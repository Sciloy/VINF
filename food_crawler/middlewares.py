"""Stop requesting pages when the website refuses or rate-limits the crawler."""

from scrapy.exceptions import IgnoreRequest
from scrapy.utils.defer import deferred_from_coro


class StopOnBlockedResponseMiddleware:
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
        # This includes robots.txt responses, which never reach spider.parse().
        if response.status in (403, 429):
            request.meta["dont_retry"] = True
            if self.stopping:
                return response
            self.stopping = True
            self.crawler.spider.logger.error(
                "Stopping crawl: HTTP %s from %s. Do not resume until the cause is understood.",
                response.status, response.url,
            )
            # Schedule shutdown without awaiting it here: shutdown waits for this
            # download to finish. Returning the response still allows it to be saved.
            deferred_from_coro(
                self.crawler.engine.close_spider_async(reason=f"http_{response.status}")
            )
        return response
