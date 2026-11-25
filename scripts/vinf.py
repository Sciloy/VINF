"""Extrakcia, indexovanie a vyhľadávanie receptov."""

import argparse
import hashlib
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from food_crawler.dataset import process_dataset, read_jsonl
from food_crawler.indexing import METHODS, build_index, save_index, search

QUERIES = ["banana bread", "fluffy pancakes", "macaroni cheese"]


def json_output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_index(root):
    path = root / "data/index/index.json"
    if not path.exists():
        raise ValueError("Index is missing. Run: python scripts/vinf.py index")
    return json.loads(path.read_text(encoding="utf-8"))


def index_dataset(root):
    """Celý index sa prestavia z JSONL; pri dopyte sa už nevytvára."""
    source = root / "data/processed/recipes.jsonl"
    if not source.exists():
        raise ValueError(
            "Extracted data is missing. Run: python scripts/vinf.py extract"
        )
    index = build_index(read_jsonl(source))
    if not index["document_count"]:
        raise ValueError("Cannot build a search index without relevant recipes")
    save_index(index, root / "data/index/index.json", source)
    return {
        "indexed_documents": index["document_count"],
        "vocabulary_size": len(index["postings"]),
        "source_sha256": index["source_sha256"],
    }


def compare(root, queries):
    """Uloží výsledky rovnakých dopytov pre obe metódy IDF."""
    index = load_index(root)
    comparisons = []
    for query in queries:
        results = {}
        for method in METHODS:
            results[method] = search(index, query, method)
        comparisons.append({"query": query, "results": results})
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "document_count": index["document_count"],
        "source_sha256": index["source_sha256"],
        "queries": comparisons,
    }
    destination = root / "data/reports/comparison.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def query_recipes(root, query, methods=METHODS, limit=5, **filters):
    """Vyhľadá obe poradia a doplní celé recepty zo zhodného JSONL."""
    index = load_index(root)
    results = {
        method: search(index, query, method, limit, **filters)
        for method in methods
    }
    selected = {item["recipe_id"] for items in results.values() for item in items}
    recipes = {}
    if selected:
        source = root / "data/processed/recipes.jsonl"
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest() != index.get("source_sha256"):
            raise ValueError(
                "Index and recipe data differ. Run: python scripts/vinf.py all --tokens"
            )
        for line in body.decode("utf-8").splitlines():
            if line.strip():
                recipe = json.loads(line)
                recipe_id = str(recipe["recipe_id"])
                if recipe_id in selected:
                    recipes[recipe_id] = recipe
        if selected - recipes.keys():
            raise ValueError("A search result is missing from recipe data")
    return {
        "query": query, "document_count": index["document_count"],
        "limit": limit, "results": results, "recipes": recipes,
    }


def format_query(report):
    """Vypíše poradia vedľa seba a každý celý recept iba raz."""
    results = report["results"]
    methods = list(results)
    ranks = {
        method: {item["recipe_id"]: (rank, item["score"])
                 for rank, item in enumerate(items, 1)}
        for method, items in results.items()
    }
    ordered = list(dict.fromkeys(
        item["recipe_id"] for items in results.values() for item in items
    ))
    lines = [f"Dopyt: {report['query'] or '(iba filtre)'}",
             f"Dokumentov v indexe: {report['document_count']}", ""]
    if not ordered:
        return "\n".join(lines + ["Žiadny recept nevyhovuje dopytu a filtrom."])

    lines.append(f"TOP {report['limit']} — poradie (skóre)")
    lines.append(f"{'Recept':54} | " + " | ".join(f"{m.upper():17}" for m in methods))
    lines.append("-" * (54 + 20 * len(methods)))
    for recipe_id in ordered:
        title = textwrap.shorten(report["recipes"][recipe_id]["title"], 54, placeholder="…")
        cells = []
        for method in methods:
            entry = ranks[method].get(recipe_id)
            cell = f"{entry[0]}. ({entry[1]:.6f})" if entry else "—"
            cells.append(f"{cell:17}")
        lines.append(f"{title:54} | " + " | ".join(cells))
    lines.append(f"— = recept nie je medzi top {report['limit']} výsledkami danej metódy.")

    def number(value):
        return "neuvedené" if value is None else f"{value:g}"

    def wrap(text, prefix="  "):
        return textwrap.fill(" ".join(str(text).split()), width=100,
                             initial_indent=prefix, subsequent_indent=" " * len(prefix))

    for recipe_id in ordered:
        recipe = report["recipes"][recipe_id]
        lines += ["", f"[{recipe_id}] {recipe['title']}", recipe["url"]]
        positions = []
        for method in methods:
            entry = ranks[method].get(recipe_id)
            if entry:
                positions.append(f"{method.upper()}: {entry[0]}. miesto, skóre {entry[1]:.6f}")
        lines.append(" | ".join(positions))
        minutes = recipe.get("total_time_minutes")
        time_label = "neuvedené" if minutes is None else f"{number(minutes)} min"
        lines.append(
            f"Čas: {time_label} | "
            f"Porcie: {number(recipe.get('servings'))} | "
            f"Výťažnosť: {recipe.get('yield_text') or 'neuvedené'}"
        )
        family = recipe.get("dish_family") or ""
        family_label = (
            "neurčená" if not family or family.startswith("unclassified:")
            else family.replace("_", " ")
        )
        lines.append(
            f"Kategória: {recipe.get('category') or 'neuvedené'} | "
            f"Hodnotenie: {recipe.get('rating') or 'neuvedené'} | "
            f"Rodina: {family_label}"
        )
        lines.append(f"Suroviny ({len(recipe['ingredients'])}):")
        lines.append(wrap("; ".join(recipe["ingredients"])))
        lines.append(f"Postup ({len(recipe['instructions'])}):")
        for step, instruction in enumerate(recipe["instructions"], 1):
            lines.append(wrap(instruction, f"  {step}. "))
        if recipe.get("warnings"):
            lines.append(wrap("; ".join(recipe["warnings"]), "Poznámky: "))
    return "\n".join(lines)


