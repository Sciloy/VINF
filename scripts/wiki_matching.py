"""Candidate titles and evidence for Wikipedia recipe links."""

import json
import re


FAMILY_VARIANTS = {
    "apple_pie": "Apple pie",
    "banana_bread": "Banana bread",
    "butter_chicken": "Butter chicken",
    "cheesecakes": "Cheesecake",
    "chicken_soup": "Chicken soup",
    "chili_con_carne": "Chili con carne",
    "chocolate_chip_cookies": "Chocolate chip cookie",
    "french_fries": "French fries",
    "fried_chicken": "Fried chicken",
    "fried_rice": "Fried rice",
    "hamburgers": "Hamburger",
    "mac_and_cheese": "Macaroni and cheese",
    "muffins": "Muffin",
    "pizzas": "Pizza",
    "potato_salad": "Potato salad",
    "salads": "Salad",
    "soups": "Soup",
    "tomato_soup": "Tomato soup",
}

# Recognizable dish names can occur inside recipe titles with extra words.
DISH_TITLES = {
    "Apple pie": r"\bapple\s+pie\b",
    "Banana bread": r"\bbanana\s+bread\b",
    "Butter chicken": r"\b(?:butter\s+chicken|chicken\s+makhani)\b",
    "Chocolate chip cookie": r"\bchocolate\s+chip\s+cookies?\b",
    "Fried rice": r"\bfried\s+rice\b",
    "French toast": r"\bfrench\s+toast\b",
    "Lasagna": r"\blasagn[ae]\b",
    "Macaroni and cheese": r"\b(?:mac|macaroni)\s+(?:and|&)\s+cheese\b",
    "Potato salad": r"\bpotato\s+salad\b",
    "Tomato soup": r"\btomato\s+soup\b",
    "Chicken soup": r"\bchicken\s+(?:noodle\s+)?soup\b",
    "Chocolate cake": r"\bchocolate\s+cake\b",
    "Meatloaf": r"\bmeat\s*loaf\b",
    "Pancake": r"\bpancakes?\b",
}

# These words can promote a recipe without changing the dish it names.
TITLE_PREFIX = re.compile(r"^(?:(?:the|best|easy|quick|simple|homemade|classic)\s+)+", re.I)
TITLE_SUFFIX = re.compile(r"\s*\([^()]*(?:easy|simple|best ever|quick)[^()]*\)\s*$", re.I)
REDIRECT = re.compile(r"^\s*#redirect\s*:?\s*\[\[([^\]|#]+)", re.I)
DISAMBIGUATION = re.compile(r"\{\{\s*(?:disambig(?:uation)?|dab|hndis|geodis)\b", re.I)
FOOD_CATEGORY = re.compile(
    r"\[\[Category:[^\n\]]*\b(?:dishes|soups|stews|sandwiches|desserts|pastries|cakes|cookies|beverages)\b",
    re.I,
)
FOOD_DEFINITION = re.compile(
    r"\b(?:is|are)\s+(?:a|an|the)\s+(?:[\w'-]+\s+){0,6}"
    r"(?:dish|soup|stew|sandwich|dessert|pastry|cake|cookie|beverage)\b",
    re.I,
)


def title_key(title):
    return " ".join(title.replace("_", " ").split()).lower()


def hash_like(recipe):
    title = title_key(recipe["title"])
    ingredients = " ".join(recipe.get("ingredients") or [])
    steps = " ".join(recipe.get("instructions") or [])
    beef = r"\b(?:ground|minced)\s+beef\b"
    potatoes = r"\bpotato(?:es)?\b"
    return (
        re.search(beef, title) and re.search(potatoes, title)
        and re.search(beef, ingredients, re.I) and re.search(potatoes, ingredients, re.I)
        and re.search(r"\b(?:skillet|fry|frying pan|saut[ée])\b", steps, re.I)
    )


def recipe_candidates(recipe, aliases):
    title = recipe["title"]
    candidates = [(title, "exact_title")]
    if recipe.get("family_rule_known") and (family := recipe.get("dish_family")):
        candidates.append((aliases.get(family, family.replace("_", " ")), "dish_family"))
        if family in FAMILY_VARIANTS:
            candidates.append((FAMILY_VARIANTS[family], "dish_family"))
    candidates.append((TITLE_PREFIX.sub("", TITLE_SUFFIX.sub("", title)), "normalized_title"))
    candidates.extend((name, "dish_family") for name, pattern in DISH_TITLES.items()
                      if re.search(pattern, title, re.I))
    if hash_like(recipe):
        candidates.append(("Hash (food)", "related"))

    seen = set()
    for priority, (name, method) in enumerate(candidates):
        key = title_key(name)
        if key and key not in seen:
            seen.add(key)
            yield key, priority, method


def read_recipe_candidates(source, aliases):
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                recipe = json.loads(line)
                for key, priority, method in recipe_candidates(recipe, aliases):
                    yield dict(recipe_id=str(recipe["recipe_id"]), key=key, priority=priority, match_type=method)


def redirect_key(text):
    match = REDIRECT.match(text or "")
    return title_key(match[1]) if match else None


def food_article(title, text):
    text = text or ""
    return not (title.lower().endswith("(disambiguation)") or DISAMBIGUATION.search(text)) and bool(
        FOOD_CATEGORY.search(text) or FOOD_DEFINITION.search(text[:5000])
    )
