"""Spracovanie HTML súborov a štatistiky receptov."""

import hashlib
import json
import os
from importlib.metadata import version
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from food_crawler.extraction import ExtractionError, extract_recipe
from food_crawler.indexing import document_text, tokenize


def read_jsonl(path):
    """JSONL má jeden samostatný JSON objekt na každom neprázdnom riadku."""
    path = Path(path)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{number}") from exc


def process_dataset(root, count_tokens=False):
    """Postupne extrahuje recepty a uloží štatistiky."""
    from food_crawler.diversity import dish_family

    root = Path(root)
    output_dir = root / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for row in read_jsonl(root / "data/crawl_metadata.jsonl"):
        if "recipe_id" in row:
            metadata[str(row["recipe_id"])] = row
    token_encoder = None
    if count_tokens:
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "Install requirements-bonus.txt to count tiktoken tokens"
            ) from exc
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(root / "data/tokenizer_cache"))
        token_encoder = tiktoken.get_encoding("cl100k_base")
    stats = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw_documents": 0,
        "raw_bytes": 0,
        "relevant_documents": 0,
        "relevant_raw_bytes": 0,
        "rejected_documents": 0,
        "word_tokens": 0,
        "tiktoken_tokens": 0 if count_tokens else None,
        "tokenizer": "cl100k_base" if count_tokens else None,
        "tiktoken_version": version("tiktoken") if count_tokens else None,
        "token_input": "extracted title + ingredients + instructions, newline separated",
        "categories": Counter(),
        "http_statuses": Counter(),
        "duplicate_content_documents": 0,
        "warning_documents": 0,
    }
    seen_content = set()
    # Recepty zapisujeme priebežne. V pamäti nemusíme držať celý HTML korpus.
    recipe_path = output_dir / "recipes.jsonl"
    rejected_path = output_dir / "rejected.jsonl"
    temporary = recipe_path.with_suffix(".jsonl.tmp")
    rejected_temporary = rejected_path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as recipes, rejected_temporary.open(
        "w", encoding="utf-8"
    ) as rejected:
        for path in sorted((root / "data/raw").glob("*.html")):
            raw = path.read_bytes()
            stats["raw_documents"] += 1
            stats["raw_bytes"] += len(raw)
            row = metadata.get(path.stem, {})
            status = row.get("http_status")
            stats["http_statuses"][
                str(status) if status is not None else "unknown"
            ] += 1
            try:
                if status is not None and status != 200:
                    raise ExtractionError(f"HTTP status {status}")
                recipe = extract_recipe(
                    raw.decode("utf-8", errors="replace"), path.stem, row.get("url", "")
                )
            except ExtractionError as exc:
                stats["rejected_documents"] += 1
                rejected.write(
                    json.dumps(
                        {
                            "recipe_id": path.stem,
                            "html_file": path.relative_to(root).as_posix(),
                            "reason": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                continue
            recipe.update(
                {
                    "html_file": path.relative_to(root).as_posix(),
                    "html_bytes": len(raw),
                    "html_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            text = document_text(recipe)
            # Rovnaký normalizovaný text dá rovnaký hash: presná deduplikácia.
            content_hash = hashlib.sha256(" ".join(tokenize(text)).encode()).hexdigest()
            duplicate = content_hash in seen_content
            seen_content.add(content_hash)
            recipe["content_sha256"] = content_hash
            recipe["duplicate_content"] = duplicate
            recipe["dish_family"], recipe["family_rule_known"] = dish_family(
                recipe["title"]
            )
            stats["duplicate_content_documents"] += duplicate
            stats["relevant_documents"] += 1
            stats["relevant_raw_bytes"] += len(raw)
            stats["word_tokens"] += len(tokenize(text))
            stats["warning_documents"] += bool(recipe["warnings"])
            category = recipe["category"] or "unknown"
            stats["categories"][str(category)] += 1
            if token_encoder is not None:
                stats["tiktoken_tokens"] += len(
                    token_encoder.encode(text, disallowed_special=())
                )
            recipes.write(json.dumps(recipe, ensure_ascii=False) + "\n")
    temporary.replace(recipe_path)
    # Výsledný JSONL vymeníme až po spracovaní celej lokálnej vzorky.
    rejected_temporary.replace(rejected_path)
    stats["extracted_bytes"] = recipe_path.stat().st_size
    stats["recipes_sha256"] = hashlib.sha256(recipe_path.read_bytes()).hexdigest()
    stats["error_html_files"] = sum(1 for _ in (root / "data/errors").glob("*.html"))
    quarantined = list((root / "data/quarantine").glob("*.html"))
    stats["quarantined_documents"] = len(quarantined)
    stats["quarantined_html_bytes"] = sum(path.stat().st_size for path in quarantined)
    stats["crawl_failure_records"] = sum(
        1 for _ in read_jsonl(root / "data/crawl_failures.jsonl")
    )
    (output_dir / "statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats
