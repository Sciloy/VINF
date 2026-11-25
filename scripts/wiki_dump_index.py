"""Select candidate pages from a local Wikimedia multistream XML dump."""

import bz2
import hashlib
import html
from pathlib import Path
import re
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from spark_recipes import ALIASES
from wiki_fields import article_links
from wiki_matching import read_recipe_candidates, title_key


SITE = "https://dumps.wikimedia.org/enwiki/latest/"
USER_AGENT = "VINF-RecipeSearch/1.0 (https://github.com/Sciloy/VINF)"
DUMP_SUFFIX = "-pages-articles-multistream.xml.bz2"
INDEX_SUFFIX = "-pages-articles-multistream-index.txt.bz2"
PAGE = re.compile(
    br"<page>\s*<title>[^<]*</title>\s*<ns>-?\d+</ns>\s*<id>(\d+)</id>.*?</page>",
    re.DOTALL,
)
REDIRECT_ELEMENT = re.compile(br'<redirect\s+title="([^"]+)"')
FOOD_LISTS = (
    "List of breads", "List of chicken dishes", "List of cookies", "List of desserts",
    "List of dumplings", "List of egg dishes", "List of noodle dishes", "List of pancakes",
    "List of pastries", "List of potato dishes", "List of rice dishes", "List of sandwiches",
    "List of soups", "List of stews",
)


def recipe_keys(recipes):
    return {row["key"] for row in read_recipe_candidates(recipes, ALIASES)}


def fetch_title_index(dump, site, user_agent):
    def request(url):
        return urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=90)

    with request(site + "enwiki-latest-sha1sums.txt") as response:
        manifest = {}
        for line in response.read().decode("utf-8").splitlines():
            if line.strip():
                digest, filename = line.split(maxsplit=1)
                manifest[filename.strip().lstrip("*")] = digest
    legacy_hash = dump.name.removesuffix(".xml.bz2")
    dump_name = next(
        (name for name, checksum in manifest.items()
         if name.endswith(DUMP_SUFFIX) and (name == dump.name or checksum == legacy_hash)),
        None,
    )
    if dump_name is None:
        raise ValueError(f"Dump {dump.name} is absent from Wikimedia's current checksum manifest")
    dump_hash = manifest[dump_name]
    index_name = dump_name.removesuffix(DUMP_SUFFIX) + INDEX_SUFFIX
    index_hash = manifest.get(index_name)
    if not index_hash:
        raise ValueError("Wikimedia's manifest has no matching multistream title index")
    index_path = dump.parent / index_name
    legacy_index = dump.parent / (index_hash + ".index.txt.bz2")
    if not index_path.exists() and legacy_index.is_file():
        legacy_index.rename(index_path)
    if index_path.is_file():
        return index_path, dump_hash

    temp = index_path.with_suffix(".partial")
    print("Downloading the small Wikipedia title index", flush=True)
    try:
        with request(site + "enwiki-latest" + INDEX_SUFFIX) as response, temp.open("wb") as target:
            copyfileobj(response, target, 1024 * 1024)
        with temp.open("rb") as source:
            if hashlib.file_digest(source, "sha1").hexdigest() != index_hash:
                raise ValueError("Wikipedia title index checksum mismatch")
        temp.replace(index_path)
    finally:
        temp.unlink(missing_ok=True)
    return index_path, dump_hash


def selected_blocks(index_path, keys, dump_size):
    """Yield byte ranges for streams with requested titles, plus expected page IDs."""
    offset = None
    ids = set()
    with bz2.open(index_path, mode="rt", encoding="utf-8") as source:
        for line in source:
            start, page_id, title = line.rstrip("\r\n").split(":", 2)
            start = int(start)
            if start != offset:
                if ids:
                    yield offset, start, ids
                offset, ids = start, set()
            if title_key(title) in keys:
                ids.add(int(page_id))
    if ids:
        yield offset, dump_size, ids


