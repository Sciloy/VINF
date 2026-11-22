# VINF – recepty z Food.com

Scrapy crawler, REGEX extraktor a vlastné vyhľadávanie s dvoma metódami IDF.
Python 3.10+, overené s Python 3.14. Príkazy sa spúšťajú z koreňa projektu.

## Vyhľadávanie s hotovými indexmi

V repozitári sú dva hotové indexy. Pôvodný index je v `data/index/index.json`
a PyLucene index je v `data/part2/lucene/`. Na ich porovnanie stačí spustený
Docker Desktop. Obraz `coady/pylucene:9.12.0` už obsahuje PyLucene.
Príkazy zadaj v PowerShelli z koreňa projektu.

```powershell
$mount = "type=bind,source=$((Get-Location).Path),target=/vinf"
$image = 'coady/pylucene:9.12.0'
docker run --rm -it --mount $mount -w /vinf --entrypoint python3 $image scripts/vinf.py compare-search
```

V porovnaní zadaj napríklad `butter chicken` alebo `tomato soup`.
Z každého indexu sa zobrazí najviac päť výsledkov. Príkaz `:id 282620`
otvorí detail receptu. Program pri tomto spustení načíta hotové indexy z disku.

### Číselné filtre

Príkaz `lucene-search` sa spúšťa priamo z PowerShellu. Nasledujúci príklad
vyhľadá lievance s celkovým časom najviac 30 minút a aspoň štyrmi porciami.
Premenné `$mount` a `$image` sú nastavené v bloku vyššie.

```powershell
docker run --rm --mount $mount -w /vinf --entrypoint python3 $image scripts/vinf.py lucene-search pancakes --max-minutes 30 --min-servings 4
```

## Opätovné spracovanie a indexovanie

Korpus po extrakcii je v `data/processed/recipes.jsonl`. Výstup spojenia
s Wikipédiou je v `data/part2/recipes.jsonl`. Pre vytvorenie PyLucene
indexu z tohto výstupu použi rovnaký Docker príkaz s `lucene-index`
namiesto `compare-search`. Pôvodný TF-IDF index sa tvorí príkazom
`python scripts/vinf.py index`.

Na zopakovanie spojenia použi Java 17, PySpark 4.1.2 a zodpovedajúci
XML dump anglickej Wikipédie. Prepínač `--indexed` načíta relevantné
bloky dumpu pomocou sprievodného indexu Wikimedia.

```powershell
python -m pip install pyspark==4.1.2
python scripts/vinf.py spark-join data/wiki/enwiki-20261101-pages-articles-multistream.xml.bz2 --indexed
```

## Inštalácia crawlera

Súbor `requirements.txt` je určený pre crawler. Inštalácia PySparku na
spracovanie dát je uvedená vyššie v časti Opätovné spracovanie a indexovanie.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Spustenie

```powershell
python -m scrapy crawl food -s CLOSESPIDER_ITEMCOUNT=50 -s CRAWL_TARGET_BYTES=1000000000
python scripts/vinf.py all
python scripts/vinf.py search "chicken soup" --method classic
python scripts/vinf.py search "chicken soup" --method smooth
python scripts/vinf.py search "chicken 15 minutes" --ingredient chicken
python scripts/vinf.py search "chicken rice" --ingredient chicken --ingredient rice --min-servings 4
python scripts/vinf.py compare "banana bread" "fluffy pancakes" "macaroni cheese"
```

`all` vykoná extrakciu, vytvorenie indexu a porovnanie troch dopytov.
Samostatné kroky: `extract`, `index`, `search`, `compare`.
`--max-minutes` obmedzí celkový čas, `--min-servings` počet porcií.
Každý `--ingredient` musí byť v zozname surovín. Zápis `15 minutes` v dopyte
znamená čas najviac 15 minút; nejde o všeobecné rozpoznávanie otázok.

## Top 5 receptov a porovnanie poradia

```powershell
python scripts/vinf.py query "macaroni cheese"
python scripts/vinf.py query "chicken 15 minutes" --ingredient chicken
python scripts/vinf.py query
```

`query` zobrazí top 5 pre `classic` aj `smooth` v jednej tabuľke s poradím
a skóre. Pod ňou vypíše každý recept iba raz: ID, URL, čas, porcie,
výťažnosť, kategóriu, hodnotenie, rodinu, všetky suroviny a celý postup.
Pomlčka znamená, že recept nie je v top 5 danej metódy.
Bez zadaného textu sa príkaz opýta na dopyt. Výpis možno upraviť cez
`--limit`, `--method classic`, `--method smooth` alebo `--method both`.
Podporuje rovnaké filtre ako `search`. Iba číta existujúci index a zhodné
extrahované recepty; neprestavuje index a nemení uložené porovnania.

## Metadáta zberu

`data/crawl_metadata.jsonl` ukladá iba `url`, `recipe_id`, `slug`,
`http_status`, `html_file`, `html_bytes` a `title`. Dôvody chýb sú
v samostatnom `data/crawl_failures.jsonl`. Kontrolné súčty v spracovaných
dátach a indexe slúžia na overenie ich zhody.

## Súbory

| Cesta | Obsah |
| --- | --- |
| `food_crawler/` | Crawler, extraktor, indexer a nastavenia |
| `scripts/vinf.py` | Spracovanie dát a vyhľadávanie |
| `config/` | Vstupné URL a vyradené recepty |
| `data/raw/`, `data/crawl_metadata.jsonl` | HTML a metadáta |
| `data/processed/` | Extrahované recepty a štatistiky |
| `data/index/index.json` | Pôvodný TF-IDF index |
| `data/part2/recipes.jsonl` | Recepty po spojení s Wikipédiou |
| `data/part2/lucene/` | Hotový PyLucene index |
| `data/reports/comparison.json` | Porovnanie metód IDF |

`compare` vytvorí porovnanie z existujúceho indexu; `all` ho vytvorí tiež.
Samotný `index` ho nevytvára. `docs/comparison.json` obsahuje porovnanie použité vo wiki.

`internal/` obsahuje pomocné riadenie zberu a rozšírené kontroly.
Do odovzdania nepatrí. Hotový archív je `dist/vinf-code.zip`.
