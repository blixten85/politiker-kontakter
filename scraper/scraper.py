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
from urllib.parse import unquote
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
# typ "troman"        = använd Troman-logik (tromanpublik.se, hämta profilsidor)
# typ "mailto"        = skrapa mailto-länkar direkt från sidan
# netpub_registry     = UUID för Netpublicator-registret
# netpub_board        = UUID för Regionfullmäktige-nämnden (Netpublicator)
# url                 = direktlänk (för typ "mailto"/"troman")

REGIONER = [
    {
        "namn": "Region Dalarna",
        "typ": "netpublicator",
        "netpub_registry": "5f0adfedbde841d188c336a5df571458",
        "netpub_board":    "94068ad4-69a6-4afa-bf74-af9b742e655f",
    },
    {
        # Inget centralt mailto-register hittat - profilsidor har bara kontaktformulär.
        # Kräver annan lösning (t.ex. per-parti-sidor) för att ge träffar.
        "namn": "Region Stockholm",
        "typ": "mailto",
        "url": "https://www.regionstockholm.se/demokrati-politik/dina-politiker/politiker/",
    },
    {
        "namn": "Region Uppsala",
        "typ": "troman",
        "url": "https://regionuppsala.tromanpublik.se/organisation/25ba180e-a289-4375-a248-2b549a0c47c8",
    },
    {
        "namn": "Region Sörmland",
        "typ": "mailto",
        "url": "https://regionsormland.se/demokrati-insyn/politisk-organisation/sok-politiker-och-politiska-forsamlingar/",
    },
    {
        "namn": "Region Östergötland",
        "typ": "troman",
        "url": "https://regionostergotland.tromanpublik.se/organisation/bbe5d34b-1050-460e-b052-9d131e030638",
    },
    {
        "namn": "Region Jönköpings län",
        "typ": "netpublicator",
        "netpub_registry": "f2b41d65fac148dd97d9175262929577",
        "netpub_board":    "ae335bbd-bcf7-48aa-b85e-ae0601083505",
    },
    {
        "namn": "Region Kronoberg",
        "typ": "mailto",
        "url": "https://www.regionkronoberg.se/politik-och-demokrati/politisk-organisation/regionfullmaktige/regionfullmaktiges-ledamoter/",
    },
    {
        "namn": "Region Kalmar län",
        "typ": "netpublicator",
        "netpub_registry": "b0f8d6ec62f049168372d66425925826",
        "netpub_board":    "eeb607af-2017-44a9-a18d-a4b945628a5b",
    },
    {
        "namn": "Region Blekinge",
        "typ": "troman",
        "url": "https://regionblekinge.tromanpublik.se/organisation/b58374d3-7ec3-4f1c-9fe4-61fff3773ba9",
    },
    {
        # Aktivt blockerad (403/WAF) mot enkla HTTP-anrop vid verifiering - kvar
        # som bästa kända URL, kan fungera via riktig browser-rendering.
        "namn": "Region Skåne",
        "typ": "mailto",
        "url": "https://www.skane.se/politik-och-demokrati/politik/politiska-organ/regionfullmaktige/",
    },
    {
        "namn": "Region Halland",
        "typ": "troman",
        "url": "https://regionhalland.tromanpublik.se/organisation/5aecfa49-fa87-41d3-8033-32d7539e126d",
    },
    {
        "namn": "Västra Götalandsregionen",
        "typ": "troman",
        "url": "https://vgregion.tromanpublik.se/organisation/251b1684-8d78-4a82-9205-da0e8232c53a",
    },
    {
        "namn": "Region Värmland",
        "typ": "troman",
        "url": "https://regionvarmland.tromanpublik.se/organisation/08876366-236d-47c4-aa43-c06b7a29faba",
    },
    {
        # Troman-baserad men exakt organisations-UUID för regionfullmäktige kunde
        # inte fastställas (gammalt numeriskt URL-schema, sidan svarade 500 på
        # enkla HTTP-anrop). Kvar som bästa kända startpunkt.
        "namn": "Region Örebro län",
        "typ": "mailto",
        "url": "https://regionorebrolan.tromanpublik.se/",
    },
    {
        "namn": "Region Västmanland",
        "typ": "troman",
        "url": "https://regionvastmanland.tromanpublik.se/organisation/e7dc3ed4-ab5c-4984-a342-e4b2bbd16c12",
    },
    {
        "namn": "Region Gävleborg",
        "typ": "troman",
        "url": "https://regiongavleborg.tromanpublik.se/organisation/cf7e8574-e79f-4393-ac37-b0e5802dd866",
    },
    {
        "namn": "Region Västernorrland",
        "typ": "troman",
        "url": "https://rvn.tromanpublik.se/organisation/fa64f1c8-bf86-4ef0-8aaa-7db6334ed653",
    },
    {
        "namn": "Region Jämtland Härjedalen",
        "typ": "troman",
        "url": "https://regionjh.tromanpublik.se/organisation/cb286917-b049-4c75-b58f-9cddfefe28fb",
    },
    {
        "namn": "Region Västerbotten",
        "typ": "troman",
        "url": "https://regionvasterbotten.tromanpublik.se/organisation/01cdebd5-80eb-4094-8afb-9bc554d0fc8e",
    },
    {
        "namn": "Region Norrbotten",
        "typ": "troman",
        "url": "https://norrbotten.tromanpublik.se/organisation/71837ba7-5ece-4aaf-988c-153aecf02a5e",
    },
    {
        # Troman-registret för Gotland exponerar inga e-postadresser alls.
        # Kvar som bästa kända källa, ger troligen 0 träffar tills en annan
        # källa (t.ex. partisidor på gotland.se) läggs till.
        "namn": "Region Gotland",
        "typ": "troman",
        "url": "https://gotland.tromanpublik.se/organisation/9bc13dfd-c20e-474f-b68e-be766963da33",
    },
]


def is_valid_email(email: str) -> bool:
    email = email.lower()
    if not EMAIL_RE.fullmatch(email):
        return False
    return not any(kw in email for kw in SKIP_KEYWORDS)


def email_from_mailto_href(href: str) -> str:
    """Plockar ut e-postadressen ur en mailto-href, t.ex. 'mailto:%20a@b.se?subject=x'.
    unquote() krävs eftersom browsern url-kodar källans whitespace (t.ex. ett
    inledande blanksteg blir %20) innan strip() annars hade kunnat ta bort den."""
    return unquote(href.replace("mailto:", "")).split("?")[0].strip().lower()


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
                    email = email_from_mailto_href(href)
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


async def scrape_troman(context, namn, org_url):
    """Hämtar ledamöternas profilsidor från Troman (tromanpublik.se) och plockar e-post."""
    emails = set()
    page = await context.new_page()
    try:
        log.info(f"{namn}: hämtar ledamötslista {org_url}")
        await page.goto(org_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        hrefs = await page.eval_on_selector_all(
            "a[href*='/person/']",
            "els => els.map(e => e.href)"
        )
        person_urls = list(set(hrefs))
        log.info(f"{namn}: {len(person_urls)} profilsidor hittade")

        for url in person_urls:
            p2 = await context.new_page()
            try:
                await p2.goto(url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(0.5)
                mailto_hrefs = await p2.eval_on_selector_all(
                    "a[href^='mailto:']",
                    "els => els.map(e => e.href)"
                )
                for href in mailto_hrefs:
                    email = email_from_mailto_href(href)
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
            email = email_from_mailto_href(href)
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
            elif region["typ"] == "troman":
                emails = await scrape_troman(context, namn, region["url"])
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
