"""Porovnanie top 3 pri už otvorených indexoch."""

from itertools import zip_longest
from statistics import median
from textwrap import wrap
from time import perf_counter_ns

from food_crawler.indexing import search
from lucene_recipes import open_search

QUERIES = ("banana bread", "fluffy pancakes", "macaroni cheese", "apple pie", "butter chicken")


def wiki_origin(recipe):
    if recipe.get("wiki_match_type") == "related":
        return ""
    wiki = recipe.get("wiki") or {}
    return ", ".join(dict.fromkeys(value for value in (wiki.get("country"), wiki.get("region")) if value))


def describe_hit(hit):
    if hit is None:
        return ["—"]
    lines = [f"[{hit['recipe_id']}] {hit['title']}"]
    minutes = hit.get("total_time_minutes")
    servings = hit.get("servings")
    facts = []
    if minutes is not None:
        facts.append(f"{minutes:g} min")
    if servings is not None:
        facts.append(f"porcie {servings:g}")
    if facts:
        lines.append(" · ".join(facts))
    if hit.get("wiki_match_type") == "related":
        lines.append(f"Súvisiaci článok: {hit['wiki_title']}")
    elif origin := wiki_origin(hit):
        lines.append(f"Pôvod podľa Wiki: {origin}")
    if cuisines := hit.get("cuisine_hints"):
        lines.append("Kuchyňa: " + ", ".join(cuisines))
    elif hit.get("wiki_title"):
        lines.append(f"Wiki: {hit['wiki_title']}")
    return lines


def side_by_side(old_hits, new_hits, method):
    width = 42
    lines = [f"{'#':>3} | {f'TF-IDF ({method})':<{width}} | PyLucene (BM25)",
             f"{'-' * 3}-+-{'-' * width}-+-{'-' * width}"]
    for rank, (old, new) in enumerate(zip_longest(old_hits, new_hits), 1):
        old_lines = [part for line in describe_hit(old) for part in wrap(line, width)]
        new_lines = [part for line in describe_hit(new) for part in wrap(line, width)]
        rank_label = str(rank)
        for left, right in zip_longest(old_lines, new_lines, fillvalue=""):
            lines.append(f"{rank_label:>3} | {left:<{width}} | {right}")
            rank_label = ""
        lines.append("")
    if not old_hits and not new_hits:
        lines.append("Žiadny výsledok v oboch indexoch.")
    return "\n".join(lines)


def recipe_details(recipe):
    lines = ["", f"[{recipe['recipe_id']}] {recipe['title']}", recipe["url"]]
    if recipe.get("total_time_minutes") is not None:
        lines.append(f"Celkový čas: {recipe['total_time_minutes']:g} min")
    if recipe.get("servings") is not None:
        lines.append(f"Porcie: {recipe['servings']:g}")
    if recipe.get("yield_text"):
        lines.append(f"Výťažnosť: {recipe['yield_text']}")
    if recipe.get("category"):
        lines.append(f"Kategória Food.com: {recipe['category']}")

    lines.extend(["", "Wikipédia"])
    wiki = recipe.get("wiki") or {}
    if recipe.get("wiki_title"):
        related = recipe.get("wiki_match_type") == "related"
        lines.append(f"Súvisiaci článok: {recipe['wiki_title']}" if related else recipe["wiki_title"])
        if recipe.get("wiki_id") is not None:
            lines.append(f"https://en.wikipedia.org/?curid={recipe['wiki_id']}")
        if related:
            lines.append("Zhoda podľa podobného jedla. Pôvod konkrétneho receptu z článku neurčujeme.")
        else:
            if origin := wiki_origin(recipe):
                lines.append(f"Pôvod: {origin}")
            for field, label in (("cuisine", "Kuchyňa"), ("type", "Typ jedla"), ("ingredients", "Typické suroviny")):
                if wiki.get(field):
                    lines.append(f"{label}: {wiki[field]}")
    else:
        lines.append("K receptu nie je priradený článok o jedle.")
    if cuisines := recipe.get("cuisine_hints"):
        lines.extend(["", "Kuchyne použité pri vyhľadávaní"])
        lines.extend(f"- {name}: {', '.join(sources)}" for name, sources in cuisines.items())
    elif not recipe.get("wiki_title"):
        lines.append("Kuchyňu sa z dostupných údajov nepodarilo určiť.")

    lines.extend(["", "Suroviny"])
    lines.extend(f"- {ingredient}" for ingredient in recipe.get("ingredients", []))
    lines.extend(["", "Postup"])
    lines.extend(f"{step}. {text}" for step, text in enumerate(recipe.get("instructions", []), 1))
    return "\n".join(lines)


def compare_queries(root, index, query, method, limit):
    if limit < 1:
        raise ValueError("Limit must be positive")
    with open_search(root) as lucene:
        def run_query(text):
            if text.startswith(":id "):
                identifier = text[4:].strip()
                if not identifier.isascii() or not identifier.isdecimal():
                    raise ValueError("Zadaj číselné ID receptu, napríklad :id 2886.")
                hits = lucene(f"recipe_id:{identifier}", 1)
                print(recipe_details(hits[0]) if hits else f"Recept {identifier} sa nenašiel.")
                return

            old_hits = search(index, text, method, limit)
            new_hits = lucene(text, limit)
            details = {row["recipe_id"]: row for row in new_hits}
            old_details = []
            for row in old_hits:
                identifier = row["recipe_id"]
                hit = details.get(identifier)
                if hit is None:
                    matches = lucene(f"recipe_id:{identifier}", 1)
                    hit = matches[0] if matches else row
                old_details.append(hit)
            print(side_by_side(old_details, new_hits, method))

        if query is not None:
            run_query(query)
            return

        print("Zadaj dopyt alebo :id ID_RECEPTU pre suroviny a postup. Prázdny riadok ukončí porovnávanie.")
        while True:
            try:
                query = input("\nDopyt > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not query:
                return
            try:
                run_query(query)
            except ValueError as error:
                print(error)


def benchmark(lookup, query):
    lookup(query)
    times = []
    for _ in range(7):
        start = perf_counter_ns()
        hits = lookup(query)
        times.append((perf_counter_ns() - start) / 1_000_000)
    titles = " / ".join(hit["title"].replace("|", "\\|") for hit in hits)
    return f"{titles} | {median(times):.3f}"


def comparison_table(root, index):
    lines = ["| Dopyt | Index | Top 3 v poradí | Medián (ms) |", "|---|---|---|---:|"]
    with open_search(root) as lucene:
        for query in QUERIES:
            for method in ("classic", "smooth"):
                result = benchmark(lambda q: search(index, q, method, 3), query)
                lines.append(f"| {query} | {method} | {result} |")
            lines.append(f"| {query} | PyLucene | {benchmark(lucene, query)} |")
    return "\n".join(lines)
