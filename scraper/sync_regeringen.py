#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synkar regeringens 11 departement (registratorsadresser) till D1-tabellen
`politicians` (area_type='regering').

Det finns medvetet INGA personliga mailadresser till enskilda statsråd —
all formell kontakt med regeringen sker via departementets registrator
(bekräftat på regeringen.se/kontaktuppgifter/). Varje rad representerar
därför ett departement, inte en enskild person.

Källa: ~/Regeringen.txt (en registratorsadress per rad, redan skrapad
tidigare i projektet).
"""

import os
import time

import requests

DEPARTMENT_NAMES = {
    "arbetsmarknadsdepartementet": "Arbetsmarknadsdepartementet",
    "finansdepartementet": "Finansdepartementet",
    "forsvarsdepartementet": "Försvarsdepartementet",
    "justitiedepartementet": "Justitiedepartementet",
    "klimat-naringslivsdepartementet": "Klimat- och näringslivsdepartementet",
    "kulturdepartementet": "Kulturdepartementet",
    "landsbygds-infrastrukturdepartementet": "Landsbygds- och infrastrukturdepartementet",
    "socialdepartementet": "Socialdepartementet",
    "statsradsberedningen": "Statsrådsberedningen",
    "utbildningsdepartementet": "Utbildningsdepartementet",
    "utrikesdepartementet": "Utrikesdepartementet",
}

UPSERT_SQL = (
    "INSERT INTO politicians (id, name, email, area_name, area_type, last_scraped_at) "
    "VALUES (lower(hex(randomblob(11))), ?, ?, ?, 'regering', ?) "
    "ON CONFLICT(email, area_name) DO UPDATE SET name = excluded.name, last_scraped_at = excluded.last_scraped_at"
)


def main():
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    path = os.path.join(os.path.dirname(__file__), "..", "..", "Regeringen.txt")
    path = os.path.expanduser("~/Regeringen.txt") if not os.path.exists(path) else path
    with open(path, encoding="utf-8") as f:
        emails = [line.strip() for line in f if line.strip()]

    now_ms = int(time.time() * 1000)
    ok = fail = 0
    for email in emails:
        prefix = email.split(".registrator@")[0]
        name = DEPARTMENT_NAMES.get(prefix, prefix.capitalize())
        resp = session.post(url, json={"sql": UPSERT_SQL, "params": [name, email, name, now_ms]}, timeout=30)
        if resp.status_code == 200 and resp.json().get("success"):
            ok += 1
            print(f"OK: {name} <{email}>")
        else:
            fail += 1
            print(f"FEL: {name} <{email}>: {resp.text}")

    print(f"Klart. {ok} synkade, {fail} misslyckades.")


if __name__ == "__main__":
    main()
