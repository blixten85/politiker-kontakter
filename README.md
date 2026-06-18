# Politiker-kontakter

Scraper som hämtar e-postadresser till förtroendevalda i svenska regioner och kommuner.
Sparar resultatet som VCF-filer som kan importeras direkt till iPhone-kontakter.

## Användning

```bash
cp .env.example .env
# Justera OUTPUT_DIR i .env
docker compose up
```

VCF-filerna sparas i `./output/` – en per region samt en samlad `Alla_regioner.vcf`.

## Struktur

- `scraper/scraper.py` – huvudlogik, Playwright-baserad
- `scraper/Dockerfile` – bygger scrapern
- `docker-compose.yml` – kör allt

## Lägga till kommuner

Lägg till poster i listan `REGIONER` i `scraper.py` med kommunens fullmäktigesida.
