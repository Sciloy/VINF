"""Jeden dokument PyLucene pre každý recept po spojení."""

import json
import re
from contextlib import contextmanager

from food_crawler.dataset import read_jsonl
from cuisine_hints import cuisine_query, recipe_cuisines

TEXT = ("title", "ingredients", "instructions", "wiki_title", "country", "region", "cuisine", "type", "wiki_ingredients")


def ranked_query(query):
    original = query.strip()
    cuisine = cuisine_query(original)
    if cuisine != original or not re.fullmatch(r"[\w\s]+", original):
        return cuisine

    terms = original.split()
    if any(term in {"AND", "OR", "NOT"} for term in terms):
        return original

    required = " AND ".join(terms)
    title_match = f"title:({required})^4"
    if len(terms) == 1:
        return f"+({required}) {title_match}"

    phrase = " ".join(terms)
    return f'+({required}) {title_match} title:"{phrase}"^8'


def start_vm():
    import lucene
    if lucene.getVMEnv() is None:
        lucene.initVM(vmargs=["-Djava.awt.headless=true"])


def build(root):
    start_vm()
    from java.nio.file import Paths
    from org.apache.lucene.analysis.standard import StandardAnalyzer
    from org.apache.lucene.document import Document, DoublePoint, Field, StoredField, StringField, TextField
    from org.apache.lucene.index import IndexWriter, IndexWriterConfig
    from org.apache.lucene.store import FSDirectory

    folder = root / "data/part2"
    source = folder / "recipes.jsonl"
    if not source.is_file():
        raise ValueError("Run spark-join first")
    directory = FSDirectory.open(Paths.get(str(folder / "lucene")))
    analyzer = StandardAnalyzer()
    try:
        config = IndexWriterConfig(analyzer)
        config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
        writer = IndexWriter(directory, config)
        try:
            ids = set()
            cuisine_counts = {}
            for row in read_jsonl(source):
                identifier = row["recipe_id"]
                if identifier in ids:
                    raise ValueError("Duplicate recipe ID: " + identifier)
                ids.add(identifier)
                doc = Document()
                doc.add(StringField("recipe_id", identifier, Field.Store.YES))
                cuisines = recipe_cuisines(row)
                doc.add(StoredField("recipe", json.dumps({**row, "cuisine_hints": cuisines}, ensure_ascii=False)))
                wiki_status = "with_wiki_article" if row.get("wiki_id") is not None else "without_wiki_article"
                for cuisine in cuisines:
                    doc.add(StringField("cuisine_hint", cuisine, Field.Store.NO))
                    counts = cuisine_counts.setdefault(cuisine, {"with_wiki_article": 0, "without_wiki_article": 0})
                    counts[wiki_status] += 1
                wiki = (row.get("wiki") or {}) if row.get("wiki_match_type") != "related" else {}
                values = {**wiki, **row, "wiki_ingredients": wiki.get("ingredients")}
                for field in TEXT:
                    value = values.get(field)
                    if isinstance(value, list):
                        value = "\n".join(value)
                    if value:
                        doc.add(TextField(field, value, Field.Store.NO))
                for field in ("total_time_minutes", "servings"):
                    if row.get(field) is not None:
                        doc.add(DoublePoint(field, [float(row[field])]))
                writer.addDocument(doc)
            if not ids:
                raise ValueError("Empty recipe corpus")
            writer.commit()
        except BaseException:
            writer.rollback()
            raise
        writer.close()
        return {"indexed_recipes": len(ids), "cuisine_counts": dict(sorted(cuisine_counts.items()))}
    finally:
        analyzer.close()
        directory.close()


@contextmanager
def open_search(root):
    start_vm()
    from lucene import JavaError
    from java.nio.file import Paths
    from org.apache.lucene.analysis.standard import StandardAnalyzer
    from org.apache.lucene.document import DoublePoint
    from org.apache.lucene.index import DirectoryReader
    from org.apache.lucene.queryparser.classic import MultiFieldQueryParser, QueryParserBase
    from org.apache.lucene.search import BooleanClause, BooleanQuery, IndexSearcher, MatchAllDocsQuery
    from org.apache.lucene.store import FSDirectory

    directory = FSDirectory.open(Paths.get(str(root / "data/part2/lucene")))
    analyzer = StandardAnalyzer()
    reader = None
    try:
        if not DirectoryReader.indexExists(directory):
            raise ValueError("Run lucene-index first")
        reader = DirectoryReader.open(directory)
        searcher = IndexSearcher(reader)
        parser = MultiFieldQueryParser([*TEXT, "cuisine_hint"], analyzer)

        def search(query, limit=5, max_minutes=None, min_servings=None):
            if limit < 1:
                raise ValueError("Limit must be positive")
            builder = BooleanQuery.Builder()
            try:
                parsed = QueryParserBase.parse(parser, ranked_query(query)) if query.strip() else MatchAllDocsQuery()
            except JavaError as exc:
                raise ValueError(f"Neplatný dopyt pre PyLucene: {query}") from exc
            builder.add(parsed, BooleanClause.Occur.MUST)
            for field, lower, upper in (("total_time_minutes", 0., max_minutes), ("servings", min_servings, float("inf"))):
                if lower is not None and upper is not None:
                    builder.add(DoublePoint.newRangeQuery(field, float(lower), float(upper)), BooleanClause.Occur.FILTER)
            docs = searcher.storedFields()
            results = []
            for hit in searcher.search(builder.build(), limit).scoreDocs:
                row = json.loads(docs.document(hit.doc).get("recipe"))
                results.append({**row, "score": hit.score})
            return results
        yield search
    finally:
        if reader is not None:
            reader.close()
        analyzer.close()
        directory.close()
