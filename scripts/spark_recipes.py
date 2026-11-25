"""Spojenie extrahovaného korpusu s anglickým pages-articles dumpom."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from wiki_fields import food_fields, wiki_recipe_text
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
WIKI_SCHEMA = "id long, key string, wiki_title string, has_infobox boolean, redirected boolean, match_candidate boolean, wiki struct<" + ",".join(
    name + ":string" for name in WIKI_FIELDS
) + ">, wiki_summary string, wiki_preparation array<string>"


def extract_articles(pages, candidates, f):
    articles = {}
    redirects = {}
    seen_keys = set()

    def read_pages(rows):
        for page in rows:
            seen_keys.add(page.key)
            if target := redirect_key(page.text):
                redirects[page.key] = target
                continue
            fields = food_fields(page.text)
            if fields is None and not food_article(page.wiki_title, page.text):
                continue
            summary, preparation = wiki_recipe_text(page.text) if fields is not None else (None, [])
            record = dict(id=page.id, key=page.key, wiki_title=page.wiki_title,
                          has_infobox=fields is not None, redirected=False,
                          wiki=dict(zip(WIKI_FIELDS, fields)) if fields is not None else None,
                          wiki_summary=summary, wiki_preparation=preparation)
            previous = articles.get(page.key)
            if previous is None or (not record["has_infobox"], record["id"]) < (
                not previous["has_infobox"], previous["id"]
            ):
                articles[page.key] = record

    recipe_keys = f.broadcast(candidates.select("key").distinct().withColumn("recipe_candidate", f.lit(True)))
    selected = pages.join(recipe_keys, "key", "left").where(
        f.col("recipe_candidate") | f.col("text").rlike(r"(?i)\{\{\s*infobox[ _]+food\b")
    )
    read_pages(selected.toLocalIterator())
    for _ in range(4):
        targets = sorted(set(redirects.values()) - seen_keys)
        if not targets:
            break
        seen_keys.update(targets)
        read_pages(pages.where(f.col("key").isin(targets)).toLocalIterator())
    canonical = list(articles.values())
    for alias, destination in redirects.items():
        visited = {alias}
        target = destination
        while target in redirects and target not in visited:
            visited.add(target)
            target = redirects[target]
        if target in articles and not articles[target]["redirected"]:
            articles[alias] = {**articles[target], "key": alias, "redirected": True}
    # Capitalization variants can share one normalized key. Keep the actual page
    # available by its ID even if a redirect occupies that key for matching.
    yield from ({**record, "match_candidate": True} for record in articles.values())
    yield from ({**record, "match_candidate": False}
                for record in canonical if articles[record["key"]]["redirected"])


def join_dump(root, dump, master):
    from pyspark.sql import SparkSession, Window, functions as f

    spark = (SparkSession.builder.master(master).appName("VINF Food.com a Wikipedia")
             .config("spark.sql.shuffle.partitions", "8").getOrCreate())
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
        article_keys = articles.where("match_candidate").select("key", "id", "has_infobox", "redirected")
        matches = keys.join(f.broadcast(article_keys), "key").cache()
        ranked = matches.withColumn("priority", f.when(f.col("match_type") == "related", f.lit(100))
                                    .when(f.col("has_infobox") & ~f.col("redirected"), f.col("priority"))
                                    .otherwise(20 + f.col("priority")))
        ranked = ranked.withColumn("rank", f.row_number().over(
            Window.partitionBy("recipe_id").orderBy("priority", "id", "key")))
        match_type = f.when((f.col("match_type") != "related") & f.col("redirected"), f.lit("redirect"))
        best = ranked.where("rank = 1").select(
            "recipe_id", f.col("id").alias("wiki_id"),
            f.coalesce(match_type, f.col("match_type")).alias("wiki_match_type"))
        linked = matches.select(f.col("id").alias("wiki_id")).distinct()
        canonical = articles.where("NOT redirected").select(
            f.col("id").alias("wiki_id"), "wiki_title", "wiki", "wiki_summary", "wiki_preparation")
        inputs = canonical.join(linked.withColumn("represented", f.lit(True)), "wiki_id", "left")

        # The selected ID enriches a Food.com record. A Wikipedia dish can also stand on its own.
        joined = recipes.join(best, "recipe_id", "left").join(inputs, "wiki_id", "full_outer")
        wiki_only = f.col("recipe_id").isNull()
        joined = joined.where(~wiki_only | (f.col("represented").isNull() & (f.size("wiki_preparation") > 0)))
        joined = (joined.withColumn("source", f.when(wiki_only, "wikipedia")
                                   .when(f.col("wiki_id").isNotNull(), "both").otherwise("foodcom"))
                  .withColumn("title", f.when(wiki_only, f.col("wiki_title")).otherwise(f.col("title")))
                  .withColumn("url", f.when(wiki_only, f.concat(f.lit("https://en.wikipedia.org/?curid="),
                                                              f.col("wiki_id"))).otherwise(f.col("url")))
                  .withColumn("instructions", f.when(wiki_only, f.col("wiki_preparation"))
                              .otherwise(f.col("instructions")))
                  .withColumn("wiki_summary", f.when(wiki_only, f.col("wiki_summary")))
                  .withColumn("recipe_id", f.coalesce("recipe_id", f.concat(f.lit("wiki"), f.col("wiki_id"))))
                  .drop("represented", "wiki_preparation"))

        ids, wiki_ids = set(), set()
        counts = dict(foodcom=0, both=0, wikipedia=0)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            temporary = stream.name
            for line in joined.toJSON().toLocalIterator():
                row = json.loads(line)
                if row["recipe_id"] in ids:
                    raise ValueError("Duplicate recipe ID: " + row["recipe_id"])
                ids.add(row["recipe_id"])
                counts[row["source"]] += 1
                if row["source"] == "both":
                    wiki_ids.add(row["wiki_id"])
                stream.write(line + "\n")
        os.replace(temporary, output / "recipes.jsonl")
        return dict(recipes=len(ids), foodcom_recipes=counts["foodcom"] + counts["both"],
                    matched=counts["both"], unmatched=counts["foodcom"], unique_wiki_pages=len(wiki_ids),
                    wikipedia_only=counts["wikipedia"])
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
