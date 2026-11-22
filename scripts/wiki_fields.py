"""Textové atribúty anglickej šablóny Infobox food."""

import html
import re


def clean(value):
    value = re.sub(r"<ref\b[^>]*?(?:/>|>.*?</ref\s*>)", "", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>|'{2,}", " ", value)
    return " ".join(html.unescape(value).split())


def food_fields(text):
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
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
    box = clean_links(re.sub(r"<ref\b[^>]*?(?:/>|>.*?</ref\s*>)", "", box, flags=re.I | re.S))
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
