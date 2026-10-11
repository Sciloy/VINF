"""Download recipe HTML and discover recipe links; do not extract recipe data."""

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import scrapy


# This expression only reads the URL, not ingredients or other recipe content.
RECIPE_PATH = re.compile(r"/recipe/(?P<slug>[a-zA-Z0-9-]+)-(?P<recipe_id>[0-9]+)/?")


def recipe_url_details(url):
    """Return (canonical URL, ID, slug) for a Food.com recipe, or None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if parts.netloc.lower() not in ("food.com", "www.food.com"):
        return None

    match = RECIPE_PATH.fullmatch(parts.path)
    if match is None:
        return None

    recipe_id = match.group("recipe_id")
    slug = match.group("slug")
    # Remove tracking queries/fragments and normalize the host and trailing slash
    # so Scrapy's duplicate filter sees equivalent links as the same URL.
    canonical_url = f"https://www.food.com/recipe/{slug}-{recipe_id}"
    return canonical_url, recipe_id, slug


class FoodSpider(scrapy.Spider):
    name = "food"
    allowed_domains = ["food.com"]
    # Varied dish families help the first sample cover more than one type.
    # This improves coverage but does not classify dishes or enforce quotas.
    start_urls = [
        "https://www.food.com/recipe/best-banana-bread-2886",
        "https://www.food.com/recipe/fluffy-pancakes-16456",
        "https://www.food.com/recipe/chocolate-chip-cookies-76416",
        "https://www.food.com/recipe/classic-lasagna-56153",
        "https://www.food.com/recipe/traditional-apple-pie-469772",
        "https://www.food.com/recipe/the-best-brownies-54225",
        "https://www.food.com/recipe/our-favorite-homemade-pizza-346339",
        "https://www.food.com/recipe/award-winning-chili-105865",
        "https://www.food.com/recipe/chicken-soup-416900",
        "https://www.food.com/recipe/grandmas-homemade-macaroni-and-cheese-14471",
    ]

    async def start(self):
        self.saved_pages = 0
        self.crawl_limit = self.settings.getint("CLOSESPIDER_ITEMCOUNT")
        self.raw_dir = Path(self.settings["RAW_HTML_DIR"])
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(
            "Starting crawl | seeds: %s | saved-page limit: %s",
            len(self.start_urls),
            self.crawl_limit or "unlimited",
        )
        for url in self.start_urls:
            request = self.recipe_request(url)
            if request is not None:
                # Unlike Scrapy's default start(), this keeps duplicate filtering
                # enabled for seeds as well as links discovered later.
                yield request

    def recipe_request(self, url):
        """Build a request unless this recipe already has a local HTML file."""
        recipe = recipe_url_details(url)
        if recipe is None:
            return None
        if (self.raw_dir / f"{recipe[1]}.html").exists():
            self.crawler.stats.inc_value("local_html/skipped")
            return None
        return scrapy.Request(recipe[0], callback=self.parse)

    def parse(self, response):
        recipe = recipe_url_details(response.url)
        if recipe is None:
            self.logger.info("Ignoring redirect to a non-recipe URL: %s", response.url)
            return

        _, recipe_id, slug = recipe
        html_file = self.raw_dir / f"{recipe_id}.html"
        if html_file.exists():
            self.logger.info("Already saved recipe %s; keeping the existing file", recipe_id)
            return
        # Preserve the response body bytes without decoding or rewriting HTML.
        html_file.write_bytes(response.body)
        self.saved_pages += 1
        progress = (
            f"{self.saved_pages}/{self.crawl_limit}"
            if self.crawl_limit else str(self.saved_pages)
        )
        # INFO messages appear immediately in the terminal with Scrapy's normal
        # timestamps. Count pages only after their HTML has been saved.
        self.logger.info(
            "[%s] HTTP %s | recipe ID: %s | saved: data/raw/%s | %s",
            progress, response.status, recipe_id, html_file.name, response.url,
        )
        yield {
            "url": response.url,
            "recipe_id": recipe_id,
            "slug": slug,
            "http_status": response.status,
            "html_file": f"data/raw/{recipe_id}.html",
            "html_bytes": len(response.body),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

        if response.status != 200:
            self.logger.warning("Saved HTTP %s response: %s", response.status, response.url)
            return

        for href in response.css("a::attr(href)").getall():
            # urljoin resolves relative links before the domain/path checks.
            try:
                request = self.recipe_request(response.urljoin(href))
            except ValueError:
                continue  # Ignore malformed links instead of losing the page.
            if request is not None:
                # No custom visited set and no dont_filter=True: Scrapy manages
                # the request queue and suppresses URLs already scheduled.
                yield request

    def closed(self, reason):
        self.logger.info(
            "Crawl finished | saved recipe pages: %s | reason: %s",
            getattr(self, "saved_pages", 0), reason,
        )
