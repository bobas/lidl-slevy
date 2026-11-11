# Hlídač nových slev Lidl.cz

Skript prochází [online nabídku slev](https://www.lidl.cz/q/query/slevy?sort=percentageDiscount-desc&availabilityIndicator=2&availabilityIndicator=3&online=1&discountFlag=1)
od nejvyšších slev a vytvoří přehled novinek nad zvolenou hranicí. Historii uchovává lokálně v SQLite. Nepotřebuje účet,
API klíč ani placenou službu.

## Spuštění

Potřebujete **Python 3.10 nebo novější** a přístup k internetu. Skript používá jen
standardní knihovnu; není potřeba instalovat balíčky.

V adresáři projektu spusťte:

```bash
python3 lidl_slevy.py --open
```

Na Windows můžete použít `py -3 lidl_slevy.py --open`. Parametr `--open` otevře
hotový přehled v prohlížeči. Bez něj se pouze uloží soubory a vypíší výsledky.

Výchozí hranice je **více než 35 %**. Vlastní hranici nastavíte parametrem:

```bash
python3 lidl_slevy.py --min-discount 50 --open
python3 lidl_slevy.py --min-discount 42.5 --open
```

Lze použít i desetinnou čárku (`42,5`). Hodnota musí být od 0 do méně než 100;
produkt s přesně zadanou slevou se nezobrazí.

**První úspěšné spuštění pouze uloží výchozí stav:** načtené aktuální produkty
považuje za již viděné. První přehled proto neobsahuje novinky. Příště spusťte
stejný příkaz; historie se načte automaticky. Kontrola může trvat několik minut.

## Co se zobrazí

- Produkt se slevou **větší než zvolená hranice** (výchozí 35 %), který ještě nebyl zaznamenaný nad touto
  hranicí. Patří sem také produkt, který měl dříve například 30 % a nyní má 36 %.
- Již viděný produkt, jehož sleva vzrostla o **více než 15 procentních bodů**
  oproti poslednímu přehledu, ve kterém byl uvedený, nebo oproti výchozímu stavu.

Například 40 → 55 % se nezobrazí, 40 → 56 % ano. Postupné změny
40 → 48 → 53 → 56 % se také zachytí až při 56 %. Pokles slevy ani dočasné
zmizení produktu nesmaže předchozí historii; návrat stejné nabídky se neopakuje.
Přesně 35 % při výchozím nastavení nevyhovuje podmínce. Změna hranice nemaže
historii. Při jejím snížení se mohou zobrazit dříve nesledované nabídky;
již zaznamenané vyšší slevy se znovu neopakují.

Sleva se přebírá tak, jak ji uvádí Lidl, včetně jeho srovnávací ceny; nepočítá se
znovu z cen. Produkty se rozlišují stabilním ID. Pokud se stejné ID objeví vícekrát
například kvůli barevným variantám, přehled použije nejvyšší zobrazenou slevu.
Používají se stejné filtry dostupnosti jako ve výše uvedeném odkazu.

## Výstupy a historie

- `reports/slevy-2026-11-09_18-42-07.html` — příklad přehledu s místním datem a časem.
  Vedle názvu s odkazem
  se při připojení k internetu načte náhled produktu z Lidlu.
- `reports/slevy-2026-11-09_18-42-07.csv` — stejný seznam pro tabulkový procesor, se středníkem a UTF-8 BOM.
- `data/history.sqlite3` — trvalá historie. **Nemažte ji**, pokud chcete zachovat paměť.

Výchozí cesty jsou relativní k umístění projektu, takže přímé spuštění skriptu
z jiného adresáře používá stejnou historii. Každý úspěšný běh uloží nový pár HTML a CSV.
Při shodě času se k názvu přidá pořadové číslo. `--open` otevře právě vytvořený HTML
přehled. Starší přehledy můžete smazat ručně. Samotné vytvoření přehledu při běžné
kontrole znamená „viděno“.

```bash
# Vyzkoušet aktuální novinky bez označení jako viděné:
python3 lidl_slevy.py --dry-run --open

# Vlastní umístění historie a základ názvu výstupů s časovou značkou:
python3 lidl_slevy.py --state moje-data/historie.sqlite3 --output vystup/slevy.html

# Přehled parametrů:
python3 lidl_slevy.py --help
```

Skript čte stránky postupně v pořadí `percentageDiscount-desc`. Úvodní denní
akce poznává podle příznaku `dealOfDay.active`, bez předpokladu pevného počtu;
jejich nižší sleva kontrolu nezastaví. Jakmile první běžná nabídka dosáhne zvolené
hranice nebo klesne pod ni, další stránky se již nestahují. I denní akce se do
výsledků dostanou pouze při splnění zvolené hranice a pravidel historie.

Mezi stránkami čeká půl sekundy a dočasné síťové chyby zkusí opakovat.
Průběžné změně počtu nabídek se
přizpůsobí; výsledky představují snímek za dobu kontroly, nikoli za jediný okamžik.
Při neúplné odpovědi, chybějící stránce nebo chybě zápisu historii neposune.
Předchozí úspěšný HTML přehled zůstane při chybě stahování zachovaný.
Při problému s připojením zkuste příkaz spustit později.
Změna interního rozhraní Lidl.cz může vyžadovat úpravu skriptu.

## Struktura a vývoj

```text
lidl_slevy.py          přímé spuštění bez instalace
src/lidl_watch/        stahování, pravidla, SQLite, HTML/CSV, příkazová řádka
tests/                automatické testy bez internetu
tests/fixtures/       zkrácený skutečný vzorek odpovědi Lidl.cz
data/                 lokální historie (ignorovaná Gitem)
reports/              vygenerované přehledy (ignorované Gitem)
```

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src lidl_slevy.py
```

Testy pokrývají první běh, volitelnou hranici, denní akce, předčasné ukončení,
přesné hranice, postupné zvyšování, návrat produktů,
uchování historie mezi běhy, stránkování, síťové chyby a vrácení databázové transakce
při chybě výstupu. Runtime nemá externí závislosti, proto nepotřebuje lockfile.
Používejte čtyřmezerné odsazení; `.editorconfig` a konfigurace Ruff v `pyproject.toml`
udržují jednotný styl. Pokud máte Ruff nainstalovaný, použijte `ruff format .` a `ruff check .`.
