"""Kuchyne odhadnuté z konkrétnych zmienok alebo známej rodiny jedla."""

import re
import unicodedata


CUISINES = {
    "italian": (
        ("italian", "italy", "taliansko", "taliansky", "talianska", "talianske"),
        ("lasagna", "risotto", "gnocchi", "carbonara", "tiramisu", "pesto", "pizza"),
    ),
    "french": (
        ("french", "france", "francuzsko", "francuzsky", "francuzska", "francuzske"),
        ("ratatouille", "quiche", "bouillabaisse", "coq_au_vin"),
    ),
    "mexican": (
        ("mexican", "mexico", "mexiko", "mexicky", "mexicka", "mexicke"),
        ("taco", "tacos", "enchilada", "enchiladas", "guacamole", "quesadilla", "quesadillas"),
    ),
    "indian": (
        ("indian", "india", "indicky", "indicka", "indicke"),
        ("butter_chicken", "palak_paneer", "tandoori_chicken", "naan"),
    ),
    "chinese": (
        ("chinese", "china", "cina", "cinsky", "cinska", "cinske"),
        ("chow_mein", "lo_mein", "kung_pao_chicken", "peking_duck"),
    ),
    "japanese": (
        ("japanese", "japan", "japonsko", "japonsky", "japonska", "japonske"),
        ("sushi", "tempura", "okonomiyaki", "teriyaki"),
    ),
    "thai": (
        ("thai", "thailand", "thajsko", "thajsky", "thajska", "thajske"),
        ("pad_thai", "tom_yum", "som_tam"),
    ),
    "greek": (
        ("greek", "greece", "grecko", "grecky", "grecka", "grecke"),
        ("tzatziki", "souvlaki", "spanakopita"),
    ),
    "spanish": (
        ("spanish", "spain", "spanielsko", "spanielsky", "spanielska", "spanielske"),
        ("paella", "gazpacho", "patatas_bravas"),
    ),
    "american": (
        ("american", "united states", "usa", "americky", "americka", "americke"),
        ("buffalo_wings", "sloppy_joe"),
    ),
}


def normalized(value):
    plain = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", plain))


def recipe_cuisines(recipe):
    wiki = (recipe.get("wiki") or {}) if recipe.get("wiki_match_type") != "related" else {}
    fields = (
        ("Wikipedia", [wiki.get("country"), wiki.get("region"), wiki.get("cuisine")]),
        ("kategória Food.com", [recipe.get("category")]),
        ("názov receptu", [recipe.get("title")]),
    )
    evidence = [(label, " " + " ".join(normalized(value) for value in values if isinstance(value, str)) + " ")
                for label, values in fields]
    title = " " + normalized(recipe["title"]) + " "
    family = recipe.get("dish_family") if recipe.get("family_rule_known") else None
    hints = {}
    for cuisine, (terms, dishes) in CUISINES.items():
        sources = [label for label, text in evidence if any(f" {term} " in text for term in terms)]
        if family in dishes:
            sources.append("rodina jedla")
        elif any(f" {dish.replace('_', ' ')} " in title for dish in dishes):
            if "názov receptu" not in sources:
                sources.append("názov jedla v recepte")
        if sources:
            hints[cuisine] = sources
    return hints


def cuisine_query(query):
    """Preloží krátke otázky ako 'taliansky recept' na dopyt nad kuchyňou."""
    if re.search(r'[:+"()!*?~^\[\]{}\\]', query):
        return query
    phrase = normalized(query)
    for suffix in (" recept", " recepty", " kuchyna", " recipe", " recipes", " cuisine"):
        phrase = phrase.removesuffix(suffix)
    for cuisine, (terms, _) in CUISINES.items():
        if phrase in terms:
            return f"cuisine_hint:{cuisine}"
    return query
