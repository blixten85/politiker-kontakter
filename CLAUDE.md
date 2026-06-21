# politiker-kontakter — Claude Code Guide

Scraper som hämtar publikt publicerade e-postadresser till förtroendevalda
(kommunfullmäktige och regionfullmäktige) i Sveriges 290 kommuner och 21
regioner. Sparar resultatet som VCF-filer (för import till t.ex. iPhone-
kontakter) och en alfabetiskt sorterad textfil.

## Tech Stack

- Python 3, Playwright (headless Chromium)
- `pypdf` för PDF-baserade ledamotslistor
- Docker / Docker Compose

## Dev Commands

```bash
cp .env.example .env
# Justera OUTPUT_DIR/LOG_DIR i .env
docker compose up
```

## Project Structure

```
scraper/scraper.py      # Huvudlogik — alla scrape_*-funktioner + REGIONER-listan
scraper/Dockerfile       # Bygger scrapern
scraper/entrypoint.sh
docker-compose.yml
UNSUPPORTED_KOMMUNER.md # Kommuner som saknar stöd/känt register
```

## Datamodell

Varje `scrape_*`-funktion returnerar en `set()` av `(politiker-namn, email)`-
tupler (namn kan vara tom sträng om inget namn gick att extrahera). `main()`
samlar detta per kommun/region i `alla_people`, sparar en `.vcf` per region
samt en samlad, alfabetiskt sorterad `Alla_kommuner_och_regioner.txt`
(`swedish_key()` ger svensk sorteringsordning utan att förlita sig på
OS-locale).

## Lägga till kommuner/regioner

Lägg till en post i listan `REGIONER` i `scraper.py` med kommunens/regionens
fullmäktigesida och rätt `"typ"` (`mailto`, `netpublicator`, `troman`,
`w3d3`, `fmr`, `profilsidor`, `namnmonster`, `pdf`, `namnlista`) beroende på
hur ledamotslistan är publicerad.

## Conventions

- Inga inloggningsuppgifter eller hemligheter hanteras — all data är redan
  offentligt publicerad av kommunerna/regionerna själva
- Skärp aldrig TLS-validering (`ignore_https_errors` etc.) i den committade
  `scraper.py` — sådana workarounds hör endast hemma i lokala testkopior
- Långa körningar (alla 273 poster) bör checkpointa namn+e-post per region,
  inte bara skriva slutfilen efter att hela listan är klar
