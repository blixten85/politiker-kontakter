#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synkar resultat/Alla_kommuner_och_regioner.txt till D1-tabellen `politicians`
i politiker-webapp-projektet. Körs som ett extra steg efter en skrapnings-
körning (inte en del av scraper.py självt — håller scraper-logiken oberörd).

D1:s HTTP-API stödjer inte parametrar tillsammans med flera statements i
samma anrop (verifierat 2026-06-22) — varje upsert skickas därför som ett
eget POST, parallelliserat med en liten trådpool för rimlig hastighet.

Miljövariabler som krävs:
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER   (token med D1 Write — se politiker-webapp/infra)
  D1_DATABASE_UUID                 (politiker_webapp-databasens uuid)
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

RESULTAT_FIL = os.environ.get(
    "RESULTAT_FIL",
    os.path.join(os.path.dirname(__file__), "..", "resultat", "Alla_kommuner_och_regioner.txt"),
)
MAX_WORKERS = 10

UPSERT_SQL = (
    "INSERT INTO politicians (id, name, email, area_name, area_type, party, role, last_scraped_at) "
    "VALUES (lower(hex(randomblob(11))), ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(email, area_name) DO UPDATE SET name = excluded.name, party = excluded.party, role = excluded.role, last_scraped_at = excluded.last_scraped_at"
)

# Rad-format från scraper.py: "Namn <email> (PARTI) [Roll]" — parti och
# roll är båda valfria suffix och utelämnas helt om okända.
LINE_RE = re.compile(
    r"^(?:(?P<name>.+?)\s+<(?P<email_named>[^>]+)>|(?P<email_bare>\S+?@\S+?))"
    r"(?:\s*\((?P<party>[^)]+)\))?(?:\s*\[(?P<role>[^\]]+)\])?$"
)


def area_type_for(area_name: str) -> str:
    if area_name.startswith("Region "):
        return "region"
    if area_name in ("Sveriges riksdag", "Riksdagen"):
        return "riksdag"
    if "departementet" in area_name.lower() or "regeringskansliet" in area_name.lower() or area_name == "Regeringen":
        return "regering"
    return "kommun"


def parse_file(path: str):
    """Returnerar lista av (name, email, area_name, area_type, party, role)."""
    rows = []
    current_area = None
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current_area = line[3:].strip()
                continue
            if current_area is None:
                continue
            m = LINE_RE.match(line)
            if not m:
                continue
            email = m.group("email_named") or m.group("email_bare")
            name = (m.group("name") or "").strip()
            party = (m.group("party") or "").strip() or None
            role = (m.group("role") or "").strip() or None
            rows.append((name, email.lower(), current_area, area_type_for(current_area), party, role))
    return rows


def upsert_row(session: requests.Session, url: str, row) -> tuple[bool, str]:
    name, email, area_name, area_type, party, role = row
    payload = {"sql": UPSERT_SQL, "params": [name, email, area_name, area_type, party, role, int(time.time() * 1000)]}
    resp = session.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        return False, f"{email}: HTTP {resp.status_code}"
    data = resp.json()
    if not data.get("success"):
        return False, f"{email}: {data.get('errors')}"
    return True, email


def sync(rows) -> int:
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    ok_count = 0
    fail_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(upsert_row, session, url, row): row for row in rows}
        for i, future in enumerate(as_completed(futures), 1):
            success, info = future.result()
            if success:
                ok_count += 1
            else:
                fail_count += 1
                print(f"FEL: {info}", file=sys.stderr)
            if i % 200 == 0:
                print(f"{i}/{len(rows)} klara ({ok_count} ok, {fail_count} fel)...")

    return ok_count, fail_count


def main():
    rows = parse_file(RESULTAT_FIL)
    if not rows:
        print(f"Inga rader hittades i {RESULTAT_FIL}", file=sys.stderr)
        sys.exit(1)
    print(f"Hittade {len(rows)} (namn, email, område)-rader. Synkar till D1...")
    ok_count, fail_count = sync(rows)
    print(f"Klart. {ok_count} synkade, {fail_count} misslyckades.")
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
