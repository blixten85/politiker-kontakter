# Politiker-kontakter

Scraper som hämtar e-postadresser till förtroendevalda i svenska regioner och
kommuner (samt EU-parlamentet, riksdagen och departementen), och synkar till
D1-databasen som driver [politiker-webapp](https://politiker.denied.se).

## Publicerad data

Hela kontaktdatabasen publiceras i [`data/`](data/) — namn, e-post, område,
områdestyp, parti och befattning för samtliga ~17 000 folkvalda:

| Fil | Format | Användning |
| --- | --- | --- |
| `data/politiker.csv` | CSV | Kanonisk, människoläsbar — öppnas i Excel/pandas/osv |
| `data/politiker.json` | JSON | Programmatisk användning |
| `data/politiker.sql` | SQL (`INSERT OR IGNORE`) | Direktimport till en egen D1 |

Filerna genereras direkt ur live-D1:n (read-only) av
[`.github/workflows/export-politiker.yml`](.github/workflows/export-politiker.yml),
som veckovis öppnar en auto-mergad PR när datan ändrats. Ingen extern skrapning
sker i den workflowen — den läser bara den redan publika databasen.

Importera till en egen politiker-webapp-kopia (efter `infra/schema.sql`):

```bash
wrangler d1 execute <din-db> --remote --file data/politiker.sql
```

### Kontaktkort till mobilen (VCF)

Vill du lägga in kontakterna i telefonen genereras VCF **på begäran** ur den
lokala `data/politiker.csv` — ingen belastning på sidan eller databasen. Filtrera
så du bara får det du vill ha och importera `.vcf`-filen i telefonens kontakter:

```bash
python3 export/to_vcf.py                          # alla i en samlad fil
python3 export/to_vcf.py --area "Lysekils kommun" # bara en kommun
python3 export/to_vcf.py --type riksdag           # hela riksdagen
python3 export/to_vcf.py --per-area               # en fil per område
```

Filerna skrivs till `vcf/` (committas inte). Detta ersätter de tidigare
hårdkodade VCF-filerna i repot.

## Köra scrapern själv

```bash
cp .env.example .env
# Justera OUTPUT_DIR i .env
docker compose up
```

Scrapern skriver VCF-filer (en per region + en samlad) till `OUTPUT_DIR`
lokalt och kan synka till D1 via `scraper/sync_to_d1.py`.

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
