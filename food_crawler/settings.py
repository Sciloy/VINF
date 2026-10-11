"""Project settings: polite downloads, a small crawl, and metadata export."""

from pathlib import Path

BOT_NAME = "food_crawler"
SPIDER_MODULES = ["food_crawler.spiders"]
NEWSPIDER_MODULE = "food_crawler.spiders"

USER_AGENT = "VINF-RecipeCrawler (student project)"
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2
# Scrapy 2.19 uses jitter for randomization: 0.5 gives delays of 1-3 seconds.
DOWNLOAD_DELAY_JITTER = 0.5
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_TIMEOUT = 15
RETRY_ENABLED = True
RETRY_TIMES = 2  # Two retries in addition to the original request.
# Pass final HTTP error responses to parse() after RetryMiddleware is finished.
HTTPERROR_ALLOW_ALL = True
# Responses pass through higher-numbered downloader middleware first. Check for
# blocking before RetryMiddleware (priority 550), including robots.txt failures.
DOWNLOADER_MIDDLEWARES = {
    "food_crawler.middlewares.StopOnBlockedResponseMiddleware": 650,
}

# Slow down further when responses become slow; concurrency remains capped at 1.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5

# Process older links first and prefer shallow pages to explore varied seeds.
DEPTH_PRIORITY = 1
SCHEDULER_MEMORY_QUEUE = "scrapy.squeues.FifoMemoryQueue"
SCHEDULER_DISK_QUEUE = "scrapy.squeues.PickleFifoDiskQueue"
REQUEST_FINGERPRINTER_CLASS = "food_crawler.fingerprints.RecipeRequestFingerprinter"

# One metadata item represents one saved recipe page. Scrapy closes the spider
# after approximately this many items, allowing in-progress requests to finish.
# Override with: python -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=20
CLOSESPIDER_ITEMCOUNT = 20

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_HTML_DIR = PROJECT_ROOT / "data" / "raw"
# Keep pending requests and duplicate fingerprints for the next batch. Resume
# with the same JOBDIR; use one job directory for one dataset/spider only.
JOBDIR = str(PROJECT_ROOT / "data" / "crawl_state")

# Yielding a plain dictionary from the spider writes one JSON object per line.
FEEDS = {
    PROJECT_ROOT / "data" / "crawl_metadata.jsonl": {
        "format": "jsonlines",
        "encoding": "utf-8",
        "overwrite": False,  # Append new batches without losing earlier metadata.
    }
}

LOG_LEVEL = "INFO"  # Show startup, per-page progress, and the closing summary.
TELNETCONSOLE_ENABLED = False
REMOTE_CONTROL_ENABLED = False
