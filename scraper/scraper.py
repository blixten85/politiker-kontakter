#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Politiker-kontakter scraper
Hämtar e-postadresser till förtroendevalda i svenska regioner.
Stöd för Netpublicator-baserade register (används av många regioner)
samt direktskrapning av mailto-länkar.
Sparar resultat som VCF-filer (en per region + en samlad).
"""

import asyncio
import logging
import os
import re
import sys
from playwright.async_api import async_playwright, Error as PlaywrightError

LOG_DIR  = os.environ.get("LOG_DIR",    "/logs")
OUT_DIR  = os.environ.get("OUTPUT_DIR", "/output")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUT_DIR,  exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
NETPUB_RE = re.compile(r"https://www\.netpublicator\.com/elected/registry/[^\"'\s]+")

# Skräpadresser att filtrera bort
SKIP_KEYWORDS = ["noreply", "no-reply", "webmaster", "webb@", "support@", "info@region", "hjalp@"]

# === Regionkonfiguration ===
# typ "netpublicator" = använd Netpublicator-logik (hämta profilsidor)
# typ "mailto"        = skrapa mailto-länkar direkt från sidan
# netpub_registry     = URL till Netpublicator-startsidan för regionen
# netpub_board        = UUID för Regionfullmäktige-nämnden
# url                 = direktlänk (för typ "mailto")

REGIONER = [
    {
        "namn": "Region Dalarna",
        "typ": "netpublicator",
        "netpub_registry": "5f0adfedbde841d188c336a5df571458",
        "netpub_board":    "94068ad4-69a6-4afa-bf74-af9b742e655f",
    },
    {
        "namn": "Region Stockholm",
        "typ": "mailto",
        "url": "https://www.regionstockholm.se/om-oss/organisation/regionstyrelsen-och-namnder/regionfullmaktige/ledamoter/",
    },
    {
        "namn": "Region Uppsala",
        "typ": "mailto",
        "url": "https://www.regionuppsala.se/om-regionen/organisation/regionfullmaktige/ledamoter-i-regionfullmaktige/",
    },
    {
        "namn": "Region Sörmland",
        "typ": "mailto",
        "url": "https://regionsormland.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Östergötland",
        "typ": "mailto",
        "url": "https://www.regionostergotland.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Jönköpings län",
        "typ": "mailto",
        "url": "https://www.rjl.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Kronoberg",
        "typ": "mailto",
        "url": "https://www.kronoberg.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Kalmar län",
        "typ": "mailto",
        "url": "https://www.regionkalmar.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Blekinge",
        "typ": "mailto",
        "url": "https://www.regionblekinge.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Skåne",
        "typ": "mailto",
        "url": "https://www.skane.se/om-region-skane/organisation-och-styrning/regionfullmaktige/",
    },
    {
        "namn": "Region Halland",
        "typ": "mailto",
        "url": "https://www.regionhalland.se/om-region-halland/organisation/regionfullmaktige/",
    },
    {
        "namn": "Västra Götalandsregionen",
        "typ": "mailto",
        "url": "https://www.vgregion.se/om-vgr/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Värmland",
        "typ": "mailto",
        "url": "https://www.regionvarmland.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Örebro län",
        "typ": "mailto",
        "url": "https://www.regionorebrolan.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Västmanland",
        "typ": "mailto",
        "url": "https://www.regionvastmanland.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Gävleborg",
        "typ": "mailto",
        "url": "https://www.regiongavleborg.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Västernorrland",
        "typ": "mailto",
        "url": "https://www.rvn.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Jämtland Härjedalen",
        "typ": "mailto",
        "url": "https://www.regionjh.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Västerbotten",
        "typ": "mailto",
        "url": "https://www.regionvasterbotten.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Norrbotten",
        "typ": "mailto",
        "url": "https://www.norrbotten.se/om-regionen/organisation/regionfullmaktige/",
    },
    {
        "namn": "Region Gotland",
        "typ": "mailto",
        "url": "https://www.gotland.se/om-kommunen/organisation/kommunfullmaktige/",
    },
]


def is_valid_email(email: str) -> bool:
    email = email.lower()
    if not EMAIL_RE.fullmatch(email):
        return False
    return not any(kw in email for kw in SKIP_KEYWORDS)


async def accept_cookies(page):
    for text in ["Acceptera alla", "Acceptera", "Jag förstår", "Accept all", "Accept", "Godkänn"]:
        try:
            btn = await page.query_selector(f"button:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1)
                return
        except PlaywrightError:
            pass


async def scrape_netpublicator(context, namn, registry_id, board_id):
    """Hämtar ledamöternas profilsidor från Netpublicator och plockar e-post."""
    emails = set()
    board_url = (
        f"https://www.netpublicator.com/elected/registry/{registry_id}"
        f"/board/{board_id}"
    )
    page = await context.new_page()
    try:
        log.info(f"{namn}: hämtar ledamötslista {board_url}")
        await page.goto(board_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Plocka alla politiker-URL:er från sidan
        hrefs = await page.eval_on_selector_all(
            "a[href*='/politician/']",
            "els => els.map(e => e.href)"
        )
        politician_urls = list(set(hrefs))
        log.info(f"{namn}: {len(politician_urls)} profilsidor hittade")

        for url in politician_urls:
            p2 = await context.new_page()
            try:
                await p2.goto(url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(0.5)
                mailto_hrefs = await p2.eval_on_selector_all(
                    "a[href^='mailto:']",
                    "els => els.map(e => e.href)"
                )
                for href in mailto_hrefs:
                    email = href.replace("mailto:", "").split("?")[0].strip().lower()
                    if is_valid_email(email):
                        emails.add(email)
            except PlaywrightError:
                pass
            finally:
                await p2.close()
            await asyncio.sleep(0.3)

    except PlaywrightError as e:
        log.error(f"{namn}: {e}")
    finally:
        await page.close()

    log.info(f"{namn}: {len(emails)} adresser funna")
    return emails


async def scrape_mailto(context, namn, url):
    """Skrapar mailto-länkar direkt från en sida (fallback för övriga regioner)."""
    emails = set()
    page = await context.new_page()
    try:
        log.info(f"{namn}: hämtar {url}")
        await page.goto(url, timeout=60000, wait_until="networkidle")
        await asyncio.sleep(2)
        await accept_cookies(page)
        await asyncio.sleep(1)

        hrefs = await page.eval_on_selector_all(
            "a[href^='mailto:']",
            "els => els.map(e => e.href)"
        )
        for href in hrefs:
            email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if is_valid_email(email):
                emails.add(email)

        # Fallback: regex på sidans HTML
        if len(emails) < 3:
            content = await page.content()
            for email in EMAIL_RE.findall(content):
                if is_valid_email(email.lower()):
                    emails.add(email.lower())

    except PlaywrightError as e:
        log.error(f"{namn}: {e}")
    finally:
        await page.close()

    log.info(f"{namn}: {len(emails)} adresser funna")
    return emails


def spara_vcf(namn, emails, path):
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{namn}",
        "N:;;;;",
        f"ORG:{namn}",
    ]
    for email in sorted(emails):
        lines.append(f"EMAIL;TYPE=WORK:{email}")
    lines.append("END:VCARD")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info(f"Sparad: {path}")


async def main():
    alla_emails = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-http2"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
        )

        for region in REGIONER:
            namn = region["namn"]
            if region["typ"] == "netpublicator":
                emails = await scrape_netpublicator(
                    context, namn,
                    region["netpub_registry"],
                    region["netpub_board"],
                )
            else:
                emails = await scrape_mailto(context, namn, region["url"])

            if emails:
                alla_emails[namn] = emails
                safe = namn.replace(" ", "_").replace("/", "-")
                spara_vcf(namn, emails, f"{OUT_DIR}/{safe}.vcf")

            await asyncio.sleep(2)

        await context.close()
        await browser.close()

    # Samlad VCF
    alla = set()
    for e in alla_emails.values():
        alla.update(e)

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "FN:Alla regioner",
        "N:;;;;",
        "ORG:Sveriges Regioner",
    ]
    for email in sorted(alla):
        lines.append(f"EMAIL;TYPE=WORK:{email}")
    lines.append("END:VCARD")

    with open(f"{OUT_DIR}/Alla_regioner.vcf", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info(f"Klar. {len(alla)} unika adresser från {len(alla_emails)} regioner.")


if __name__ == "__main__":
    asyncio.run(main())
