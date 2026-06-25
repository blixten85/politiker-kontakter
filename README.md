# Politiker-kontakter

Scraper som hämtar e-postadresser till förtroendevalda i svenska regioner och kommuner.
Sparar resultatet som VCF-filer som kan importeras direkt till iPhone-kontakter,
och synkar till D1-databasen som driver [politiker-webapp](https://politiker.denied.se).

## Användning

```bash
cp .env.example .env
# Justera OUTPUT_DIR i .env
docker compose up
```

VCF-filerna sparas i `./output/` – en per region samt en samlad `Alla_regioner.vcf`.

## Struktur

- `scraper/scraper.py` – huvudlogik, Playwright-baserad
- `scraper/fetch_eu_meps.py` – EU-parlamentariker (namn, parti, utskottsbefattning)
- `scraper/fetch_riksdagen_members.py` – riksdagsledamöter
- `scraper/sync_regeringen.py` – departementens registratorsadresser
- `scraper/backfill_kommun_role_party.py` – engångs-/återkörbar bakfyllning av
  befattning+parti för kommun/region via troman/netpublicator-källornas
  ledamotslistor (samma datakälla som `scraper.py`, separat steg eftersom det
  görs per person istället för per region)
- `scraper/backfill_riksdagen_role.py` – motsvarande bakfyllning för riksdagen
- `scraper/sync_party_from_val.py` – matchar parti mot Valmyndighetens öppna data
  där det inte går att fastställa direkt vid skrapning
- `scraper/sync_to_d1.py` – upsert av hela `alla_people`-datastrukturen till
  politiker-webapps D1-databas (`politicians`-tabellen)
- `scraper/Dockerfile` – bygger scrapern
- `docker-compose.yml` – kör allt

## Lägga till kommuner

Lägg till poster i listan `REGIONER` i `scraper.py` med kommunens fullmäktigesida.
