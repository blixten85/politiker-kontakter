#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Politiker-kontakter scraper
Hämtar e-postadresser till förtroendevalda i svenska regioner och kommuner.
Sparar resultat som VCF-filer (en per region/kommun + en samlad).
"""

import asyncio
import logging
import os
import re
import sys
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Error as PlaywrightError

LOG_DIR = "/logs"
OUTPUT_DIR = "/output"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# === Regionernas kontaktsidor ===
# Varje post: (namn, url, email_selector_strategi)
# Strategi: "href" = plocka mailto:-länkar, "text" = regex på sidan
REGIONER = [
    ("Region Stockholm",         "https://www.regionstockholm.se/om-oss/organisation/regionstyrelsen-och-namnder/regionfullmaktige/ledamoter/", "href"),
    ("Region Uppsala",           "https://www.regionuppsala.se/om-regionen/organisation/regionfullmaktige/ledamoter-i-regionfullmaktige/", "href"),
    ("Region Sörmland",          "https://regionsormland.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Östergötland",      "https://www.regionostergotland.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Jönköpings län",    "https://www.rjl.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Kronoberg",         "https://www.kronoberg.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Kalmar län",        "https://www.regionkalmar.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Blekinge",          "https://www.regionblekinge.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Skåne",             "https://www.skane.se/om-region-skane/organisation-och-styrning/regionfullmaktige/", "href"),
    ("Region Halland",           "https://www.regionhalland.se/om-region-halland/organisation/regionfullmaktige/", "href"),
    ("Västra Götalandsregionen", "https://www.vgregion.se/om-vgr/organisation/regionfullmaktige/", "href"),
    ("Region Värmland",          "https://www.regionvarmland.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Örebro län",        "https://www.regionorebrolan.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Västmanland",       "https://www.regionvastmanland.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Dalarna",           "https://www.regiondalarna.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Gävleborg",         "https://www.regiongavleborg.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Västernorrland",    "https://www.rvn.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Jämtland Härjedalen","https://www.regionjh.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Västerbotten",      "https://www.regionvasterbotten.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Norrbotten",        "https://www.norrbotten.se/om-regionen/organisation/regionfullmaktige/", "href"),
    ("Region Gotland",           "https://www.gotland.se/om-kommunen/organisation/kommunfullmaktige/", "href"),
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-åäöÅÄÖ]+@[a-zA-Z0-9.\-åäöÅÄÖ]+\.[a-zA-Z]{2,}")


async def accept_cookies(page):
    for text in ["Acceptera alla", "Acceptera", "Jag förstår", "Accept all", "Accept", "Godkänn"]:
        try:
            btn = await page.query_selector(f"button:has-text('{text}')")
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.5)
                return
        except PlaywrightError:
            pass


async def scrape_region(context, namn, url):
    emails = set()
    page = None
    try:
        page = await context.new_page()
        logger.info(f"Hämtar {namn}: {url}")
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        await accept_cookies(page)
        await asyncio.sleep(1)

        # Strategi 1: mailto-länkar
        hrefs = await page.eval_on_selector_all(
            "a[href^='mailto:']",
            "els => els.map(e => e.href)"
        )
        for href in hrefs:
            email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if EMAIL_RE.match(email):
                emails.add(email)

        # Strategi 2: regex på synlig text om mailto gav för lite
        if len(emails) < 3:
            content = await page.content()
            found = EMAIL_RE.findall(content)
            for email in found:
                email = email.lower()
                # Filtrera bort webmaster/noreply/tekniska adresser
                if not any(x in email for x in ["noreply", "no-reply", "webmaster", "info@", "kontakt@", "webb@"]):
                    emails.add(email)

        logger.info(f"  → {len(emails)} adresser funna")
    except PlaywrightError as e:
        logger.error(f"Fel för {namn}: {e}")
    finally:
        if page:
            await page.close()
    return emails


def spara_vcf(namn, emails, path):
    safe_name = namn.replace("/", "-")
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"FN:{safe_name}",
        f"N:{safe_name};;;;",
        f"ORG:{safe_name}",
    ]
    for email in sorted(emails):
        lines.append(f"EMAIL;TYPE=WORK:{email}")
    lines.append("END:VCARD")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Sparad: {path}")


async def main():
    alla_emails = {}  # namn -> set(emails)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
        )

        for namn, url, _ in REGIONER:
            emails = await scrape_region(context, namn, url)
            if emails:
                alla_emails[namn] = emails
                safe = namn.replace(" ", "_").replace("/", "-")
                spara_vcf(namn, emails, f"{OUTPUT_DIR}/{safe}.vcf")
            await asyncio.sleep(2)

        await context.close()
        await browser.close()

    # Samlad VCF med alla
    alla = set()
    for emails in alla_emails.values():
        alla.update(emails)

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "FN:Alla regioner",
        "N:Alla regioner;;;;",
        "ORG:Sveriges Regioner",
    ]
    for email in sorted(alla):
        lines.append(f"EMAIL;TYPE=WORK:{email}")
    lines.append("END:VCARD")

    with open(f"{OUTPUT_DIR}/Alla_regioner.vcf", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Klar. Totalt {len(alla)} unika adresser från {len(alla_emails)} regioner.")


if __name__ == "__main__":
    asyncio.run(main())
