"""Overenie vzorky a spracovanie celého korpusu z PowerShellu aj na Linuxe."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "coady/pylucene:9.12.0"
SITE = "https://dumps.wikimedia.org/enwiki/latest/"
USER_AGENT = "VINF-RecipeSearch/1.0 (https://github.com/Sciloy/VINF)"


def run(command):
    # Sparkové logy a stav sťahovania Docker obrazu idú priebežne na stderr.
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, check=True)
    return result.stdout.decode("utf-8").strip()


def wiki_dump():
    folder = ROOT / "data/wiki"
    folder.mkdir(parents=True, exist_ok=True)
    filename = "enwiki-latest-pages-articles-multistream.xml.bz2"
    request = Request(SITE + "enwiki-latest-sha1sums.txt", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response:
            manifest = response.read().decode()
    except HTTPError as exc:
        raise SystemExit(f"Wikipedia checksum download failed: HTTP {exc.code} {exc.reason} ({exc.url})") from exc
    match = re.search(
        r"(?m)^([0-9a-f]{40})\s+\*?(enwiki-(?:latest|\d{8})-pages-articles-multistream\.xml\.bz2)\s*$",
        manifest,
    )
    if not match:
        raise ValueError("Wikipedia checksum missing for " + filename)
    digest, dump_name = match.groups()
    destination = folder / dump_name
    legacy = folder / (digest + ".xml.bz2")
    if not destination.exists() and legacy.is_file():
        legacy.rename(destination)
    if not destination.exists():
        partial = destination.with_suffix(".bz2.partial")
        legacy_partial = legacy.with_suffix(".bz2.partial")
        if not partial.exists() and legacy_partial.is_file():
            legacy_partial.rename(partial)
        print("Downloading Wikipedia dump to", partial, flush=True)
        subprocess.run(["curl.exe" if os.name == "nt" else "curl", "--fail", "--location",
                        "--user-agent", USER_AGENT, "--retry", "3", "--continue-at", "-",
                        "--output", str(partial), SITE + filename], check=True)
        with partial.open("rb") as stream:
            if hashlib.file_digest(stream, "sha1").hexdigest() != digest:
                partial.rename(folder / (uuid4().hex + ".checksum-failed"))
                raise ValueError("Dump checksum mismatch. Run again to download the current snapshot.")
        partial.replace(destination)
    return destination


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def check(sample, dump, spark_input=None):
    base = "examples" if sample else "."
    cli = ["scripts/vinf.py", "--root", base]
    docker = ["docker", "run", "--rm", "--mount", f"type=bind,source={ROOT},target=/vinf",
              "-w", "/vinf", "--entrypoint", "python3", IMAGE, *cli]
    output = ROOT / base / "data/part2"
    source = ROOT / base / "data/processed/recipes.jsonl"
    print(f"Starting Spark join ({base})", flush=True)
    spark_output = run([sys.executable, *cli, "spark-join", str(spark_input or dump)])
    # Windows môže po JSON štatistike dopísať stav ukončenia procesov JVM.
    stats, end = json.JSONDecoder().raw_decode(spark_output)
    if trailing := spark_output[end:].strip():
        print(trailing, file=sys.stderr)
    print(base, stats, flush=True)
    rows = read_rows(output / "recipes.jsonl")
    ids = {row["recipe_id"] for row in rows}
    source_recipes = {row["recipe_id"]: row for row in read_rows(source)}
    matched = [row for row in rows if row["source"] == "both"]
    unmatched = [row for row in rows if row["source"] == "foodcom"]
    wiki_only = [row for row in rows if row["source"] == "wikipedia"]
    expected = dict(recipes=len(rows), foodcom_recipes=len(source_recipes), matched=len(matched),
                    unmatched=len(unmatched), wikipedia_only=len(wiki_only),
                    unique_wiki_pages=len({row["wiki_id"] for row in matched}))
    require({row["recipe_id"] for row in matched + unmatched} == source_recipes.keys() and len(ids) == len(rows),
            "Lost or duplicate recipe IDs")
    require(all(all(row.get(key) == original for key, original in source_recipes[row["recipe_id"]].items())
                for row in matched + unmatched), "Changed Food.com fields")
    require(all(row.get("wiki_title") for row in matched), "A matched Wikipedia page has no metadata")
    wiki_ids = {row["wiki_id"] for row in wiki_only}
    require(len(wiki_ids) == len(wiki_only) and wiki_ids.isdisjoint(row["wiki_id"] for row in matched),
            "Added a duplicate Wikipedia page")
    require(wiki_only and all(row["instructions"] and row["recipe_id"] == f'wiki{row["wiki_id"]}' for row in wiki_only),
            "Wikipedia-only recipes must have a preparation description and a wiki ID")
    require(stats == expected, "Spark statistics disagree with saved rows")
    if sample:
        require(any(row["recipe_id"] == "2886" and row.get("wiki_title") == "Banana bread" for row in matched),
                "A redirect with the same normalized title hid the canonical article")
        require(stats["foodcom_recipes"] == 16 and stats["matched"] == 3
                and stats["unique_wiki_pages"] == 2 and wiki_ids == {3},
                "Wrong fixture join")
    require(matched, "No Wikipedia articles matched")
    match_types = dict(sorted(Counter(row.get("wiki_match_type") or "unknown" for row in matched).items()))
    print("Wikipedia match types:", match_types, flush=True)
    indexed = json.loads(run([*docker, "lucene-index"]))
    require(indexed["indexed_recipes"] == len(rows), "Index count differs from corpus")
    require(indexed["source_counts"] == {"foodcom": len(unmatched), "both": len(matched), "wikipedia": len(wiki_only)},
            "Index counts by source differ from corpus")
    cases = []

    def search(query, *options):
        hits = json.loads(run([*docker, "lucene-search", query, *options]))
        cases.append(dict(query=query, options=options, hits=[
            dict(recipe_id=r["recipe_id"], title=r["title"], wiki_title=r.get("wiki_title"),
                 wiki_match_type=r.get("wiki_match_type"), source=r["source"], score=r["score"])
            for r in hits]))
        return hits

    if sample:
        hits = search("wiki_ingredients:banana")
        require(any(row["recipe_id"] == "2886" for row in hits), "Wrong wiki ingredient match")
    else:
        example = min(matched, key=lambda row: row["recipe_id"])
        title = example["wiki_title"].replace("\\", "\\\\").replace('"', '\\"')
        hits = search(f'recipe_id:{example["recipe_id"]} AND wiki_title:"{title}"')
        require(len(hits) == 1 and hits[0].get("wiki_id") == example["wiki_id"], "Wrong real article match")
    example = min(wiki_only, key=lambda row: row["recipe_id"])
    hits = search(f'source:wikipedia AND recipe_id:"{example["recipe_id"]}"')
    require(len(hits) == 1 and hits[0]["instructions"] == example["instructions"],
            "The index cannot retrieve an independently discovered Wikipedia preparation")
    if unmatched:
        identifier = min(row["recipe_id"] for row in unmatched)
        hits = search("recipe_id:" + identifier)
        require(len(hits) == 1 and hits[0]["recipe_id"] == identifier and hits[0].get("wiki_id") is None,
                "Recipe without Wikipedia article missing from search")
    hits = search('title:"banana bread"')
    require(hits and all(re.search(r"\bbanana\W+bread\b", row["title"], re.I) for row in hits), "Wrong title phrase")
    hits = search("pancakes", "--max-minutes", "30")
    require(hits and all(row["total_time_minutes"] <= 30 for row in hits), "Wrong time filter")
    require(not search("recipe_id:vinfmissingid"), "Expected empty result")
    if not sample:
        if "282620" in ids:
            hits = search("recipe_id:282620")
            require(len(hits) == 1, "Ground Beef and Potatoes is missing from PyLucene")
            print("Ground Beef and Potatoes:", hits[0].get("wiki_title") or "no Wikipedia link", flush=True)
        table = run([*docker, "evaluate"])
        (output / "comparison.md").write_text(table + "\n", encoding="utf-8")
    report = dict(dump=str(dump), join=stats, wiki_match_types=match_types, index=indexed, cases=cases)
    path = output / "test-results.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS:", path, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Po vzorke spracuje aj celý korpus")
    parser.add_argument("--dump", type=Path, help="Existujúci lokálny dump pre celý korpus")
    parser.add_argument("--indexed", action="store_true", help="Vyberie kandidátov z dumpu pomocou Wikimedia multistream indexu")
    parser.add_argument("--title-index", type=Path, help="Lokálny index názvov pre --indexed")
    args = parser.parse_args()
    if args.dump and not args.full:
        parser.error("--dump requires --full")
    if args.indexed and not args.full:
        parser.error("--indexed requires --full")
    if args.title_index and not args.indexed:
        parser.error("--title-index requires --indexed")
    os.environ["PYSPARK_PYTHON"] = sys.executable
    run(["docker", "info", "--format", "{{.ServerVersion}}"])
    check(True, ROOT / "tests/fixtures/wiki_sample.xml")
    if args.full:
        dump = args.dump.resolve(strict=True) if args.dump else wiki_dump()
        spark_input = None
        if args.indexed:
            from wiki_dump_index import candidate_xml

            spark_input = candidate_xml(dump, ROOT / "data/processed/recipes.jsonl", SITE, USER_AGENT,
                                        index_path=args.title_index)
        check(False, dump, spark_input)
