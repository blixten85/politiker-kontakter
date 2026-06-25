#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bakåtfyller parti+befattning för REDAN skrapade kommun-/regionpolitiker i
D1-tabellen `politicians`, för troman- och netpublicator-kommunerna
(~192 av 273, se REGIONER i scraper.py) — UTAN att köra om hela
Playwright/Docker-skraparen. Dessa sidor är server-renderade rent HTML
(verifierat manuellt), så vanliga `requests`-anrop räcker, samma extraktions-
logik som i scraper.py men portad från Playwright till requests+regex.

Matchar mot politicians via (email, area_name) — den befintliga unika
nyckeln — så bara raden uppdateras, inga nya rader skapas och ingen
omdistribuerad email-gissning behövs.

mailto-kommunerna (resterande ~64) hoppas över här: deras data sitter
direkt i sidans HTML-text utan en gemensam tabellstruktur (varierar mer
sida till sida), så det är inte lika mekaniskt att portera — får vänta
till nästa riktiga skrapning.

Miljövariabler som krävs (samma .env som sync_to_d1.py):
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER
  D1_DATABASE_UUID
"""

import html
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests


def extract_h1_text(page_html: str) -> str | None:
    """Hämtar h1:ens textinnehåll, även om partiet ligger i en nästlad
    <a>-tagg (t.ex. 'Namn (<a href="...">S</a>)') — tar bort alla taggar
    inuti och avkodar HTML-entiteter."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.S)
    if not m:
        return None
    text = re.sub(r"<[^>]+>", "", m.group(1))
    return html.unescape(re.sub(r"\s+", " ", text)).strip()

def load_regioner() -> list[dict]:
    """Plockar REGIONER-listan direkt ur scraper.py:s källkod, utan att
    importera modulen (den kräver playwright, ett tungt beroende som inte
    behövs här eftersom troman/netpublicator är vanlig server-renderad
    HTML)."""
    path = os.path.join(os.path.dirname(__file__), "scraper.py")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    start = content.index("REGIONER = [")
    end = content.index("\n]", start) + 2
    ns: dict = {}
    exec(content[start:end], ns)  # noqa: S102 — trusted lokal fil, ingen extern indata
    return ns["REGIONER"]

PARTY_FULLNAME_TO_ABBR = {
    "socialdemokraterna": "S", "moderaterna": "M", "moderata samlingspartiet": "M",
    "sverigedemokraterna": "SD", "vänsterpartiet": "V", "centerpartiet": "C",
    "liberalerna": "L", "kristdemokraterna": "KD", "miljöpartiet": "MP",
    "miljöpartiet de gröna": "MP", "feministiskt initiativ": "FI",
}


