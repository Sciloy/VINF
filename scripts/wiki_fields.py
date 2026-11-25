"""Textové atribúty anglickej šablóny Infobox food."""

import html
import re


REFERENCES = re.compile(r"<ref\b[^>]*?(?:/>|>.*?</ref\s*>)", re.I | re.S)
COMMENTS = re.compile(r"<!--.*?-->", re.S)
HEADING = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.M)
PREPARATION_HEADING = re.compile(
    r"(?:(?:ingredients? and |recipe and )?(?:preparation|preparing|cooking)(?: methods?| and (?:cooking|serving))?"
    r"|(?:traditional |modern )?(?:recipe|preparation)s?|(?:method|methods) of (?:preparation|cooking))",
    re.I,
)
COOKING_ACTION = re.compile(
    r"\b(?:mix(?:es|ed|ing)?|combin(?:e[ds]?|ing)|knead(?:s|ed|ing)?|"
    r"bak(?:e[ds]?|ing)(?!\s+(?:powder|soda))|boil(?:s|ed|ing)?|fri(?:es|ed)|fry(?:ing)?|"
    r"roast(?:s|ed|ing)?|steam(?:s|ed|ing)?|simmer(?:s|ed|ing)?|"
    r"grill(?:s|ed|ing)?|saut(?:é|e)(?:s|d|ing)?|pour(?:s|ed|ing)?|"
    r"stir(?:s|red|ring)?|wrapp?(?:s|ed|ing)?|marinat(?:e[ds]?|ing)|"
    r"ferment(?:s|ed|ing)?|roll(?:s|ed|ing)?|chopp?(?:s|ed|ing)?|"
    r"season(?:ed|ing)|stuff(?:ed|ing)|cooked with|cooked in|made by)\b",
    re.I,
)


def clean(value):
    value = REFERENCES.sub("", value)
    value = re.sub(r"<[^>]+>|'{2,}", " ", value)
    return " ".join(html.unescape(value).split())


def food_fields(text):
    text = COMMENTS.sub("", text or "")
    start = re.search(r"\{\{\s*infobox[ _]+food\b", text, re.I)
    if not start:
        return None
    # Iba parametre vonkajšej šablóny. Vnorené šablóny môžu obsahovať vlastné | a =.
    depth = 1
    end = start.end()
    for token in re.finditer(r"\{\{|\}\}", text[end:]):
        depth += 1 if token[0] == "{{" else -1
        if depth == 0:
            box = text[end:end + token.start()]
            break
    else:
        return None
    box = clean_links(REFERENCES.sub("", box))
    while "{{" in box:
        reduced = re.sub(r"\{\{([^{}]*)\}\}", lambda m: template_text(m[1]), box)
        if reduced == box:
            break
        box = reduced
    fields = {}
    for match in re.finditer(r"\|\s*(country|region|national_cuisine|type|main_ingredient)\s*=\s*([^|]*)", box, re.I):
        fields[match[1].lower()] = clean(match[2]) or None
    return tuple(fields.get(key) for key in ("country", "region", "national_cuisine", "type", "main_ingredient"))


def clean_links(text):
    return re.sub(r"\[\[(?:[^\[\]|]+\|)?([^\[\]]+)\]\]", r"\1", text)


def template_text(body):
    parts = body.split("|")
    if parts[0].strip().lower() in {"plainlist", "ubl", "unbulleted list", "hlist", "flag", "flagcountry"}:
        return ", ".join(p.strip(" *\n") for p in parts[1:] if p.strip())
    return ""


def article_links(text):
    """Read article targets from the body of a Wikipedia food list."""
    text = COMMENTS.sub("", text or "")
    for heading in HEADING.finditer(text):
        if heading[2].casefold() in {"see also", "references", "notes", "external links", "further reading", "bibliography"}:
            text = text[:heading.start()]
            break
    return set(re.findall(r"\[\[\s*([^][|#:\n]+?)(?:#[^][|\n]*)?(?:\|[^][\n]*)?\]\]", text))


def wiki_prose(text):
    text = re.sub(r"<(?:gallery|math)\b[^>]*>.*?</(?:gallery|math)\s*>", "", text, flags=re.I | re.S)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)
    # Work from inner templates out so their markup cannot appear as cooking text.
    while "{{" in text:
        reduced = re.sub(r"\{\{([^{}]*)\}\}", lambda m: template_text(m[1]), text)
        if reduced == text:
            break
        text = reduced
    text = re.sub(r"\[\[(?:File|Image|Category):[^\n]*\]\]", "", text, flags=re.I)
    text = clean_links(text)
    text = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", text)
    return text


def clean_paragraph(text):
    text = re.sub(r"\([\s,;:–-]*\)|\(\s*or\s*\)", "", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", clean(text))


def wiki_recipe_text(text):
    """Return a description and verbatim preparation prose with wiki markup removed."""
    text = REFERENCES.sub("", COMMENTS.sub("", text or ""))
    headings = list(HEADING.finditer(text))
    lead = text[:headings[0].start()] if headings else text
    paragraphs = [clean_paragraph(part) for part in re.split(r"\n\s*\n", wiki_prose(lead))
                  if part.strip() and not part.lstrip().startswith(("*", "#", "|", "!"))]
    summary = next((part for part in paragraphs if len(part.split()) >= 8), None)
    preparation = []
    for index, heading in enumerate(headings):
        if not PREPARATION_HEADING.fullmatch(clean(clean_links(heading[2]))):
            continue
        end = next((other.start() for other in headings[index + 1:]
                    if len(other[1]) <= len(heading[1])), len(text))
        section = wiki_prose(HEADING.sub("", text[heading.end():end]))
        blocks = [clean_paragraph(part.strip(" *#:\t\n"))
                  for part in re.split(r"\n\s*\n|\n(?=[*#])", section)]
        if any(COOKING_ACTION.search(part) for part in blocks if len(part.split()) >= 8):
            preparation.extend(part for part in blocks if part)
    if not preparation:
        preparation = [sentence for part in paragraphs[:2]
                       for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", part)
                       if len(sentence.split()) >= 8 and COOKING_ACTION.search(sentence)]
    return summary, list(dict.fromkeys(preparation))
