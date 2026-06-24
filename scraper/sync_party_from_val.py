#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fyller i partibeteckning för redan skrapade kommun- och regionpolitiker i
D1-tabellen `politicians`, genom att matcha namn mot Valmyndighetens öppna
data över nuvarande ledamöter (kommun-/regionfullmäktige).

Valmyndighetens data har INGEN mailadress (det är valresultatdata, inte
kontaktinformation) — den kan därför aldrig ersätta kommun-skrapningen,
bara komplettera den med parti. Matchning sker på exakt namn inom samma
kommun/region; om inget exakt namnmatch hittas lämnas raden orörd (ingen
gissning).

Källa: https://resultat.val.se/filer/val2022/info/nuvarande_ledamoter.csv
(uppdateras dagligen av Valmyndigheten trots filnamnet "val2022" — fångar
ersättare/fyllnadsval sedan valet).

OBS: filen använder gamla Mac-radslut (bara \\r, inget \\n) — vanlig
\\n-baserad radläsning ger en enda jättelång rad. Dela på \\r explicit.

Miljövariabler som krävs (samma .env som sync_to_d1.py):
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER
  D1_DATABASE_UUID
"""

import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

VAL_CSV_URL = "https://resultat.val.se/filer/val2022/info/nuvarande_ledamoter.csv"
MAX_WORKERS = 10


def fetch_val_rows() -> list[list[str]]:
    resp = requests.get(VAL_CSV_URL, timeout=60)
    resp.raise_for_status()
    content = resp.content.decode("utf-8-sig")
    lines = content.split("\r")
    reader = csv.reader(lines, delimiter=";")
    rows = [row for row in reader if row and row[0] in ("KF", "RF")]
    return rows


def build_party_lookup(rows: list[list[str]]) -> dict[tuple[str, str], str]:
    """Returnerar {(area_name, "Förnamn Efternamn"): partiförkortning} —
    exakt namn, för förstahandsmatchning."""
    lookup: dict[tuple[str, str], str] = {}
    for row in rows:
        valtyp, _val_till, _lanskod, _lan, _kommunkod, kommun, *_rest = row
        parti = row[8]
        fornamn = row[11]
        efternamn = row[12]
        full_name = f"{fornamn} {efternamn}"

        if valtyp == "KF":
            area_name = f"{kommun} kommun"
        else:  # RF — extrahera "Region X" ur "Regionfullmäktige i Region X"
            val_till = row[1]
            if " i " in val_till:
                area_name = val_till.split(" i ", 1)[1]
            else:
                continue

        lookup[(area_name, full_name)] = parti
    return lookup


def name_words(name: str) -> set[str]:
    """Normaliserar ett namn till en mängd ord — bindestreck behandlas som
    mellanslag (\"Sundvall-Bergström\" -> {\"sundvall\", \"bergström\"}) så
    att bindestreck/mellanslags-skillnader mellan källorna inte stoppar en
    match."""
    return set(name.replace("-", " ").lower().split())


def build_fuzzy_index(rows: list[list[str]]) -> dict[str, list[tuple[frozenset[str], str]]]:
    """Returnerar {area_name: [(alla_namnord_som_mängd, parti), ...]} för
    andrahandsmatchning. Anledningar till att exakt namnmatch missar:
    1) Valmyndigheten har ofta fler förnamn än kommunens egna sida visar
       (\"Andrea Birgitta Möllerberg\" vs \"Andrea Möllerberg\").
    2) Tilltalsnamnet är inte alltid det FÖRSTA förnamnet — en person med
       flera förnamn kan gå under det andra/tredje.
    3) Sammansatta efternamn kan visas med bara EN av delarna på kommunens
       sida (\"Nybacka\" för \"Nybacka Onshagen\", \"Santangelo\" för
       \"Santangelo Gonzalez\") — vi vet inte vilken del.
    4) Bindestreck vs mellanslag (\"Sundvall-Bergström\" vs
       \"Sundvall Bergström\").
    Lösning: jämför som ordmängder. Match om det skrapade namnets ord är
    en delmängd av Valmyndighetens namnord, inom samma område."""
    index: dict[str, list[tuple[frozenset[str], str]]] = {}
    for row in rows:
        valtyp, val_till, _lanskod, _lan, _kommunkod, kommun, *_rest = row
        parti = row[8]
        words = name_words(f"{row[11]} {row[12]}")

        if valtyp == "KF":
            area_name = f"{kommun} kommun"
        else:
            area_name = val_till.split(" i ", 1)[1] if " i " in val_till else None
        if not area_name or not words:
            continue
        index.setdefault(area_name, []).append((frozenset(words), parti))
    return index


def fuzzy_match(name: str, area_name: str, fuzzy_index: dict[str, list[tuple[frozenset[str], str]]]) -> str | None:
    scraped_words = name_words(name)
    if len(scraped_words) < 2:
        return None
    candidates = [parti for val_words, parti in fuzzy_index.get(area_name, []) if scraped_words <= val_words]
    # Bara ett otvetydigt resultat räknas som match — om flera olika
    # partier matchar (olika personer med överlappande namnord inom
    # samma område) gissar vi inte.
    if len(set(candidates)) == 1:
        return candidates[0]
    return None


def main():
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    print("Hämtar Valmyndighetens ledamotsdata...", flush=True)
    rows = fetch_val_rows()
    print(f"{len(rows)} KF/RF-rader hämtade.", flush=True)
    lookup = build_party_lookup(rows)
    print(f"{len(lookup)} unika (område, namn)-par i uppslagstabellen.", flush=True)

    print("Hämtar befintliga kommun-/regionpolitiker från D1...", flush=True)
    resp = session.post(
        url,
        json={"sql": "SELECT id, name, area_name FROM politicians WHERE area_type IN ('kommun', 'region')"},
        timeout=60,
    )
    existing = resp.json()["result"][0]["results"]
    print(f"{len(existing)} befintliga rader att matcha mot.", flush=True)

    fuzzy_index = build_fuzzy_index(rows)

    now_ms = int(time.time() * 1000)
    to_update: list[tuple[str, str, str]] = []
    exact_count = fuzzy_count = 0
    for p in existing:
        exact = lookup.get((p["area_name"], p["name"]))
        if exact:
            to_update.append((p["id"], p["name"], exact))
            exact_count += 1
            continue
        fuzzy = fuzzy_match(p["name"], p["area_name"], fuzzy_index)
        if fuzzy:
            to_update.append((p["id"], p["name"], fuzzy))
            fuzzy_count += 1

    unmatched = len(existing) - len(to_update)
    print(f"{exact_count} exakta + {fuzzy_count} fuzzy-matchade ({len(to_update)} totalt), {unmatched} utan match (lämnas orörda).", flush=True)

    def update_one(item: tuple[str, str, str]) -> tuple[bool, str]:
        politician_id, name, party = item
        resp = session.post(
            url,
            json={"sql": "UPDATE politicians SET party = ?, last_scraped_at = ? WHERE id = ?", "params": [party, now_ms, politician_id]},
            timeout=30,
        )
        if resp.status_code == 200 and resp.json().get("success"):
            return True, name
        return False, f"{name}: {resp.text}"

    matched = fail = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(update_one, item): item for item in to_update}
        for i, future in enumerate(as_completed(futures), 1):
            ok, info = future.result()
            if ok:
                matched += 1
            else:
                fail += 1
                print(f"FEL: {info}", file=sys.stderr, flush=True)
            if i % 1000 == 0:
                print(f"{i}/{len(to_update)} klara ({matched} ok, {fail} fel)...", flush=True)

    print(f"Klart. {matched} matchade och uppdaterade, {unmatched} utan exakt namnmatch (lämnade orörda), {fail} fel.", flush=True)
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
