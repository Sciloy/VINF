"""Vlastný obrátený index a vyhľadávanie pomocou TF-IDF."""

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
METHODS = ("classic", "smooth")
QUERY_MINUTES = re.compile(r"\b(\d+)\s*(?:minutes?|mins?)\b", re.IGNORECASE)


def tokenize(text):
    """Rovnaká normalizácia a rozdelenie na slová platí aj pre dopyt."""
    normalized_text = unicodedata.normalize("NFKC", text)
    lowercase_text = normalized_text.casefold()
    return TOKEN.findall(lowercase_text)


def document_text(recipe):
    """Do vyhľadávania vstupuje názov, suroviny a postup."""
    parts = [recipe["title"]]
    parts.extend(recipe["ingredients"])
    parts.extend(recipe["instructions"])
    return "\n".join(parts)


def idf(document_count, document_frequency, method):
    """Vypočíta IDF z počtu všetkých dokumentov a DF."""
    if method not in METHODS:
        raise ValueError(f"Unknown IDF method: {method}")
    if not 0 < document_frequency <= document_count:
        raise ValueError("IDF requires 0 < df <= N")
    if method == "classic":
        return math.log(document_count / document_frequency)
    # Vyhladenie pridáva 1 k N, k DF a nakoniec k výsledku.
    return math.log((document_count + 1) / (document_frequency + 1)) + 1


def calculate_document_norms(documents, postings):
    """Pre každú IDF metódu vypočíta dĺžky TF-IDF vektorov dokumentov."""
    document_count = len(documents)
    squared_norms = {}
    for method in METHODS:
        squared_norms[method] = {}

    for term_documents in postings.values():
        document_frequency = len(term_documents)
        for method in METHODS:
            idf_value = idf(document_count, document_frequency, method)
            for recipe_id, term_frequency in term_documents.items():
                tf_idf = term_frequency * idf_value
                previous_sum = squared_norms[method].get(recipe_id, 0.0)
                squared_norms[method][recipe_id] = previous_sum + tf_idf**2

    # Dĺžka vektora = odmocnina zo súčtu štvorcov jeho súradníc.
    norms = {}
    for method in METHODS:
        norms[method] = {}
        for recipe_id in documents:
            squared_norm = squared_norms[method].get(recipe_id, 0.0)
            norms[method][recipe_id] = math.sqrt(squared_norm)
    return norms


def build_index(recipes):
    """Vytvorí metadáta dokumentov, obrátený index a dĺžky vektorov."""
    documents = {}
    postings = {}
    for recipe in recipes:
        recipe_id = str(recipe["recipe_id"])
        if recipe_id in documents:
            raise ValueError(f"Duplicate recipe ID: {recipe_id}")
        words = tokenize(document_text(recipe))
        term_counts = Counter(words)
        if not term_counts:
            raise ValueError(f"Empty document: {recipe_id}")
        documents[recipe_id] = {
            "title": recipe["title"],
            "url": recipe["url"],
            "token_count": sum(term_counts.values()),
            "ingredients": recipe["ingredients"],
            "total_time_minutes": recipe.get("total_time_minutes"),
            "servings": recipe.get("servings"),
            "yield_text": recipe.get("yield_text"),
        }
        # Príklad: postings['apple'] = {'recept_1': 3, 'recept_2': 1}.
        # znamená tri výskyty slova v prvom recepte, teda TF = 3.
        for term, term_frequency in term_counts.items():
            if term not in postings:
                postings[term] = {}
            postings[term][recipe_id] = term_frequency

    norms = calculate_document_norms(documents, postings)
    return {
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tokenizer": "NFKC + casefold + Unicode words; no stemming/stopwords",
        "tf": "raw count",
        "scoring": "cosine TF-IDF",
        "document_count": len(documents),
        "documents": documents,
        "postings": postings,
        "norms": norms,
    }


def result_sort_key(result):
    """Vyššie skóre ide prvé; pri zhode rozhoduje ID receptu ako text."""
    return (-result["score"], result["recipe_id"])


