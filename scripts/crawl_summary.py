"""Print a local dataset summary; this script never accesses the website."""

import json
from collections import Counter
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    raw_dir = root / "data" / "raw"
    metadata_file = root / "data" / "crawl_metadata.jsonl"
    files = list(raw_dir.glob("*.html"))
    total_bytes = sum(path.stat().st_size for path in files)
    records = []
    if metadata_file.exists():
        records = [
            json.loads(line)
            for line in metadata_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    ids = [record["recipe_id"] for record in records]
    statuses = Counter(record["http_status"] for record in records)
    print(f"Raw HTML files: {len(files)}")
    print(f"Raw HTML size: {total_bytes:,} bytes ({total_bytes / 1_000_000:.2f} MB)")
    print(f"Metadata records: {len(records)}")
    print(f"Distinct recipe IDs: {len(set(ids))}")
    print(f"Repeated recipe IDs in metadata: {len(ids) - len(set(ids))}")
    print(f"HTTP statuses: {dict(sorted(statuses.items()))}")
    if files:
        average = total_bytes / len(files)
        estimated_pages = int(500_000_000 / average) + 1
        print(f"Average raw HTML size: {average / 1_000:.1f} KB")
        print(f"Estimated total pages for 500 MB at this average: {estimated_pages:,}")
    print("Dish-family diversity is not measured yet; review the recipe slugs below.")
    for record in records[-50:]:
        print(f"  {record['recipe_id']}: {record['slug']}")


if __name__ == "__main__":
    main()
