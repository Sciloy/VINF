"""Kontroly pred a po HTTP požiadavke: kvóty, chyby a ochranné zastavenie."""

from scrapy.exceptions import IgnoreRequest
from scrapy.utils.defer import deferred_from_coro

from food_crawler.spiders.food import recipe_url_details
from food_crawler.diversity import DiversitySkip


class DiversityAdmissionMiddleware:
    """Preskočí známe a nadlimitné recepty ešte pred ich stiahnutím."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        recipe = recipe_url_details(request.url)
        spider = self.crawler.spider
        if (
            hasattr(spider, "stop_at_target")
            and hasattr(spider, "target_bytes")
            and spider.stop_at_target()
        ):
            raise DiversitySkip("Crawl is stopping")
        if recipe is None or not hasattr(spider, "diversity"):
            return
        canonical_url, recipe_id, slug = recipe
        excluded_ids = getattr(spider, "excluded_ids", set())
        if recipe_id in excluded_ids:
            self.crawler.stats.inc_value("corpus/reviewed_exclusion")
            raise DiversitySkip("Reviewed corpus exclusion")
        if recipe_id in spider.known_ids:
            self.crawler.stats.inc_value("diversity/already_stored")
            raise DiversitySkip("Recipe is already stored")
        title_hint = slug.replace("-", " ")
        if not spider.diversity.permits(title_hint):
            spider.defer_for_diversity(
                request.url, recipe_id, title_hint, "before_download"
            )
            raise DiversitySkip("Dish family quota reached")


class AttachRecipeErrbackMiddleware:
    """Pripojí spracovanie chýb aj k požiadavkám z uloženej fronty."""

    def __init__(self, crawler):
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        if request.errback is None and recipe_url_details(request.url) is not None:
            request.errback = self.crawler.spider.request_failed


class StopOnBlockedResponseMiddleware:
    """Zastaví zber pri odmietnutí alebo chybe servera."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.stopping = False

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_request(self, request):
        if self.stopping:
            raise IgnoreRequest("The crawl is stopping after a blocked response")

    def process_response(self, request, response):
        # Kontroluje sa aj odpoveď robots.txt.
        stop_on_server_error = self.crawler.settings.getbool(
            "STOP_ON_SERVER_ERROR", True
        )
        server_unavailable = (
            response.status in (500, 502, 503, 504) and stop_on_server_error
        )
        access_refused = response.status in (403, 429)
        if access_refused or server_unavailable:
            request.meta["dont_retry"] = True
            if self.stopping:
                return response
            self.stopping = True
            self.crawler.spider.logger.error(
                "Zber zastavený: HTTP %s z %s.",
                response.status,
                response.url,
            )
            # Zatváranie počká na dokončenie aktuálnej odpovede.
            deferred_from_coro(
                self.crawler.engine.close_spider_async(reason=f"http_{response.status}")
            )
        return response
