"""Sťahovanie receptov z Food.com a ukladanie HTML s metadátami."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import scrapy
from scrapy import signals
from scrapy.utils.defer import deferred_from_coro

from food_crawler.dataset import read_jsonl
from food_crawler.extraction import ExtractionError, extract_recipe
from food_crawler.diversity import DiversitySkip, FamilyQuota, dish_family

RECIPE_PATH = re.compile(r"/recipe/(?P<slug>[a-zA-Z0-9-]+)-(?P<recipe_id>[0-9]+)/?")
DISCOVERY_PATH = re.compile(
    r"/(?:html-sitemap|recipe|topic(?:/[a-z0-9-]+)?|ideas/[a-z0-9-]+)/?", re.I
)


def recipe_url_details(url):
    """REGEX overí cestu URL; vráti jednotnú URL, ID receptu a slug."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in (
        "food.com",
        "www.food.com",
    ):
        return None
    match = RECIPE_PATH.fullmatch(parts.path)
    if match is None:
        return None
    recipe_id, slug = match.group("recipe_id", "slug")
    return f"https://www.food.com/recipe/{slug}-{recipe_id}", recipe_id, slug


def discovery_url(url):
    """Povolí iba prehľadové stránky na Food.com."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in (
        "food.com",
        "www.food.com",
    ):
        return None
    if parts.path not in ("", "/") and not DISCOVERY_PATH.fullmatch(parts.path):
        return None
    return "https://www.food.com" + (parts.path.rstrip("/") or "/")


def boolean_argument(value):
    if str(value).lower() not in ("true", "false"):
        raise ValueError("Spider boolean arguments must be true or false")
    return str(value).lower() == "true"


class FoodSpider(scrapy.Spider):
    name = "food"
    allowed_domains = ["food.com"]
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

    def __init__(
        self,
        rediscover="false",
        retry_failed="false",
        seeds_file=None,
        discovery_file=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.rediscover = boolean_argument(rediscover)
        self.retry_failed = boolean_argument(retry_failed)
        self.seeds_file = seeds_file
        self.discovery_file = discovery_file
        self.saved_pages = self.valid_pages = 0
        self.stopping = False
        self.discovery_scheduled = set()
        self.known_ids = set()
        self.invalid_ids = set()
        self.attempted_ids = set()
        self.retry_urls = []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.opened, signal=signals.spider_opened)
        return spider

    def opened(self):
        """Pri štarte načíta limity a históriu, aby obnova nesťahovala to isté."""
        self.started_monotonic = time.monotonic()
        self.soft_failures = 0
        self.root = Path(self.settings["PROJECT_ROOT"])
        self.raw_dir = Path(self.settings["RAW_HTML_DIR"])
        self.error_dir = self.root / "data/errors"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.error_dir.mkdir(parents=True, exist_ok=True)
        self.target_bytes = self.settings.getint("CRAWL_TARGET_BYTES")
        self.discovery_limit = self.settings.getint("DISCOVERY_PAGE_LIMIT")
        self.crawl_limit = self.settings.getint("CLOSESPIDER_ITEMCOUNT")
        self.total_bytes = 0
        exclusions = self.root / "config/excluded_recipes.json"
        self.excluded_ids = set()
        if exclusions.exists():
            excluded_recipes = json.loads(exclusions.read_text(encoding="utf-8"))
            for recipe in excluded_recipes:
                self.excluded_ids.add(str(recipe["recipe_id"]))
        self.diversity = FamilyQuota(
            self.settings.getint("DISH_FAMILY_MAX_PAGES", 20),
            self.settings.getbool("DIVERSITY_ENABLED", False),
        )
        processed = {}
        for row in read_jsonl(self.root / "data/processed/recipes.jsonl"):
            processed[str(row["recipe_id"])] = row
        if self.target_bytes < 0 or self.discovery_limit < 0:
            raise ValueError("Crawl byte target and discovery limit cannot be negative")
        # Pri opakovanom ID platí posledný záznam v JSONL.
        metadata = {}
        for row in read_jsonl(self.root / "data/crawl_metadata.jsonl"):
            if "recipe_id" in row:
                metadata[str(row["recipe_id"])] = row
        for key, row in metadata.items():
            if row.get("is_recipe") is False or row.get("http_status", 200) != 200:
                self.invalid_ids.add(key)
                if row.get("url"):
                    self.retry_urls.append(row["url"])
        for row in read_jsonl(self.root / "data/crawl_failures.jsonl"):
            details = recipe_url_details(row.get("url", ""))
            if details is not None:
                self.invalid_ids.add(details[1])
                self.retry_urls.append(details[0])
        for path in self.raw_dir.glob("*.html"):
            record = metadata.get(path.stem, {})
            try:
                if record.get("http_status", 200) != 200:
                    raise ExtractionError("Previous HTTP error")
                if not record.get("is_recipe"):
                    extract_recipe(path.read_text(encoding="utf-8", errors="replace"))
            except ExtractionError:
                self.invalid_ids.add(path.stem)
            else:
                self.known_ids.add(path.stem)
                self.total_bytes += path.stat().st_size
                title = processed.get(path.stem, {}).get("title") or record.get("title")
                if title is None:
                    title = extract_recipe(
                        path.read_text(encoding="utf-8", errors="replace")
                    )["title"]
                self.diversity.register(path.stem, title)
        self.initial_bytes = self.total_bytes
        self.crawler.stats.set_value("dataset/initial_valid_bytes", self.total_bytes)
        self.logger.info(
            "Existing valid recipes: %s | bytes: %s | target: %s",
            len(self.known_ids),
            self.total_bytes,
            self.target_bytes or "unlimited",
        )

    def stop_at_target(self):
        """STOP súbor alebo dosiahnutý počet bajtov vyvolá čisté zatvorenie."""
        stop_file = self.settings.get("CRAWL_STOP_FILE")
        if stop_file and Path(stop_file).exists():
            if not self.stopping:
                self.stopping = True
                deferred_from_coro(
                    self.crawler.engine.close_spider_async(reason="requested_stop")
                )
            return True
        if self.target_bytes and self.total_bytes >= self.target_bytes:
            if not self.stopping:
                self.stopping = True
                deferred_from_coro(
                    self.crawler.engine.close_spider_async(
                        reason="target_bytes_reached"
                    )
                )
            return True
        return self.stopping

    async def start(self):
        """Odovzdá Scrapy počiatočné URL; ďalšie URL pribúdajú z callbackov."""
        if self.stop_at_target():
            return
        seeds = list(self.start_urls)
        if self.retry_failed:
            seeds.extend(self.retry_urls)
        if self.seeds_file:
            seeds.extend(self.read_url_file(Path(self.seeds_file)))
        for url in seeds:
            request = self.recipe_request(url)
            if request is not None:
                yield request
        discovery_path = (
            Path(self.discovery_file)
            if self.discovery_file
            else self.root / "config/discovery_urls.txt"
        )
        for url in self.read_url_file(discovery_path):
            request = self.listing_request(url, depth=0)
            if request is not None:
                yield request
        if self.rediscover:
            # Obnoví odkazy z už uloženého HTML.
            for path in self.raw_dir.glob("*.html"):
                if path.stem in self.known_ids:
                    response = scrapy.http.HtmlResponse(
                        url="https://www.food.com/",
                        body=path.read_bytes(),
                        encoding="utf-8",
                    )
                    for request in self.discover_recipe_links(response):
                        yield request

    @staticmethod
    def read_url_file(path):
        if not path.exists():
            return []
        urls = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls

    def recipe_request(self, url, source_url=None):
        """Pripraví požiadavku iba na povolený a ešte neuložený recept."""
        recipe = recipe_url_details(url)
        if recipe is None or self.stopping:
            return None
        canonical_url, recipe_id, slug = recipe
        if recipe_id in self.excluded_ids:
            self.crawler.stats.inc_value("corpus/reviewed_exclusion")
            return None
        if recipe_id in self.known_ids:
            self.crawler.stats.inc_value("local_html/skipped")
            return None
        if recipe_id in self.invalid_ids and not self.retry_failed:
            self.crawler.stats.inc_value("local_html/invalid_skipped")
            return None
        retry = self.retry_failed and recipe_id in self.invalid_ids
        if retry and recipe_id in self.attempted_ids:
            return None
        self.attempted_ids.add(recipe_id)
        return scrapy.Request(
            canonical_url,
            # Úspešná odpoveď ide do parse(); konečná chyba do request_failed().
            callback=self.parse,
            errback=self.request_failed,
            dont_filter=retry,
            meta={"source_url": source_url},
        )

    def listing_request(self, url, depth):
        canonical = discovery_url(url)
        if (
            canonical is None
            or self.stopping
            or canonical in self.discovery_scheduled
            or len(self.discovery_scheduled) >= self.discovery_limit
        ):
            return None
        self.discovery_scheduled.add(canonical)
        return scrapy.Request(
            canonical,
            callback=self.parse_listing,
            errback=self.request_failed,
            meta={"listing_depth": depth},
        )

    def discover_recipe_links(self, response):
        """Z odkazov v HTML pripraví požiadavky na recepty."""
        for href in response.css("a::attr(href)").getall():
            try:
                request = self.recipe_request(response.urljoin(href), response.url)
            except ValueError:
                continue
            if request is not None:
                yield request

    def parse_listing(self, response):
        """Z prehľadovej stránky vyberie odkazy, neukladá ju ako recept."""
        if self.stop_at_target():
            return
        if response.status != 200:
            self.record_failure(
                {
                    "url": response.url,
                    "http_status": response.status,
                    "kind": "listing_http",
                }
            )
            return
        recipes = list(self.discover_recipe_links(response))
        with (self.root / "data/discovery_responses.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                json.dumps(
                    {
                        "url": response.url,
                        "http_status": response.status,
                        "recipe_candidates": len(recipes),
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                + "\n"
            )
        yield from recipes
        depth = response.meta.get("listing_depth", 0)
        if depth < self.settings.getint("DISCOVERY_MAX_DEPTH"):
            for href in response.css("a::attr(href)").getall():
                try:
                    request = self.listing_request(response.urljoin(href), depth + 1)
                except ValueError:
                    continue
                if request is not None:
                    yield request

    def parse(self, response):
        """Overí odpoveď, extrahuje recept, uloží HTML a odovzdá metadáta."""
        if self.stop_at_target():
            return
        recipe = recipe_url_details(response.url)
        if recipe is None:
            self.record_failure({"url": response.url, "kind": "non_recipe_redirect"})
            return
        _, recipe_id, slug = recipe
        if recipe_id in self.excluded_ids:
            return
        self.attempted_ids.add(recipe_id)
        if recipe_id in self.known_ids:
            return
        now = datetime.now(timezone.utc)
        # 1. Validácia HTTP a povinných polí ešte pred uložením do korpusu.
        try:
            if response.status != 200:
                raise ExtractionError(f"HTTP status {response.status}")
            content_type = response.headers.get("Content-Type", b"").decode("latin-1")
            if content_type and "html" not in content_type.lower():
                raise ExtractionError(f"Unexpected Content-Type: {content_type}")
            if not isinstance(response, scrapy.http.TextResponse):
                raise ExtractionError("Non-text response")
            extracted = extract_recipe(response.text, recipe_id, response.url)
            error = None
        except ExtractionError as exc:
            extracted, error = None, str(exc)
        if extracted and not self.diversity.permits(extracted["title"]):
            self.defer_for_diversity(
                response.url, recipe_id, extracted["title"], "response_title"
            )
            yield from self.discover_recipe_links(response)
            return
        # 404/410 znamená chýbajúci recept, nie blokovanie alebo zmenu šablóny.
        missing_page = response.status in (404, 410)
        # 2. Chybové HTML má vlastný priečinok a nezvyšuje platný objem dát.
        if error:
            if not missing_page:
                self.soft_failures += 1
            html_file = (
                self.error_dir / f"{recipe_id}-{now.strftime('%Y%m%dT%H%M%S%fZ')}.html"
            )
            self.record_failure(
                {
                    "recipe_id": recipe_id,
                    "url": response.url,
                    "http_status": response.status,
                    "kind": "invalid_recipe",
                    "reason": error,
                    "html_file": html_file.relative_to(self.root).as_posix(),
                }
            )
            self.invalid_ids.add(recipe_id)
        else:
            html_file = self.raw_dir / f"{recipe_id}.html"
            if html_file.exists():
                backup = (
                    self.error_dir
                    / f"{recipe_id}-legacy-{now.strftime('%Y%m%dT%H%M%S%fZ')}.html"
                )
                backup.write_bytes(html_file.read_bytes())
        temporary = html_file.with_suffix(".html.tmp")
        # Dočasný súbor bráni tomu, aby po prerušení zostalo neúplné raw HTML.
        temporary.write_bytes(response.body)
        temporary.replace(html_file)
        if extracted:
            self.soft_failures = 0
            self.known_ids.add(recipe_id)
            self.invalid_ids.discard(recipe_id)
            self.valid_pages += 1
            self.total_bytes += len(response.body)
            self.diversity.register(recipe_id, extracted["title"])
        self.saved_pages += 1
        self.crawler.stats.set_value("dataset/valid_bytes", self.total_bytes)
        self.crawler.stats.inc_value(
            "recipes/valid" if extracted else "recipes/invalid"
        )
        self.logger.info(
            "Saved %s | valid %s | dataset %.2f MB | HTTP %s | %s",
            self.saved_pages,
            self.valid_pages,
            self.total_bytes / 1_000_000,
            response.status,
            response.url,
        )
        self.record_speed()
        # 3. Scrapy exportuje tento slovník ako jeden riadok crawl_metadata.jsonl.
        yield {
            "url": response.url,
            "recipe_id": recipe_id,
            "slug": slug,
            "http_status": response.status,
            "html_file": html_file.relative_to(self.root).as_posix(),
            "html_bytes": len(response.body),
            "title": extracted["title"] if extracted else None,
        }
        if not missing_page and self.soft_failures >= self.settings.getint(
            "SOFT_FAILURE_LIMIT", 3
        ):
            self.stopping = True
            deferred_from_coro(
                self.crawler.engine.close_spider_async(
                    reason="soft_block_or_template_change"
                )
            )
            return
        if self.stop_at_target() or not extracted:
            return
        yield from self.discover_recipe_links(response)

    def record_failure(self, record):
        record = {"recorded_at": datetime.now(timezone.utc).isoformat(), **record}
        with (self.root / "data/crawl_failures.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.crawler.stats.inc_value("crawl/failures")

    def request_failed(self, failure):
        """Eviduje konečné chyby; odmietnutie kvótou nie je sieťová chyba."""
        if failure.check(DiversitySkip):
            return
        self.record_failure(
            {
                "url": failure.request.url,
                "source_url": failure.request.meta.get("source_url"),
                "kind": "network_or_request",
                "reason": str(failure.value),
            }
        )
        self.logger.warning(
            "Request failed: %s | %s", failure.request.url, failure.value
        )
        self.soft_failures += 1
        if (
            self.soft_failures >= self.settings.getint("SOFT_FAILURE_LIMIT", 3)
            and not self.stopping
        ):
            self.stopping = True
            deferred_from_coro(
                self.crawler.engine.close_spider_async(reason="network_errors")
            )

    def defer_for_diversity(self, url, recipe_id, title, phase):
        family, known = dish_family(title)
        self.crawler.stats.inc_value("diversity/skipped")
        with (self.root / "data/diversity_deferred.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                json.dumps(
                    {
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "url": url,
                        "recipe_id": recipe_id,
                        "dish_family": family,
                        "known_rule": known,
                        "phase": phase,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def record_speed(self):
        elapsed = max(time.monotonic() - self.started_monotonic, 0.001)
        added = self.total_bytes - self.initial_bytes
        sample = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "new_valid_pages": self.valid_pages,
            "new_raw_bytes": added,
            "total_valid_bytes": self.total_bytes,
            "pages_per_minute": self.valid_pages * 60 / elapsed,
            "MB_per_minute": added / 1_000_000 * 60 / elapsed,
            "http_requests": self.crawler.stats.get_value(
                "downloader/request_count", 0
            ),
            "family_skips": self.crawler.stats.get_value("diversity/skipped", 0),
        }
        with (self.root / "data/speed_samples.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(json.dumps(sample) + "\n")
        return sample

    def closed(self, reason):
        if not hasattr(self, "root"):
            return
        now = datetime.now(timezone.utc)
        report_dir = self.root / "data/runs"
        report_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "closed_at": now.isoformat(),
            "reason": reason,
            "new_saved_responses": self.saved_pages,
            "new_valid_recipes": self.valid_pages,
            "initial_valid_bytes": self.initial_bytes,
            "final_valid_bytes": self.total_bytes,
            "settings": {
                key: self.settings.get(key)
                for key in (
                    "USER_AGENT",
                    "ROBOTSTXT_OBEY",
                    "DOWNLOAD_DELAY",
                    "DOWNLOAD_DELAY_JITTER",
                    "CONCURRENT_REQUESTS",
                    "DOWNLOAD_TIMEOUT",
                    "RETRY_TIMES",
                    "CRAWL_TARGET_BYTES",
                    "CLOSESPIDER_ITEMCOUNT",
                    "CLOSESPIDER_TIMEOUT",
                    "JOBDIR",
                )
            },
            "scrapy_stats": self.crawler.stats.get_stats(),
            "speed": self.record_speed(),
            "dish_family_counts": dict(self.diversity.counts.most_common()),
        }
        (report_dir / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        self.logger.info(
            "Crawl finished | new valid recipes: %s | total bytes: %s | reason: %s",
            self.valid_pages,
            self.total_bytes,
            reason,
        )
