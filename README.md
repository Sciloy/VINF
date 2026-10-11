# Food.com raw-page crawler

A small university project using Python and Scrapy. This first stage downloads
raw recipe pages, records crawl metadata, and discovers additional recipe URLs.
It does not extract recipe content or match anything to Wikipedia.

## Files and architecture

```text
requirements.txt                 Scrapy dependency
scrapy.cfg                       Selects the project settings
food_crawler/
    __init__.py
    settings.py                  Crawl limits, politeness, and JSON Lines export
    fingerprints.py              Duplicate detection by individual recipe ID
    middlewares.py               Stop on HTTP 403 / 429, including robots.txt
    spiders/
        __init__.py
        food.py                  Seed URLs, URL validation, HTML saving, links
data/                            Created automatically when crawling
    raw/<recipe-id>.html         Downloaded response bodies
    crawl_metadata.jsonl         One JSON record per saved page
    crawl_state/                 Scrapy's persistent queue and duplicate filter
scripts/
    crawl_summary.py             Local counts, sizes, statuses, and slug preview
```

The spider starts from ten varied seed recipes. For each recipe response it saves the body
and yields a metadata dictionary. Scrapy's built-in feed exporter writes that
dictionary to JSON Lines. The spider then reads HTML links and yields requests
for matching recipe URLs. Scrapy's scheduler queues them and its duplicate filter
prevents repeated requests. The custom fingerprinter identifies individual recipes
by ID even when their slugs differ. Pending requests and duplicate fingerprints
persist between batches in `data/crawl_state/`. Existing HTML files are kept and
skipped when building new requests. No custom pipeline is needed.

## Setup

Use Python 3.10 or newer. Run commands from the repository root, where
`scrapy.cfg` lives. Scrapy is pinned to 2.19.0 for a consistent configuration.

Windows PowerShell (activation is not required):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux / macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Run

Windows PowerShell, using the default limit of approximately 20 new pages:

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl food
```

For the first test, use a slower five-second base delay and a ten-minute time cap:

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=20 -s DOWNLOAD_DELAY=5 -s CLOSESPIDER_TIMEOUT=600
```

