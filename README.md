# VINF - vyhľadávanie receptov

Scrapy crawler, REGEX extraktor a vlastné vyhľadávanie s dvoma metódami IDF.
Apache Spark spája recepty Food.com s článkami z Wikipédie. PyLucene
indexuje obohatené recepty aj samostatné záznamy z Wikipédie.
Python 3.10+, overené s Python 3.14. Príkazy sa spúšťajú z koreňa projektu.

## Vyhľadávanie s hotovými indexmi

V repozitári sú dva hotové indexy. Pôvodný index je v `data/index/index.json`
a PyLucene index je v `data/part2/lucene/`. Na ich porovnanie stačí spustený
Docker Desktop. Obraz `coady/pylucene:9.12.0` už obsahuje PyLucene.
Po zmene spojených dát vytvor aktuálny PyLucene index príkazom `lucene-index`.
Príkazy zadaj v PowerShelli z koreňa projektu.

```powershell
$mount = "type=bind,source=$((Get-Location).Path),target=/vinf"
$image = 'coady/pylucene:9.12.0'
docker run --rm -it --mount $mount -w /vinf --entrypoint python3 $image scripts/vinf.py compare-search
```

V porovnaní zadaj napríklad `butter chicken` alebo `tomato soup`.
Z každého indexu sa zobrazí najviac päť výsledkov. Príkaz `:id 282620`
otvorí detail receptu. Program pri tomto spustení načíta hotové indexy z disku.

### GUI v prehliadači

Po vytvorení aktualizovaného PyLucene indexu spusti z koreňa projektu:

```powershell
docker run --rm -p 127.0.0.1:8765:8765 --mount "type=bind,source=$($PWD.Path),target=/vinf,readonly" -w /vinf --entrypoint python3 coady/pylucene:9.12.0 scripts/vinf.py gui --bind 0.0.0.0
```

Otvor [http://localhost:8765](http://localhost:8765). Vo filtri **Zdroj** vyber
**Wikipédia** a klikni na **Vyhľadať** aj bez dopytu. Detail obsahuje opis prípravy
prevzatý z článku, dostupné wiki údaje a odkaz na pôvodnú stránku.
Pri **Food.com + Wikipédia** detail ukazuje suroviny a postup z Food.com
a dostupné údaje z priradeného wiki článku. Server ukončíš cez Ctrl+C.

### Číselné filtre

Filtre sa pridávajú na koniec dopytu v riadku `Dopyt >`.
Platia pre výsledky oboch indexov a dajú sa kombinovať.

| Vstup | Výsledok |
| --- | --- |
| `pancakes --max-minutes 30` | Lievance s celkovým časom najviac 30 minút. |
| `butter chicken --min-servings 4` | Výsledky pre `butter chicken` s aspoň štyrmi porciami. |
| `pancakes --max-minutes 30 --min-servings 4` | Lievance, ktoré spĺňajú obe podmienky. |

## Opätovné spracovanie a indexovanie

Korpus po extrakcii je v `data/processed/recipes.jsonl`. Výstup spojenia
s Wikipédiou je v `data/part2/recipes.jsonl`. Pre vytvorenie PyLucene
indexu z tohto výstupu použi rovnaký Docker príkaz s `lucene-index`
namiesto `compare-search`. Pôvodný TF-IDF index sa tvorí príkazom
`python scripts/vinf.py index`.

Na zopakovanie spojenia použi Java 17, PySpark 4.1.2 a zodpovedajúci
XML dump anglickej Wikipédie. Prepínač `--indexed` pomocou sprievodného
indexu Wikimedia načíta kandidátov podľa názvov receptov a podľa odkazov
v zoznamoch jedál Wikipédie. Ak máš zodpovedajúci lokálny index pod iným
názvom, zadaj jeho cestu cez `--title-index`.
V čerstvom virtuálnom prostredí nainštaluj PySpark cez
`.\.venv\Scripts\python.exe -m pip install pyspark==4.1.2`.

```powershell
$wiki = 'data/wiki/enwiki-20261101-pages-articles-multistream.xml.bz2'
$titleIndex = 'data/wiki/9aa04cdaf3b5b7f78d1f28b3c19c0bcc05b7611c.index.txt.bz2'
.\.venv\Scripts\python.exe scripts/vinf.py spark-join $wiki --indexed --title-index $titleIndex
$mount = "type=bind,source=$($PWD.Path),target=/vinf"
docker run --rm --mount $mount -w /vinf --entrypoint python3 coady/pylucene:9.12.0 scripts/vinf.py lucene-index
```

Spark vypíše `wikipedia_only` (nové záznamy výlučne z Wikipédie),
`matched` (obohatené recepty Food.com) a `recipes` (celkový počet po spojení).
Overenie vzorky aj celého dumpu:

```powershell
.\.venv\Scripts\python.exe scripts/check_part2.py --full --dump $wiki --indexed --title-index $titleIndex
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