def add_filters(command):
    command.add_argument("--max-minutes", type=float)
    command.add_argument("--min-servings", type=float)
    command.add_argument("--ingredient", action="append", default=[])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("extract", "all"):
        command = commands.add_parser(name)
        command.add_argument(
            "--tokens",
            action="store_true",
            help="Spočíta tokeny pomocou tiktoken",
        )
    commands.add_parser("index")
    query = commands.add_parser("search")
    query.add_argument("query")
    query.add_argument("--method", choices=METHODS, default="classic")
    query.add_argument("--limit", type=int, default=5)
    add_filters(query)
    preview = commands.add_parser("query", help="Prehľadné top 5 pre classic aj smooth")
    preview.add_argument("query", nargs="?", help="Bez argumentu sa opýta na dopyt")
    preview.add_argument("--method", choices=(*METHODS, "both"), default="both")
    preview.add_argument("--limit", type=int, default=5)
    add_filters(preview)
    comparison = commands.add_parser("compare")
    comparison.add_argument("queries", nargs="*", default=QUERIES)
    join = commands.add_parser("spark-join")
    join.add_argument("dump", help="English pages-articles XML or XML.bz2 path")
    join.add_argument("--master", default="local[2]")
    join.add_argument("--indexed", action="store_true",
                      help="Find recipe titles and Wikipedia food lists through the Wikimedia title index")
    join.add_argument("--title-index", type=Path, help="Local multistream title index for --indexed")
    commands.add_parser("lucene-index")
    lucene = commands.add_parser("lucene-search")
    lucene.add_argument("query")
    lucene.add_argument("--limit", type=int, default=5)
    lucene.add_argument("--max-minutes", type=float)
    lucene.add_argument("--min-servings", type=float)
    comparison_view = commands.add_parser("compare-search", help="TF-IDF a PyLucene vedľa seba")
    comparison_view.add_argument("query", nargs="?", help="Bez dopytu spustí interaktívny režim")
    comparison_view.add_argument("--method", choices=METHODS, default="smooth")
    comparison_view.add_argument("--limit", type=int, default=5)
    gui = commands.add_parser("gui", help="Otvoriť vyhľadávanie receptov v prehliadači")
    gui.add_argument("--bind", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    commands.add_parser("evaluate")
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        if args.command == "spark-join":
            from spark_recipes import join_dump
            if args.title_index and not args.indexed:
                parser.error("--title-index requires --indexed")
            if args.indexed:
                from wiki_dump_index import candidate_xml

                source = Path(args.dump).resolve(strict=True)
                dump = candidate_xml(source, root / "data/processed/recipes.jsonl",
                                     index_path=args.title_index).as_uri()
            else:
                dump = args.dump if "://" in args.dump else Path(args.dump).resolve().as_uri()
            json_output(join_dump(root, dump, args.master))
        if args.command == "lucene-index":
            from lucene_recipes import build
            json_output(build(root))
        if args.command == "lucene-search":
            from lucene_recipes import open_search
            with open_search(root) as lookup:
                json_output(lookup(args.query, args.limit, args.max_minutes, args.min_servings))
        if args.command == "evaluate":
            from evaluate_recipes import comparison_table
            print(comparison_table(root, load_index(root)))
        if args.command == "gui":
            from recipe_gui import serve
            serve(root, args.bind, args.port)
        if args.command == "compare-search":
            from evaluate_recipes import compare_queries
            compare_queries(root, load_index(root), args.query, args.method, args.limit)
        if args.command in ("extract", "all"):
            json_output(process_dataset(root, args.tokens))
        if args.command in ("index", "all"):
            json_output(index_dataset(root))
        if args.command == "search":
            json_output(search(
                load_index(root), args.query, args.method, args.limit,
                max_minutes=args.max_minutes, min_servings=args.min_servings,
                ingredients=args.ingredient,
            ))
        if args.command == "query":
            query_text = args.query
            if query_text is None:
                try:
                    query_text = input("Dopyt: ")
                except (EOFError, KeyboardInterrupt):
                    return
            methods = METHODS if args.method == "both" else (args.method,)
            print(format_query(query_recipes(
                root, query_text, methods, args.limit,
                max_minutes=args.max_minutes, min_servings=args.min_servings,
                ingredients=args.ingredient,
            )))
        if args.command == "compare":
            json_output(compare(root, args.queries))
        if args.command == "all":
            json_output(compare(root, QUERIES))
    except (ValueError, RuntimeError, FileNotFoundError, ImportError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
