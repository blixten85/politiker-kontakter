#!/usr/bin/env python3
"""Genererar VCF-kontaktkort (för import i mobilen) ur den publicerade datan.

Läser data/politiker.csv lokalt — ingen belastning på politiker.denied.se eller
D1. Filtrera på område/typ så du bara får de kontakter du vill ha, och importera
.vcf-filen direkt i telefonens kontakter.

Exempel:
  python3 export/to_vcf.py                          # alla, en samlad fil
  python3 export/to_vcf.py --area "Lysekils kommun" # bara en kommun
  python3 export/to_vcf.py --type riksdag           # bara riksdagen
  python3 export/to_vcf.py --per-area --out vcf/    # en fil per område
"""
from __future__ import annotations

import argparse
import csv
import os
import re


def _esc(val: str) -> str:
    # vCard-escaping: backslash, komma, semikolon, radbrytning.
    return (
        (val or "")
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def _vcard(row: dict) -> str:
    name = row.get("name") or row.get("email", "").split("@")[0]
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{_esc(name)}", f"N:;{_esc(name)};;;"]
    if row.get("email"):
        lines.append(f"EMAIL;TYPE=INTERNET:{row['email']}")
    if row.get("area_name"):
        lines.append(f"ORG:{_esc(row['area_name'])}")
    if row.get("role"):
        lines.append(f"TITLE:{_esc(row['role'])}")
    note = []
    if row.get("party"):
        note.append(f"Parti: {row['party']}")
    if row.get("area_type"):
        note.append(f"Nivå: {row['area_type']}")
    if note:
        lines.append(f"NOTE:{_esc(' | '.join(note))}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "kontakter"


def main() -> None:
    here = os.path.dirname(__file__)
    ap = argparse.ArgumentParser(description="Generera VCF ur data/politiker.csv")
    ap.add_argument("--csv", default=os.path.join(here, "..", "data", "politiker.csv"))
    ap.add_argument("--area", help="filtrera på exakt area_name (t.ex. 'Lysekils kommun')")
    ap.add_argument("--type", dest="atype", help="filtrera på area_type (eu|riksdag|regering|region|kommun)")
    ap.add_argument("--per-area", action="store_true", help="en .vcf-fil per område istället för en samlad")
    ap.add_argument("--out", default=os.path.join(here, "..", "vcf"), help="utkatalog (default: vcf/)")
    args = ap.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = [
            r for r in csv.DictReader(f)
            if (not args.area or r["area_name"] == args.area)
            and (not args.atype or r["area_type"] == args.atype)
        ]
    if not rows:
        raise SystemExit("Inga kontakter matchade filtret.")

    os.makedirs(args.out, exist_ok=True)
    if args.per_area:
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(r["area_name"], []).append(r)
        for area, grp in groups.items():
            path = os.path.join(args.out, f"{_safe(area)}.vcf")
            with open(path, "w", encoding="utf-8") as out:
                out.write("".join(_vcard(r) for r in grp))
        print(f"Skrev {len(groups)} filer ({len(rows)} kontakter) till {args.out}/")
    else:
        path = os.path.join(args.out, "kontakter.vcf")
        with open(path, "w", encoding="utf-8") as out:
            out.write("".join(_vcard(r) for r in rows))
        print(f"Skrev {len(rows)} kontakter till {path}")


if __name__ == "__main__":
    main()
