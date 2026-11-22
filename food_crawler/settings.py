"""Nastavenia Scrapy crawlera."""

from pathlib import Path

BOT_NAME = "food_crawler"
SPIDER_MODULES = ["food_crawler.spiders"]
NEWSPIDER_MODULE = "food_crawler.spiders"

USER_AGENT = "VINF-RecipeCrawler (student project)"
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 20
DOWNLOAD_DELAY_JITTER = 0
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_TIMEOUT = 60
RETRY_ENABLED = True
RETRY_TIMES = 0
STOP_ON_SERVER_ERROR = True
HTTPERROR_ALLOW_ALL = True

# Chyby servera sa kontrolujú pred automatickým opakovaním požiadavky.
DOWNLOADER_MIDDLEWARES = {
    "food_crawler.middlewares.AttachRecipeErrbackMiddleware": 60,
    "food_crawler.middlewares.DiversityAdmissionMiddleware": 70,
    "food_crawler.middlewares.StopOnBlockedResponseMiddleware": 650,
}

# Pri pomalšej odozve sa odstup požiadaviek zväčší.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 20
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5

DEPTH_PRIORITY = 1
SCHEDULER_MEMORY_QUEUE = "scrapy.squeues.FifoMemoryQueue"
SCHEDULER_DISK_QUEUE = "scrapy.squeues.PickleFifoDiskQueue"
REQUEST_FINGERPRINTER_CLASS = "food_crawler.fingerprints.RecipeRequestFingerprinter"

CLOSESPIDER_ITEMCOUNT = 20
CLOSESPIDER_TIMEOUT = 1800
CRAWL_TARGET_BYTES = 3_000_000_000
DISCOVERY_PAGE_LIMIT = 30
DISCOVERY_MAX_DEPTH = 1
DIVERSITY_ENABLED = True
DISH_FAMILY_MAX_PAGES = 20
SOFT_FAILURE_LIMIT = 1

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_HTML_DIR = PROJECT_ROOT / "data" / "raw"
JOBDIR = str(PROJECT_ROOT / "data" / "crawl_state")

# Každá stiahnutá stránka pridá jeden riadok metadát.
FEEDS = {
    PROJECT_ROOT
    / "data"
    / "crawl_metadata.jsonl": {
        "format": "jsonlines",
        "encoding": "utf-8",
        "overwrite": False,
    }
}

LOG_LEVEL = "INFO"
TELNETCONSOLE_ENABLED = False
REMOTE_CONTROL_ENABLED = False
