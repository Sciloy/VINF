"""Lokálne webové rozhranie pre index PyLucene."""

import re
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from evaluate_recipes import split_query_filters, wiki_origin
from lucene_recipes import SOURCE_LABELS, open_search, recipe_source


STYLE = """
:root{font:16px/1.5 system-ui,sans-serif;color:#202d29;background:#f4f6f1}
*{box-sizing:border-box}body{margin:0}
main{width:min(1120px,94vw);margin:34px auto}h1,h2,h3,p{margin:0 0 .65rem}
h1{font-size:2rem}h2{font-size:1.45rem}h3{font-size:1.04rem}
form,.results,article{background:#fff;border:1px solid #dce3da;border-radius:12px;padding:18px}
form{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:end;margin-bottom:16px}
label{display:grid;gap:4px;font-weight:600}input,select,button{font:inherit;padding:8px 11px;border:1px solid #a4b5a9;border-radius:7px}
input,select{width:100%;background:white;color:inherit}
button{background:#225543;color:white;border-color:#225543;cursor:pointer}
.columns{display:grid;grid-template-columns:minmax(220px,1fr) minmax(0,1.7fr);gap:16px;align-items:start}
.results ul{list-style:none;margin:0;padding:0}.results li+li{border-top:1px solid #e4e9e3}
.results a{display:block;padding:9px 5px;text-decoration:none;color:inherit;overflow-wrap:anywhere}
.results a:hover,.results a[aria-current=true]{background:#edf3ed}
small,dt{color:#435b50}small{display:block}.source{color:#225543;font-weight:600}
article section{margin-top:16px;padding-top:14px;border-top:1px solid #e4e9e3}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:8px 0}
dd{margin:0}a{color:#206249}ul,ol{padding-left:1.45rem}.error{color:#8e291e}
@media(max-width:690px){.columns{grid-template-columns:1fr}form{grid-template-columns:1fr auto}form label:first-child{grid-column:1/-1}}
"""


def detail(row):
    source = recipe_source(row)
    wikipedia = source == "wikipedia"
    article_url = f'https://en.wikipedia.org/?curid={int(row["wiki_id"])}' if row.get("wiki_id") else ""
    url = row.get("url") or ""
    facts = []
    for key, label, suffix in (("total_time_minutes", "Celkový čas", " min"), ("servings", "Porcie", ""),
                               ("yield_text", "Výťažnosť", ""), ("category", "Kategória Food.com", "")):
        if row.get(key) is not None:
            facts.append(f"<dt>{label}</dt><dd>{escape(str(row[key]))}{suffix}</dd>")
    facts_html = f"<dl>{''.join(facts)}</dl>" if facts else ""
    parts = [f'<article id="detail"><h2>{escape(row["title"])}</h2>',
             f'<p class="source">{SOURCE_LABELS[source]}</p>',
             f'<p><small>ID {escape(row["recipe_id"])}</small></p>', facts_html]
    if not wikipedia:
        if url.startswith(("https://www.food.com/", "https://food.com/")):
            parts.append(f'<p><a href="{escape(url)}">Otvoriť recept na Food.com</a></p>')
        for key, label, tag in (("ingredients", "Suroviny", "ul"), ("instructions", "Postup", "ol")):
            if items := row.get(key):
                content = "".join(f"<li>{escape(item)}</li>" for item in items)
                parts.append(f"<section><h3>{label} z Food.com</h3><{tag}>{content}</{tag}></section>")
    if article_url:
        parts.append(f'<section><h3>Údaje z Wikipédie</h3><p><a href="{article_url}">'
                     f'{escape(row.get("wiki_title") or "Otvoriť článok")}</a></p>')
        if row.get("wiki_match_type") == "related":
            parts.append("<p>Súvisiaci článok podľa podobného jedla.</p>")
        else:
            wiki = row.get("wiki") or {}
            values = (("Pôvod", wiki_origin(row)), ("Kuchyňa", wiki.get("cuisine")),
                      ("Typ jedla", wiki.get("type")), ("Typické suroviny", wiki.get("ingredients")))
            info = "".join(f"<dt>{label}</dt><dd>{escape(value)}</dd>" for label, value in values if value)
            if info:
                parts.append(f"<dl>{info}</dl>")
        if wikipedia and (summary := row.get("wiki_summary")):
            parts.append(f"<p>{escape(summary)}</p>")
        parts.append("</section>")
    if wikipedia and (steps := row.get("instructions")):
        parts.append("<section><h3>Príprava podľa Wikipédie</h3>")
        parts.extend(f"<p>{escape(step)}</p>" for step in steps)
        parts.append("</section>")
    parts.append("</article>")
    return "".join(parts)


def render(lookup, params):
    query = params.get("q", [""])[0].strip()
    source = params.get("source", [""])[0]
    source = source if source in SOURCE_LABELS else ""
    identifier = params.get("id", [""])[0]
    options = "".join(f'<option value="{key}"{" selected" if key == source else ""}>{label}</option>'
                      for key, label in {"": "Všetky", **SOURCE_LABELS}.items())
    hits, selected, message = [], None, ""
    try:
        text, filters = split_query_filters(query)
        hits = lookup(text, limit=12, source=source, **filters)
        if re.fullmatch(r"(?:wiki)?[0-9]+", identifier):
            matches = [row for row in hits if row["recipe_id"] == identifier] or lookup(f'recipe_id:"{identifier}"', 1)
            selected = next(iter(matches), None)
        else:
            selected = next(iter(hits), None)
    except ValueError as error:
        message = f'<p class="error" role="alert">{escape(str(error))}</p>'
    results = []
    for row in hits:
        href = "/?" + urlencode({"q": query, "source": source, "id": row["recipe_id"]}) + "#detail"
        current = ' aria-current="true"' if selected and row["recipe_id"] == selected["recipe_id"] else ""
        results.append(f'<li><a href="{escape(href)}"{current}>{escape(row["title"])}'
                       f'<small>{SOURCE_LABELS[recipe_source(row)]}</small></a></li>')
    listing = f"<ul>{''.join(results)}</ul>" if results else "<p>Žiadne výsledky.</p>"
    return f"""<!doctype html>
<html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vyhľadávanie receptov</title><style>{STYLE}</style></head><body><main>
<h1>Vyhľadávanie receptov</h1>
<form action="/" method="get">
<label>Dopyt<input type="search" name="q" value="{escape(query)}" placeholder="napr. tomato soup"></label>
<label>Zdroj<select name="source">{options}</select></label><button>Vyhľadať</button>
</form>{message}
<div class="columns"><section class="results"><h2>Výsledky</h2>{listing}</section>
{detail(selected) if selected else ''}</div></main></body></html>"""


def serve(root, bind, port):
    with open_search(root) as lookup:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                request = urlsplit(self.path)
                if request.path != "/":
                    self.send_error(404)
                    return
                page = render(lookup, parse_qs(request.query)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

        with HTTPServer((bind, port), Handler) as server:
            print(f"Vyhľadávanie receptov: http://localhost:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