def normalize_party(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    return PARTY_FULLNAME_TO_ABBR.get(raw.lower(), raw) or None


def party_from_parens(text: str) -> str | None:
    m = re.search(r"\(([^)]{1,20})\)\s*$", text.strip())
    return normalize_party(m.group(1)) if m else None


def fetch(url: str, timeout: int = 30) -> str | None:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as err:
        print(f"  FEL vid hämtning {url}: {err}", file=sys.stderr, flush=True)
        return None


def email_from_mailto(href: str) -> str | None:
    if not href.startswith("mailto:"):
        return None
    return href[len("mailto:"):].split("?")[0].strip().lower()


def troman_rows(org_url: str) -> list[tuple[str, str, str | None, str | None]]:
    """Returnerar [(namn, email, parti, roll), ...] för en troman-kommun."""
    org_html = fetch(org_url)
    if not org_html:
        return []
    person_urls = sorted(set(re.findall(r'href="(/person/[a-f0-9-]+)"', org_html)))
    base = re.match(r"(https?://[^/]+)", org_url).group(1)

    rows = []
    for path in person_urls:
        purl = urljoin(base, path)
        phtml = fetch(purl, timeout=20)
        if not phtml:
            continue
        text = extract_h1_text(phtml)
        name, party = "", None
        if text:
            party = party_from_parens(text)
            name = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()

        role = None
        table_match = re.search(r'id="engagementTable:tbody_element"(.*?)</table>', phtml, re.S)
        if table_match:
            all_rows = []
            for row_match in re.finditer(r"<tr>(.*?)</tr>", table_match.group(1), re.S):
                tds = re.findall(r"<td>(.*?)</td>", row_match.group(1), re.S)
                if len(tds) < 2:
                    continue
                org_text = html.unescape(re.sub(r"<[^>]+>", "", tds[0])).strip()
                role_text = html.unescape(re.sub(r"<[^>]+>", "", tds[1])).strip()
                all_rows.append((org_text, role_text))
                if "fullmäktige" in org_text.lower():
                    role = role_text
                    break
            if role is None and all_rows:
                role = all_rows[0][1]

        for href in re.findall(r'href="(mailto:[^"]+)"', phtml):
            email = email_from_mailto(href)
            if email:
                rows.append((name, email, party, role or None))
        time.sleep(0.2)
    return rows


def netpublicator_rows(registry_id: str, board_id: str) -> list[tuple[str, str, str | None, str | None]]:
    board_url = f"https://www.netpublicator.com/elected/registry/{registry_id}/board/{board_id}"
    board_html = fetch(board_url)
    if not board_html:
        return []

    info_by_url: dict[str, tuple[str | None, str | None]] = {}
    for row_match in re.finditer(r"<tr>(.*?)</tr>", board_html, re.S):
        row = row_match.group(1)
        link_match = re.search(r'href="([^"]*?/politician/[^"]+)"', row)
        if not link_match:
            continue
        purl = urljoin("https://www.netpublicator.com", html.unescape(link_match.group(1)))
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)

        # Rollcellen är ett vanligt textfält utan nästlad länk (till skillnad
        # från förnamn/efternamn/parti-cellerna, som alla har <a>-taggar) —
        # robustare än ett fast kolumnindex som varierar mellan kommuner.
        # Vissa kommuner (t.ex. Ekerö) har EN extra platsnummer-kolumn
        # ("<td data-type=\"text\">12</td>") som också saknar <a>-tagg —
        # hoppa över rent numeriska celler, en roll är aldrig bara siffror.
        role = None
        for td in tds:
            if "<a" in td:
                continue
            text = html.unescape(re.sub(r"<[^>]+>", "", td)).strip()
            if text and not text.isdigit():
                role = text
                break

        party = None
        title_match = re.search(r'<img[^>]*title="([^"]+)"', row)
        if title_match:
            party = normalize_party(html.unescape(title_match.group(1)))
        info_by_url[purl] = (role, party)

    rows = []
    for purl, (role, party) in info_by_url.items():
        phtml = fetch(purl, timeout=20)
        if not phtml:
            continue
        text = extract_h1_text(phtml)
        name, party_from_page = "", None
        if text:
            party_from_page = party_from_parens(text)
            name = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
        for href in re.findall(r'href="(mailto:[^"]+)"', phtml):
            email = email_from_mailto(href)
            if email:
                rows.append((name, email, party or party_from_page, role))
        time.sleep(0.2)
    return rows


def main():
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"]
    db_uuid = os.environ["D1_DATABASE_UUID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    targets = [r for r in load_regioner() if r["typ"] in ("troman", "netpublicator")]
    print(f"{len(targets)} troman/netpublicator-kommuner/regioner att bearbeta.", flush=True)

    now_ms = int(time.time() * 1000)
    total_ok = total_fail = total_skip = 0
    for i, region in enumerate(targets, 1):
        namn = region["namn"]
        print(f"[{i}/{len(targets)}] {namn} ({region['typ']})...", flush=True)
        try:
            if region["typ"] == "troman":
                rows = troman_rows(region["url"])
            else:
                rows = netpublicator_rows(region["netpub_registry"], region["netpub_board"])
        except Exception as err:  # en kommuns strukturavvikelse ska inte stoppa hela körningen
            print(f"  FEL (oväntat) för {namn}: {err}", file=sys.stderr, flush=True)
            continue

        ok = fail = skip = 0
        for name, email, party, role in rows:
            if not party and not role:
                skip += 1
                continue
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "sql": "UPDATE politicians SET party = COALESCE(?, party), role = COALESCE(?, role), last_scraped_at = ? WHERE area_name = ? AND email = ?",
                    "params": [party, role, now_ms, namn, email],
                },
                timeout=30,
            )
            if resp.status_code == 200 and resp.json().get("success"):
                ok += 1
            else:
                fail += 1
        print(f"  {len(rows)} personer, {ok} uppdaterade, {fail} fel, {skip} utan parti/roll", flush=True)
        total_ok += ok
        total_fail += fail
        total_skip += skip

    print(f"\nKlart. Totalt {total_ok} uppdaterade, {total_fail} fel, {total_skip} utan parti/roll.", flush=True)


if __name__ == "__main__":
    main()