def candidate_xml(dump, recipes, site=SITE, user_agent=USER_AGENT, index_path=None):
    if index_path is None:
        local_index = dump.with_name(dump.name.removesuffix(DUMP_SUFFIX) + INDEX_SUFFIX)
        index_path = local_index if local_index.is_file() else fetch_title_index(dump, site, user_agent)[0]
    index_path = index_path.resolve(strict=True)
    list_keys = {title_key(title) for title in FOOD_LISTS}
    keys = recipe_keys(recipes)
    fingerprint = [*sorted(keys | list_keys)]
    for path in (dump, index_path):
        info = path.stat()
        fingerprint.extend([path.name, str(info.st_size), str(info.st_mtime_ns)])
    key_hash = hashlib.sha256("\n".join(fingerprint).encode("utf-8")).hexdigest()
    output = dump.parent / f"{key_hash[:16]}.outer-v2.candidates.xml"
    if output.is_file():
        print(f"Using existing Wikipedia candidates: {output.name}", flush=True)
        return output

    print(f"Looking up {len(keys)} recipe titles and {len(list_keys)} Wikipedia food lists", flush=True)
    keys.update(list_keys)
    size = dump.stat().st_size
    temporary = None
    written = set()
    lists_read = set()
    try:
        with dump.open("rb") as source, NamedTemporaryFile(mode="wb", dir=dump.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<mediawiki>\n")
            requested = set()
            # Food lists can redirect before yielding their links. Those linked pages can redirect too.
            for round_number in range(5):
                if not keys:
                    break
                requested.update(keys)
                if round_number:
                    print(f"Looking up {len(keys)} linked Wikipedia titles and redirects", flush=True)
                blocks = list(selected_blocks(index_path, keys, size))
                if not blocks and round_number == 0:
                    raise ValueError("The Wikipedia title index contains no candidate pages")
                print(f"Reading {len(blocks)} Wikipedia blocks (pass {round_number + 1})", flush=True)
                next_keys = set()
                for number, (start, end, expected_ids) in enumerate(blocks, 1):
                    if not 0 <= start < end <= size:
                        raise ValueError(f"Invalid dump offsets: {start}–{end}")
                    source.seek(start)
                    block = bz2.decompress(source.read(end - start))
                    found_ids = set()
                    for page in PAGE.finditer(block):
                        page_id = int(page[1])
                        if page_id not in expected_ids:
                            continue
                        found_ids.add(page_id)
                        raw_page = page[0]
                        header = raw_page.split(b"<revision>", 1)[0]
                        start_title = header.index(b"<title>") + len(b"<title>")
                        title = title_key(html.unescape(header[start_title:header.index(b"</title>")].decode("utf-8")))
                        list_page = title in list_keys
                        if redirect := REDIRECT_ELEMENT.search(header):
                            destination = title_key(html.unescape(redirect[1].decode("utf-8")).split("#", 1)[0])
                            next_keys.add(destination)
                            if list_page:
                                list_keys.add(destination)
                        elif list_page:
                            tree = ElementTree.fromstring(raw_page)
                            links = article_links(tree.findtext("revision/text"))
                            next_keys.update(title_key(link) for link in links)
                            lists_read.add(title)
                        if page_id not in written:
                            target.write(raw_page + b"\n")
                            written.add(page_id)
                    if found_ids != expected_ids:
                        raise ValueError(f"Dump does not match the title index at byte {start}")
                    if number % 50 == 0 or number == len(blocks):
                        print(f"Wikipedia blocks read: {number}/{len(blocks)}", flush=True)
                keys = next_keys - requested
            target.write(b"</mediawiki>\n")
        if not lists_read:
            raise ValueError("No Wikipedia food list could be read from this dump")
        temporary.replace(output)
        print(f"Read {len(lists_read)} Wikipedia food lists and collected {len(written)} candidate pages", flush=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output