Override the limit, for example to download approximately 5 pages:

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=5
```

On Linux / macOS, use `.venv/bin/python` instead of
`.\.venv\Scripts\python.exe` in these run commands.

`CLOSESPIDER_ITEMCOUNT` counts metadata records: each saved recipe page produces
one, including HTTP error responses. This counts saved pages rather than the
robots.txt request or intermediate retry responses. It is an approximate limit:
requests already in the downloader can finish during shutdown. The project also
limits total concurrent requests to one, keeping this overrun small. Retries and
the robots.txt request can add HTTP traffic. The crawl can end before the limit
if no eligible links remain or robots.txt blocks them. Setting the limit to `0`
disables it. Limits count new pages in the current batch, not all existing files.

To change the seeds, edit `start_urls` in `food_crawler/spiders/food.py`.

The terminal shows the seed count and limit at startup, then a progress line for
each saved page at the default `INFO` log level. For example:

```text
[food] INFO: Starting crawl | seeds: 10 | saved-page limit: 20
[food] INFO: [1/20] HTTP 200 | recipe ID: 240864 | saved: data/raw/240864.html | https://www.food.com/recipe/easy-no-boil-macaroni-cheese-240864
[food] INFO: Crawl finished | saved recipe pages: 20 | reason: closespider_itemcount
```

Scrapy adds timestamps to these messages. With a limit of `0`, the counter shows
only the number saved. The closing summary includes the actual saved-page count
and the stopping reason. These messages report final recipe responses after any
retries; Scrapy logs retry attempts and network errors separately. HTTP 403 and
429 responses automatically stop the entire crawl before retries. The blocked
recipe response is still saved when it reaches the spider. The same stop rule
applies to robots.txt. Requests already in progress may finish during shutdown.
Investigate a blocking response before resuming; do not repeatedly restart it.

## Inspect the first sample

```powershell
.\.venv\Scripts\python.exe scripts\crawl_summary.py
```

Run this after a batch finishes. It reads local files only and prints HTML file
count and size, distinct recipe
IDs, repeated IDs in metadata, HTTP status counts, and the latest recipe slugs.
Open several `data/raw/<id>.html` files in your editor and check that they contain
recipe pages rather than access-denied or CAPTCHA HTML. A 200 status alone is
not proof that the body is a recipe. Inspect a mix of seed and discovered pages.

The live test on 11 October 2026 used the 20-page command above. It saved 21 new
recipe pages in about two minutes, because one request finished during shutdown.
All responses were HTTP 200, including robots.txt, with no retries or blocking
responses. Together with the two earlier pages, the dataset contains 23 distinct
recipe IDs and 11,890,864 bytes (11.89 MB) of raw HTML. Each saved file was checked
for recipe structured data and a matching recipe URL. This successful sample
does not guarantee that a larger crawl will be accepted.

The average is approximately 517 KB per page: about 968 total pages would reach
500 MB if that average holds. There are already several pancake variants in the
sample, so inspect the slugs and add dish-family sampling before scaling up.

## Continue the dataset in batches

The default `JOBDIR` stores unfinished requests and seen fingerprints. Keeping
the same directory lets the next invocation continue the dataset. Press Ctrl+C
once for a clean stop and wait for Scrapy to finish. Avoid killing the process
or running two crawlers against the same job directory. Use the same pinned
Scrapy version when resuming.

Once the sample is reviewed, permission to crawl is established, and dish-family
sampling is implemented, the batch-size controls are:

```powershell
.\.venv\Scripts\python.exe -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=500 -s DOWNLOAD_DELAY=5
.\.venv\Scripts\python.exe -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=1000 -s DOWNLOAD_DELAY=5
```

Run one command at a time. These mean about 500 or 1,000 **additional** pages per
invocation, not total dataset sizes. Start with the smaller batch and inspect
the results before increasing it. AutoThrottle can slow requests further. At a
five-second base delay, rough delay budgets are 42 minutes for 500 pages and
83 minutes for 1,000; actual times depend on responses, retries, and throttling.
Pending links may run out before the requested limit is reached.

Polite settings reduce load but cannot guarantee that a site will not block a
crawler. Check the site's applicable terms and obtain any required permission
for larger collection. Do not bypass CAPTCHA or other access restrictions.

## Exact duplicates versus dish-family sampling

A Food.com ID identifies one submitted recipe. Different IDs can describe
different versions of the same dish, so IDs are still useful for preventing exact
repeat downloads but cannot enforce a varied collection. There is no sequential
ID range that guarantees different dish families.

The current spider uses varied seeds and shallow-first, FIFO traversal. It does
not classify dish families or enforce a per-family cap. Before the larger run,
add and review a `dish_family` label and keep, for example, 5-10 variants per
family. A first version can use curated title/slug keywords with manual review;
ingredient-based similarity and synonym handling belong to the later extraction
stage. Hybrid names and recipes such as pizza dough versus pizza need clear
labeling rules. For example, 100 families with 10 variants each gives 1,000 pages.
Broaden the seeds to cover those families as well: a quota alone does not ensure
the crawler discovers enough different dishes.

Measure the raw HTML bytes rather than assuming a page count reaches 500 MB.
The local summary estimates the required page count from the observed average.
This is an estimate, since page sizes vary. HTML includes page layout, scripts,
and reviews; 500 MB of raw HTML is different from 500 MB of extracted recipe data.

## Output

The crawler creates `data/raw/` automatically. A recipe with ID `240864` is saved
as `data/raw/240864.html`. Files contain Scrapy's response body bytes without
HTML parsing or reserialization; normal HTTP decompression still applies.

Example metadata record (illustrative):

```json
{"url": "https://www.food.com/recipe/best-banana-bread-2886", "recipe_id": "2886", "slug": "best-banana-bread", "http_status": 200, "html_file": "data/raw/2886.html", "html_bytes": 420000, "crawled_at": "2026-10-11T10:00:00+00:00"}
```

Each run appends to `data/crawl_metadata.jsonl`, preserving earlier records.
Existing raw HTML files are kept. Duplicate fingerprints persist in the job
directory. The two files downloaded before persistence was added are also kept;
local file checks prevent requesting them again. `crawled_at` uses UTC and
`html_bytes` records the saved body size. Downloaded data and the virtual
environment are ignored by Git.

Final HTTP error responses, such as 403 or 404, are also saved with their status;
the spider does not discover links from those bodies. Network failures after
retries are logged by Scrapy and have no HTML body or metadata record to save.
Only links present in downloaded HTML are discovered; JavaScript is not executed.
Failed requests may already be marked as seen in the job directory. After
investigating a failure, any deliberate retry needs separate handling; resetting
all crawl state is not a substitute for investigating a block.

## URL rules and crawl settings

Accepted recipe URLs have this structure:

```text
https://www.food.com/recipe/<recipe-name>-<numeric-id>
```

The name contains letters, digits, and hyphens. The spider resolves relative
links, accepts Food.com host variants and HTTP links, and normalizes them to
HTTPS on `www.food.com`. It removes query strings, fragments, and trailing
slashes before scheduling so tracking links do not cause duplicate downloads.
Other domains and non-recipe paths are ignored. The regular expression only
validates URLs and reads their ID/slug; it is not a recipe-content extractor.

`food_crawler/settings.py` contains:

| Setting | Value |
| --- | --- |
| `ROBOTSTXT_OBEY` | `True` |
| `USER_AGENT` | `VINF-RecipeCrawler/0.1 (student project)` |
| `DOWNLOAD_DELAY` | 2 seconds |
| `DOWNLOAD_DELAY_JITTER` | `0.5` (random delays between 1 and 3 seconds) |
| `CONCURRENT_REQUESTS` | 1 |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | 1 |
| `DOWNLOAD_TIMEOUT` | 15 seconds |
| `RETRY_TIMES` | 2 retries after the initial attempt |
| `CLOSESPIDER_ITEMCOUNT` | 20 saved pages / metadata records |
| `AUTOTHROTTLE_ENABLED` | `True` |
| `AUTOTHROTTLE_START_DELAY` | 5 seconds |
| `AUTOTHROTTLE_MAX_DELAY` | 60 seconds |
| `AUTOTHROTTLE_TARGET_CONCURRENCY` | `0.5` |
| `JOBDIR` | `data/crawl_state/` |

Scrapy 2.19 uses `DOWNLOAD_DELAY_JITTER` for randomized delays. See the
[Scrapy settings documentation](https://docs.scrapy.org/en/latest/topics/settings.html#download-delay-jitter)
and the
[close-spider documentation](https://docs.scrapy.org/en/latest/topics/extensions.html#closespider-extension)
for the built-in behavior used here.
See also [persistent crawl jobs](https://docs.scrapy.org/en/latest/topics/jobs.html)
and [AutoThrottle](https://docs.scrapy.org/en/latest/topics/autothrottle.html).

For a consultation, the main parts to explain are `recipe_url_details()` (URL
validation and normalization), `start()` (seeds and output directory), `parse()`
(HTML saving, metadata, and link discovery), and `settings.py` (Scrapy behavior).
The fingerprinter gives Scrapy a recipe-ID-based duplicate key. The downloader
middleware checks response statuses before retrying and stops on 403 or 429.
