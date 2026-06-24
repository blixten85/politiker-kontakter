#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hämtar ALLA ledamöter i Europaparlamentet (alla 27 EU-länder) via
EU-parlamentets öppna data-API (data.europarl.europa.eu) och synkar till
D1-tabellen `politicians` (area_type='eu', area_name='Europaparlamentet
(<land>)' — ett område per land, så mottagarlistan kan filtreras per land
senare).

Mail-adresser finns inte i API-svaret — varje ledamots officiella profilsida
innehåller en spam-skyddad, omvänd sträng (t.ex. "ue[dot]aporue.lraporue[at]
nergmloh.rap") som avkodas till "par.holmgren@europarl.europa.eu". Avkodning:
ersätt "[dot]"->"." och "[at]"->"@", sedan vänd strängen.

Miljövariabler som krävs (samma .env som sync_to_d1.py):
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER
  D1_DATABASE_UUID
"""

import os
import re
import sys
import time

import requests

EP_API_BASE = "https://data.europarl.europa.eu/api/v2"

# Svenska landsnamn för EU:s 27 medlemsländer (ISO 3166-1 alpha-2).
COUNTRY_NAMES = {
    "AT": "Österrike", "BE": "Belgien", "BG": "Bulgarien", "CY": "Cypern",
    "CZ": "Tjeckien", "DE": "Tyskland", "DK": "Danmark", "EE": "Estland",
    "ES": "Spanien", "FI": "Finland", "FR": "Frankrike", "GR": "Grekland",
    "HR": "Kroatien", "HU": "Ungern", "IE": "Irland", "IT": "Italien",
    "LT": "Litauen", "LU": "Luxemburg", "LV": "Lettland", "MT": "Malta",
    "NL": "Nederländerna", "PL": "Polen", "PT": "Portugal", "RO": "Rumänien",
    "SE": "Sverige", "SI": "Slovenien", "SK": "Slovakien",
}

UPSERT_SQL = (
    "INSERT INTO politicians (id, name, email, area_name, area_type, party, last_scraped_at) "
    "VALUES (lower(hex(randomblob(11))), ?, ?, ?, 'eu', ?, ?) "
    "ON CONFLICT(email, area_name) DO UPDATE SET name = excluded.name, party = excluded.party, last_scraped_at = excluded.last_scraped_at"
)


def fetch_all_current_meps() -> list[dict]:
    meps = []
    offset = 0
    while True:
        resp = requests.get(
            f"{EP_API_BASE}/meps/show-current",
            params={"limit": 100, "offset": offset},
            headers={"Accept": "application/ld+json"},
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()["data"]
        if not page:
            break
        meps.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return meps


def decode_email(mep_id: str) -> str | None:
    """Returnerar avkodad e-postadress, eller None om profilsidan saknar en
    (inget mailfält publicerat). Kastar requests.HTTPError vid 4xx/5xx —
    det är en riktig miss (rate limit, serverfel), inte "ingen email"."""
    resp = requests.get(f"https://www.europarl.europa.eu/meps/en/{mep_id}/x/home", timeout=20)
    resp.raise_for_status()
    match = re.search(r'class="link_email[^"]*"\s+href="([^"]+)"', resp.text)
    if not match:
        return None
    encoded = match.group(1)
    return encoded.replace("[dot]", ".").replace("[at]", "@")[::-1]


def sync_one(session: requests.Session, url: str, name: str, email: str, area_name: str, party: str | None, now_ms: int) -> bool:
    resp = session.post(url, json={"sql": UPSERT_SQL, "params": [name, email, area_name, party, now_ms]}, timeout=30)
    if resp.status_code == 200 and resp.json().get("success"):
        return True
    print(f"FEL: {name} <{email}>: {resp.text}", file=sys.stderr)
    return False


def main():
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    # Engångsstädning: tidigare körningar (innan per-land-uppdelning) skrev
    # area_name='Europaparlamentet' utan land. Ofarligt att köra om — bara en
    # no-op om raderna redan är borta.
    session.post(
        url,
        json={"sql": "DELETE FROM politicians WHERE area_type = 'eu' AND area_name = 'Europaparlamentet'"},
        timeout=30,
    )

    meps = fetch_all_current_meps()
    print(f"Hittade {len(meps)} EU-parlamentariker totalt (alla 27 länder).", flush=True)

    now_ms = int(time.time() * 1000)
    ok = fail = skipped = 0
    for i, m in enumerate(meps, 1):
        mep_id = m["id"].rstrip("/").split("/")[-1]
        name = f"{m['givenName']} {m['familyName']}"
        country_code = m.get("api:country-of-representation")
        country_name = COUNTRY_NAMES.get(country_code, country_code)
        area_name = f"Europaparlamentet ({country_name})"
        party = m.get("api:political-group")

        try:
            email = decode_email(mep_id)
        except requests.HTTPError as err:
            print(f"FEL (HTTP) för {name} (id {mep_id}): {err}", file=sys.stderr, flush=True)
            fail += 1
            continue
        if not email:
            print(f"VARNING: ingen email hittad för {name} (id {mep_id})", file=sys.stderr, flush=True)
            skipped += 1
            continue

        # Synkar DIREKT, en i taget — om processen avbryts (rate limit, krasch)
        # är allt som redan körts sparat, inget arbete går förlorat.
        if sync_one(session, url, name, email, area_name, party, now_ms):
            ok += 1
        else:
            fail += 1

        if i % 25 == 0:
            print(f"{i}/{len(meps)} klara ({ok} ok, {fail} fel, {skipped} utan email)...", flush=True)
        time.sleep(0.3)

    print(f"Klart. {ok} synkade, {fail} misslyckades, {skipped} utan email.", flush=True)
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
