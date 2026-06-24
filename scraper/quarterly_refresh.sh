#!/bin/bash
# Kvartalsvis uppdatering av hela politiker-listan: skrapar om kommun/region,
# synkar till D1, och uppdaterar parti för EU/riksdag/kommun/region.
#
# Första riktiga körning ska ske EFTER valet 2026-09 (ny mandatperiod) —
# se crontab-kommentar. Körs sedan var 3:e månad.
set -e
cd "$(dirname "$0")"

set -a
source ~/.appdata/.config/.env
set +a

echo "=== $(date -Iseconds) Startar kvartalsvis uppdatering ==="

echo "--- Skrapar kommun/region (Playwright/Docker) ---"
cd ..
docker compose up --abort-on-container-exit
cd scraper

echo "--- Synkar kommun/region till D1 ---"
python3 sync_to_d1.py

echo "--- Hämtar EU-parlamentariker (alla 27 länder) ---"
python3 fetch_eu_meps.py

echo "--- Hämtar riksdagens nuvarande ledamöter ---"
python3 fetch_riksdagen_members.py

echo "--- Synkar regeringens departement ---"
python3 sync_regeringen.py

echo "--- Fyller i parti för kommun/region via Valmyndigheten ---"
python3 sync_party_from_val.py

echo "=== $(date -Iseconds) Klart ==="
