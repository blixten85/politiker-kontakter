#!/usr/bin/env python3
"""Exporterar politicians-tabellen ur politiker-webapps D1 till publicerbara filer.

Producerar (i data/):
  - politiker.csv   kanonisk, människoläsbar databas
  - politiker.json  samma data, för programmatisk användning
  - politiker.sql   INSERT-satser för direkt import till en ny D1 (setup.sh)

Läser konfiguration ur miljön:
  CLOUDFLARE_API_TOKEN   token med D1-läsrättigheter
  CLOUDFLARE_ACCOUNT_ID  Cloudflare-konto-id
  D1_DATABASE_ID         databasens uuid

Deterministisk ordning + endast stabila fält (inga tidsstämplar/verifierings-
status) så att diffarna blir meningsfulla och inte brusar vid varje körning.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import urllib.request

# Fält som publiceras (stabila — utelämnar last_scraped_at/verification_status).
FIELDS = ["name", "email", "area_name", "area_type", "party", "role"]
PAGE = 5000

API = "https://api.cloudflare.com/client/v4/accounts/{acct}/d1/database/{db}/query"


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"FEL: miljövariabeln {name} saknas")
    return val


def query(sql: str, token: str, url: str) -> list[dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps({"sql": sql}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if not body.get("success"):
        sys.exit(f"FEL: D1-fråga misslyckades: {body.get('errors')}")
    return body["result"][0]["results"]


def fetch_all(token: str, url: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    cols = ", ".join(FIELDS)
    while True:
        page = query(
            f"SELECT {cols} FROM politicians "
            f"ORDER BY area_type, area_name, name, email "
            f"LIMIT {PAGE} OFFSET {offset}",
            token,
            url,
        )
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return rows


def sqlesc(val) -> str:
    if val is None or val == "":
        return "NULL"
    return "'" + str(val).replace("'", "''") + "'"


def write_outputs(rows: list[dict], outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(outdir, "politiker.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(k) or "") for k in FIELDS})

    with open(os.path.join(outdir, "politiker.json"), "w", encoding="utf-8") as f:
        json.dump(
            [{k: r.get(k) for k in FIELDS} for r in rows],
            f, ensure_ascii=False, indent=2, sort_keys=False,
        )
        f.write("\n")

    # SQL: deterministiskt id (sha1 av email|area_name, matchar UNIQUE-nyckeln),
    # konstant last_scraped_at=0 så filen inte brusar. INSERT OR IGNORE för fork-import.
    cols = "id, name, email, area_name, area_type, party, role, last_scraped_at, verification_status"
    with open(os.path.join(outdir, "politiker.sql"), "w", encoding="utf-8") as f:
        f.write("-- Genererad av export/export_d1.py — importera till ny D1 efter schema.sql.\n")
        f.write("-- wrangler d1 execute <db> --remote --file data/politiker.sql\n")
        for r in rows:
            rid = hashlib.sha1(f"{r['email']}|{r['area_name']}".encode()).hexdigest()
            vals = ", ".join([
                sqlesc(rid), sqlesc(r["name"]), sqlesc(r["email"]),
                sqlesc(r["area_name"]), sqlesc(r["area_type"]),
                sqlesc(r.get("party")), sqlesc(r.get("role")),
                "0", "'unknown'",
            ])
            f.write(f"INSERT OR IGNORE INTO politicians ({cols}) VALUES ({vals});\n")


def main() -> None:
    token = _require("CLOUDFLARE_API_TOKEN")
    url = API.format(acct=_require("CLOUDFLARE_ACCOUNT_ID"), db=_require("D1_DATABASE_ID"))
    outdir = os.path.join(os.path.dirname(__file__), "..", "data")
    rows = fetch_all(token, url)
    write_outputs(rows, outdir)
    print(f"Skrev {len(rows)} politiker till data/ (csv, json, sql)")


if __name__ == "__main__":
    main()
