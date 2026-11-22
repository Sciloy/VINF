"""REGEX extrakcia názvu, surovín a postupu z HTML Food.com."""

import html
import json
import re

FLAGS = re.IGNORECASE | re.DOTALL
COMMENTS = re.compile(r"<!--.*?-->", FLAGS)
SCRIPTS = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", FLAGS)
TAGS = re.compile(r"<[^>]+>")
CLASS = re.compile(r"\bclass\s*=\s*([\"'])(.*?)\1", FLAGS)
AMOUNT = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
LEADING_MEASURE = re.compile(
    rf"^{AMOUNT}(?:\s*[-–]\s*{AMOUNT})?\s+"
    r"(?:cups?|tablespoons?|teaspoons?|tbsps?|tsps?|lbs?|pounds?|ounces?|oz|"
    r"grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|slices?|cloves?|cans?|packages?|packets?|eggs?)\b",
    re.I,
)
TITLE = re.compile(r"<h1\b[^>]*>(.*?)</h1\s*>", FLAGS)
ITEM = re.compile(r"<li\b[^>]*>(.*?)</li\s*>", FLAGS)
FACT = re.compile(r"<dt\b[^>]*>(.*?)</dt\s*>\s*<dd\b[^>]*>(.*?)</dd\s*>", FLAGS)
LD_SCRIPT = re.compile(
    r"<script\b(?=[^>]*\btype\s*=\s*['\"]application/ld\+json['\"])[^>]*>(.*?)</script\s*>",
    FLAGS,
)
DURATION = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>days?|d|hours?|hrs?|h|minutes?|mins?|m)\b",
    re.I,
)
ISO_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", re.I)
FRACTIONS = {
    "½": "1/2",
    "¼": "1/4",
    "¾": "3/4",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}


class ExtractionError(ValueError):
    """Stránka nemá úplný recept."""


def clean_text(fragment):
    """Odstráni HTML značky, prevedie špeciálne znaky a zachová zlomky."""
    fragment = COMMENTS.sub("", fragment)
    fragment = SCRIPTS.sub("", fragment)
    fragment = re.sub(r"<br\b[^>]*>|</(?:p|div)\s*>", " ", fragment, flags=re.I)
    text_without_tags = TAGS.sub("", fragment)
    text = html.unescape(text_without_tags).replace("⁄", "/")
    for character, value in FRACTIONS.items():
        text = text.replace(character, " " + value)
    return " ".join(text.split())


def class_blocks(document, tag, class_name):
    """Vyberie bloky známej HTML šablóny podľa značky a triedy."""
    pattern = re.compile(rf"<{tag}\b(?P<attrs>[^>]*)>(?P<body>.*?)</{tag}\s*>", FLAGS)
    for match in pattern.finditer(document):
        classes = CLASS.search(match["attrs"])
        if classes and class_name in classes[2].split():
            yield match["body"]


def duration_minutes(value):
    """Prevedie čas receptu na minúty."""
    if not value:
        return None
    iso = ISO_DURATION.fullmatch(value.strip())
    if iso and any(iso.groups()):
        time_parts = []
        for part in iso.groups():
            time_parts.append(int(part or 0))
        days, hours, minutes, seconds = time_parts
        return days * 1440 + hours * 60 + minutes + seconds / 60
    matches = list(DURATION.finditer(value))
    remainder = DURATION.sub("", value).strip(" ,")
    if not matches or remainder:
        return None
    minute_parts = []
    for match in matches:
        amount = float(match["value"])
        unit = match["unit"].lower()
        if unit.startswith("d"):
            multiplier = 1440
        elif unit.startswith("h"):
            multiplier = 60
        else:
            multiplier = 1
        minute_parts.append(amount * multiplier)
    return sum(minute_parts)


def structured_recipes(document):
    """Načíta doplnkové údaje receptu z JSON-LD."""

    def visit(value):
        if isinstance(value, list):
            for entry in value:
                yield from visit(entry)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            if kind == "Recipe" or (isinstance(kind, list) and "Recipe" in kind):
                yield value
            yield from visit(value.get("@graph", []))

    for match in LD_SCRIPT.finditer(document):
        try:
            yield from visit(json.loads(match[1]))
        except (json.JSONDecodeError, TypeError):
            continue


def extract_title(visible):
    """Názov receptu je obsah prvej značky h1."""
    title_match = TITLE.search(visible)
    if title_match is None:
        return ""
    return clean_text(title_match[1])