def matches_filters(document, max_minutes, min_servings, ingredients):
    """Neznámy čas alebo počet porcií nevyhovuje príslušnému filtru."""
    if max_minutes is not None:
        minutes = document.get("total_time_minutes")
        if minutes is None or minutes > max_minutes:
            return False
    if min_servings is not None:
        servings = document.get("servings")
        if servings is None or servings < min_servings:
            return False
    for ingredient in ingredients:
        phrase = " ".join(tokenize(ingredient))
        if not phrase:
            raise ValueError("Ingredient must contain a word")
        found = False
        for line in document.get("ingredients", []):
            words = " " + " ".join(tokenize(line)) + " "
            if " " + phrase + " " in words:
                found = True
                break
        if not found:
            return False
    return True


def search(
    index, query, method="classic", limit=5, *, max_minutes=None,
    min_servings=None, ingredients=(),
):
    """Zoradí dokumenty podľa kosínusovej podobnosti s dopytom."""
    if method not in METHODS:
        raise ValueError(f"Unknown IDF method: {method}")
    if limit < 1:
        raise ValueError("Result limit must be positive")
    # Jednoduchý zápis „chicken 15 minutes“ pridá časový filter.
    for match in QUERY_MINUTES.finditer(query):
        minutes = int(match[1])
        max_minutes = minutes if max_minutes is None else min(max_minutes, minutes)
    query = QUERY_MINUTES.sub("", query).strip()
    for value in (max_minutes, min_servings):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("Filter values must be positive numbers")
    for ingredient in ingredients:
        if not tokenize(ingredient):
            raise ValueError("Ingredient must contain a word")
    has_filters = (
        max_minutes is not None or min_servings is not None or bool(ingredients)
    )
    if has_filters and index.get("version", 1) < 2:
        raise ValueError("Rebuild the index to use filters: python scripts/vinf.py all")
    # Slová mimo slovníka nemajú dokumenty, preto ich vynecháme.
    known_words = []
    for term in tokenize(query):
        if term in index["postings"]:
            known_words.append(term)
    query_tf = Counter(known_words)

    dot_products = {}
    query_norm_squared = 0
    for term, query_frequency in query_tf.items():
        term_documents = index["postings"][term]
        document_frequency = len(term_documents)
        idf_value = idf(index["document_count"], document_frequency, method)
        query_weight = query_frequency * idf_value
        query_norm_squared += query_weight**2
        # Skalárny súčin: sčítame súčiny váh rovnakého slova v oboch vektoroch.
        for recipe_id, document_tf in term_documents.items():
            previous_score = dot_products.get(recipe_id, 0.0)
            contribution = query_weight * document_tf * idf_value
            dot_products[recipe_id] = previous_score + contribution

    query_norm = math.sqrt(query_norm_squared)
    filter_only = not tokenize(query) and has_filters
    if not query_norm and not filter_only:
        return []
    if filter_only:
        dot_products = dict.fromkeys(index["documents"], 0.0)
    results = []
    for recipe_id, dot_product in dot_products.items():
        document = index["documents"][recipe_id]
        if not matches_filters(document, max_minutes, min_servings, ingredients):
            continue
        document_norm = index["norms"][method][recipe_id]
        if filter_only or (document_norm and dot_product > 0):
            # cosine = skalárny súčin / (dĺžka dokumentu * dĺžka dopytu).
            score = 0.0 if filter_only else dot_product / (document_norm * query_norm)
            result = {"recipe_id": recipe_id}
            result.update(index["documents"][recipe_id])
            result["score"] = score
            results.append(result)
    results.sort(key=result_sort_key)
    return results[:limit]


def save_index(index, path, source_path=None):
    """Uloží index a hash vstupu, podľa ktorého kontrolujeme zhodu s dátami."""
    if source_path is not None:
        source_bytes = Path(source_path).read_bytes()
        index["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(path)
