"""Spojenie extrahovaného korpusu s anglickým pages-articles dumpom."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from wiki_fields import food_fields
from wiki_matching import food_article, read_recipe_candidates, redirect_key


ALIASES = {
    "pancakes": "pancake", "crepes": "crêpe", "cookies": "cookie",
    "lasagna": "lasagna", "waffles": "waffle", "brownies": "chocolate brownie",
    "dumplings": "dumpling", "spring_rolls": "spring roll", "tacos": "taco",
    "enchiladas": "enchilada", "burritos": "burrito", "chili": "chili con carne",
    "hot_dogs": "hot dog", "omelet": "omelette", "meatballs": "meatball",
    "muffins": "muffin", "donuts": "doughnut", "samosas": "samosa",
    "mashed_potatoes": "mashed potato", "salsa": "salsa (food)",
}

WIKI_FIELDS = ("country", "region", "cuisine", "type", "ingredients")
WIKI_SCHEMA = "id long, key string, wiki_title string, has_infobox boolean, is_food boolean, redirected boolean, wiki struct<" + ",".join(
    name + ":string" for name in WIKI_FIELDS
) + ">"


def extract_articles(pages, candidates, functions):
    articles = {}
    redirects = {}
    seen = set()

    def read_pages(rows):
        for page in rows:
            seen.add(page.key)
            if target := redirect_key(page.text):
                redirects[page.key] = target
                continue
            fields = food_fields(page.text)
            is_food = food_article(page.wiki_title, page.text)
            if fields is None and not is_food:
                continue
            record = dict(id=page.id, key=page.key, wiki_title=page.wiki_title,
                          has_infobox=fields is not None, is_food=is_food, redirected=False,
                          wiki=dict(zip(WIKI_FIELDS, fields)) if fields is not None else None)
            previous = articles.get(page.key)
            if previous is None or (not record["has_infobox"], record["id"]) < (
                not previous["has_infobox"], previous["id"]
            ):
                articles[page.key] = record

    first_pages = pages.join(functions.broadcast(candidates.select("key").distinct()), "key")
    read_pages(first_pages.toLocalIterator())
    for _ in range(2):
        targets = sorted(set(redirects.values()) - seen)
        if not targets:
            break
        seen.update(targets)
        read_pages(pages.where(functions.col("key").isin(targets)).toLocalIterator())
    for alias in redirects:
        target = redirects[alias]
        if target in redirects:
            target = redirects[target]
        if target in articles and not articles[target]["redirected"]:
            articles[alias] = {**articles[target], "key": alias, "redirected": True}
    return articles.values()


def join_dump(root, dump, master):
    from pyspark.sql import SparkSession, Window, functions as f

    spark = SparkSession.builder.master(master).appName("VINF Food.com").getOrCreate()
    temporary = None
    candidates_path = None
    keys_path = None
    try:
        data = root / "data"
        source = data / "processed/recipes.jsonl"
        output = data / "part2"
        output.mkdir(parents=True, exist_ok=True)
        recipes = spark.read.option("mode", "FAILFAST").json(source.as_uri())
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            keys_path = Path(stream.name)
            for key in read_recipe_candidates(source, ALIASES):
                stream.write(json.dumps(key, ensure_ascii=False) + "\n")
        keys = spark.read.schema("recipe_id string, key string, priority int, match_type string").json(keys_path.as_uri())
        pages = (spark.read.format("xml").option("rowTag", "page").option("excludeAttribute", "true")
                 .option("mode", "FAILFAST").schema("id long, ns int, title string, revision struct<text:string>")
                 .load(dump).where("ns = 0").select("id", f.col("title").alias("wiki_title"), "revision.text"))
        pages = pages.withColumn("key", f.lower(f.trim(f.regexp_replace("wiki_title", r"[_\s]+", " "))))
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            candidates_path = Path(stream.name)
            for article in extract_articles(pages, keys, f):
                stream.write(json.dumps(article, ensure_ascii=False) + "\n")
        articles = spark.read.schema(WIKI_SCHEMA).option("mode", "FAILFAST").json(candidates_path.as_uri())
        # Priamy kandidát s infoboxom má prednosť pred voľnejším pravidlom.
        matches = keys.join(f.broadcast(articles), "key").where("has_infobox OR is_food")
        matches = matches.withColumn("priority", f.when(f.col("match_type") == "related", f.lit(100))
                                     .when(f.col("has_infobox") & ~f.col("redirected"), f.col("priority"))
                                     .otherwise(20 + f.col("priority")))
        matches = matches.withColumn("rank", f.row_number().over(
            Window.partitionBy("recipe_id").orderBy("priority", "id", "key")))
        match_type = f.when((f.col("match_type") != "related") & f.col("redirected"), f.lit("redirect"))
        matches = matches.where("rank = 1").select(
            "recipe_id", f.col("id").alias("wiki_id"), "wiki_title", "wiki",
            f.coalesce(match_type, f.col("match_type")).alias("wiki_match_type"))
        joined = recipes.join(matches, "recipe_id", "left")
        ids, articles = set(), set()
        matched = 0
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            temporary = stream.name
            for line in joined.toJSON().toLocalIterator():
                row = json.loads(line)
                if row["recipe_id"] in ids:
                    raise ValueError("Duplicate recipe ID: " + row["recipe_id"])
                ids.add(row["recipe_id"])
                if "wiki_id" in row:
                    articles.add(row["wiki_id"])
                    matched += 1
                stream.write(line + "\n")
        os.replace(temporary, output / "recipes.jsonl")
        return dict(recipes=len(ids), matched=matched, unmatched=len(ids)-matched, unique_wiki_pages=len(articles))
    finally:
        try:
            spark.stop()
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
            if candidates_path is not None:
                candidates_path.unlink(missing_ok=True)
            if keys_path is not None:
                keys_path.unlink(missing_ok=True)