def combine_ingredient(quantity, text):
    """Spojí množstvo a surovinu, pokiaľ text už nemá úplné množstvo."""
    if LEADING_MEASURE.match(text):
        # Napr. text „10 tablespoons blueberries“ už obsahuje vlastné množstvo.
        return text
    if quantity and text.startswith(quantity + " "):
        # Napr. množstvo „1“ a text „1 lb beef“ nesmú vytvoriť „1 1 lb beef“.
        return text
    parts = []
    if quantity:
        parts.append(quantity)
    if text:
        parts.append(text)
    return " ".join(parts)


def extract_ingredients(visible):
    """Z prvého ingredient-list vyberie jednotlivé li a ich dva span bloky."""
    ingredients = []
    for block in class_blocks(visible, "ul", "ingredient-list"):
        for item in ITEM.finditer(block):
            quantity = next(class_blocks(item[1], "span", "ingredient-quantity"), "")
            text = next(class_blocks(item[1], "span", "ingredient-text"), "")
            quantity = clean_text(quantity)
            text = clean_text(text)
            ingredient = combine_ingredient(quantity, text)
            if ingredient:
                ingredients.append(ingredient)
        break
    return ingredients


def extract_instructions(visible):
    """Postup môže byť uložený v ul alebo ol s triedou direction-list."""
    instructions = []
    for tag in ("ul", "ol"):
        block = next(class_blocks(visible, tag, "direction-list"), None)
        if block is not None:
            for item in ITEM.finditer(block):
                text = clean_text(item[1])
                if text:
                    instructions.append(text)
            break
    return instructions


def extract_recipe(document, recipe_id="", url=""):
    """Riadi extrakciu: očistí HTML, vyberie povinné polia a pridá metadáta."""
    # JSON-LD skripty vyberáme neskôr z pôvodného document, nie z visible.
    visible = COMMENTS.sub("", document)
    visible = SCRIPTS.sub("", visible)
    title = extract_title(visible)
    ingredients = extract_ingredients(visible)
    instructions = extract_instructions(visible)

    missing = []
    required_fields = {
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
    }
    for field, value in required_fields.items():
        if not value:
            missing.append(field)
    if missing:
        raise ExtractionError("Missing REGEX fields: " + ", ".join(missing))

    facts = {}
    for match in FACT.finditer(visible):
        label = clean_text(match[1]).rstrip(":").lower()
        facts[label] = clean_text(match[2])
    structured = next(structured_recipes(document), {})
    warnings = []
    if structured:
        if clean_text(str(structured.get("name", ""))) != title:
            warnings.append("JSON-LD title differs from visible HTML")
        for key, entries in (
            ("recipeIngredient", ingredients),
            ("recipeInstructions", instructions),
        ):
            expected = structured.get(key)
            if isinstance(expected, list) and len(expected) != len(entries):
                warnings.append(f"JSON-LD {key} count differs from visible HTML")
    else:
        warnings.append("No valid Recipe JSON-LD for cross-check")
    total_time = duration_minutes(facts.get("ready in"))
    if total_time is None:
        total_time = duration_minutes(str(structured.get("totalTime", "")))
    # Počet porcií alebo kusov nemusí byť vo viditeľnom HTML vyplnený.
    yield_value = (
        structured.get("recipeYield") or facts.get("serves") or facts.get("yields")
    )
    if isinstance(yield_value, list):
        yield_value = ", ".join(str(x) for x in yield_value)
    rating = structured.get("aggregateRating", {})
    # Porcie berieme zo SERVES. Údaj YIELDS môže označovať aj počet kusov.
    serving_match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?",
        facts.get("serves", ""),
    )
    if serving_match is None and yield_value:
        serving_match = re.search(
            r"(?<![\d./])(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?"
            r"\s+serving(?:s|\(s\))?",
            clean_text(str(yield_value)), re.IGNORECASE,
        )
    servings = float(serving_match[1]) if serving_match else None
    return {
        "recipe_id": str(recipe_id),
        "url": url,
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
        "total_time_minutes": total_time,
        "yield_text": clean_text(str(yield_value)) if yield_value else None,
        "servings": servings,
        "category": structured.get("recipeCategory"),
        "rating": rating.get("ratingValue") if isinstance(rating, dict) else None,
        "extraction_method": "regex_html",
        "warnings": warnings,
    }
