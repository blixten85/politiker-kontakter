#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hämtar svenska ledamöter i Europaparlamentet via EU-parlamentets öppna
data-API (data.europarl.europa.eu) och synkar till D1-tabellen `politicians`
(area_type='eu', area_name='Europaparlamentet').

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
UPSERT_SQL = (
    "INSERT INTO politicians (id, name, email, area_name, area_type, last_scraped_at) "
    "VALUES (lower(hex(randomblob(11))), ?, ?, 'Europaparlamentet', 'eu', ?) "
    "ON CONFLICT(email, area_name) DO UPDATE SET name = excluded.name, last_scraped_at = excluded.last_scraped_at"
)


def fetch_current_meps(country_code: str) -> list[dict]:
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
        meps.extend(m for m in page if m.get("api:country-of-representation") == country_code)
        if len(page) < 100:
            break
        offset += 100
    return meps


def decode_email(mep_id: str) -> str | None:
    resp = requests.get(f"https://www.europarl.europa.eu/meps/en/{mep_id}/x/home", timeout=20)
    match = re.search(r'class="link_email[^"]*"\s+href="([^"]+)"', resp.text)
    if not match:
        return None
    encoded = match.group(1)
    return encoded.replace("[dot]", ".").replace("[at]", "@")[::-1]


def sync(rows: list[tuple[str, str]]) -> tuple[int, int]:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    now_ms = int(time.time() * 1000)
    ok = fail = 0
    for name, email in rows:
        resp = session.post(url, json={"sql": UPSERT_SQL, "params": [name, email, now_ms]}, timeout=30)
        if resp.status_code == 200 and resp.json().get("success"):
            ok += 1
        else:
            fail += 1
            print(f"FEL: {name} <{email}>: {resp.text}", file=sys.stderr)
    return ok, fail


def main():
    meps = fetch_current_meps("SE")
    print(f"Hittade {len(meps)} svenska EU-parlamentariker.")

    rows = []
    for m in meps:
        mep_id = m["id"].split("/")[1]
        name = f"{m['givenName']} {m['familyName']}"
        email = decode_email(mep_id)
        if not email:
            print(f"VARNING: ingen email hittad för {name} (id {mep_id})", file=sys.stderr)
            continue
        rows.append((name, email))
        time.sleep(0.3)

    ok, fail = sync(rows)
    print(f"Klart. {ok} synkade, {fail} misslyckades.")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
