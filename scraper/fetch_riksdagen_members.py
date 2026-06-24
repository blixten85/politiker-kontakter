#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hämtar Sveriges riksdags 349 nuvarande ledamöter via riksdagens öppna API
(data.riksdagen.se) och synkar till D1-tabellen `politicians`
(area_type='riksdag', area_name='Sveriges riksdag', party ifylld).

VIKTIGT om rdlstatus-parametern: tomt/utelämnat värde ger BARA nuvarande
ledamöter (349 st). rdlstatus=tjanst ger alla ledamöter/ersättare sedan
2018 (651+ st) — märkbart tyngre svar (varje persons fulla uppdragshistorik
inkluderas) som dessutom riskerar att serverns anslutning bryts mitt i
svaret. Använd ALDRIG rdlstatus=tjanst för den här synkens syfte.

E-postadresser anges i formatet "namn[på]riksdagen.se" — byt bara ut
"[på]" mot "@".

Miljövariabler som krävs (samma .env som sync_to_d1.py):
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER
  D1_DATABASE_UUID
"""

import os
import sys
import time

import requests

RIKSDAGEN_API = "https://data.riksdagen.se/personlista/?utformat=json"
AREA_NAME = "Sveriges riksdag"

UPSERT_SQL = (
    "INSERT INTO politicians (id, name, email, area_name, area_type, party, last_scraped_at) "
    "VALUES (lower(hex(randomblob(11))), ?, ?, ?, 'riksdag', ?, ?) "
    "ON CONFLICT(email, area_name) DO UPDATE SET name = excluded.name, party = excluded.party, last_scraped_at = excluded.last_scraped_at"
)


def fetch_current_members() -> list[dict]:
    # data.riksdagen.se nollställer ibland anslutningen mitt i svaret även
    # för denna lilla, korrekta fråga (oberoende av vår sida — servern
    # verkar helt enkelt instabil under belastning). Försök några gånger
    # innan vi ger upp.
    last_err = None
    for attempt in range(5):
        try:
            resp = requests.get(RIKSDAGEN_API, timeout=120)
            resp.raise_for_status()
            return resp.json()["personlista"]["person"]
        except requests.exceptions.RequestException as err:
            last_err = err
            print(f"Försök {attempt + 1}/5 misslyckades ({err}), försöker igen...", file=sys.stderr, flush=True)
            time.sleep(5)
    raise last_err


def extract_email(person: dict) -> str | None:
    for u in person.get("personuppgift", {}).get("uppgift", []):
        if u.get("kod") == "Officiell e-postadress":
            raw = u["uppgift"][0] if u.get("uppgift") else None
            if raw:
                return raw.replace("[på]", "@")
    return None


def main():
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    people = fetch_current_members()
    print(f"Hittade {len(people)} nuvarande riksdagsledamöter.", flush=True)

    now_ms = int(time.time() * 1000)
    ok = fail = skipped = 0
    for i, p in enumerate(people, 1):
        name = f"{p['tilltalsnamn']} {p['efternamn']}"
        party = p.get("parti") or None
        email = extract_email(p)
        if not email:
            print(f"VARNING: ingen email hittad för {name}", file=sys.stderr, flush=True)
            skipped += 1
            continue

        resp = session.post(url, json={"sql": UPSERT_SQL, "params": [name, email, AREA_NAME, party, now_ms]}, timeout=30)
        if resp.status_code == 200 and resp.json().get("success"):
            ok += 1
        else:
            fail += 1
            print(f"FEL: {name} <{email}>: {resp.text}", file=sys.stderr, flush=True)

        if i % 50 == 0:
            print(f"{i}/{len(people)} klara ({ok} ok, {fail} fel, {skipped} utan email)...", flush=True)

    print(f"Klart. {ok} synkade, {fail} misslyckades, {skipped} utan email.", flush=True)
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
