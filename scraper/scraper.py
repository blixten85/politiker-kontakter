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

    # === Kommuner (första omgången, av ~290) ===
    # Verifierade Troman-baserade kommunfullmäktige
    {
        "namn": "Göteborgs Stad",
        "typ": "troman",
        "url": "https://goteborg.tromanpublik.se/organisation/8f8da821-ebcd-4d1a-8a91-b1427de24de5",
    },
    {
        "namn": "Linköpings kommun",
        "typ": "troman",
        "url": "https://linkoping.tromanpublik.se/organisation/f837afca-8263-462d-b73f-b8058346ca19",
    },
    {
        "namn": "Örebro kommun",
        "typ": "troman",
        "url": "https://orebro.tromanpublik.se/organisation/59a7d59a-4f7b-4bde-997f-9f0d45255b44",
    },
    {
        "namn": "Helsingborgs stad",
        "typ": "troman",
        "url": "https://helsingborg.tromanpublik.se/organisation/c972abcd-f878-496d-bd4f-f76cfd22899b",
    },
    {
        "namn": "Norrköpings kommun",
        "typ": "troman",
        "url": "https://norrkoping.tromanpublik.se/organisation/8e518403-bcf5-4595-bbe2-ed2f042600bc",
    },
    {
        # Eget system (Evald), inte Netpublicator/Troman. Aktivt blockerad (403)
        # mot enkla HTTP-anrop vid verifiering - kvar som bästa kända URL.
        "namn": "Stockholms stad",
        "typ": "mailto",
        "url": "https://evald.stockholm.se/extern/Organ/1052",
    },
    {
        # JS-renderad MeetingPlus-portal utan synliga mailto-länkar vid
        # verifiering - ger troligen 0 träffar tills en annan källa läggs till.
        "namn": "Malmö stad",
        "typ": "mailto",
        "url": "https://motenmedborgarportal.malmo.se/committees/kommunfullmaktige/representatives",
    },
    {
        # Eget sök/filter-system utan centralt mailto-register - profilsidor
        # kan ha e-post men kräver annan crawl-logik än de tre stödda typerna.
        "namn": "Uppsala kommun",
        "typ": "mailto",
        "url": "https://www.uppsala.se/kommun-och-politik/sa-fungerar-kommunen/fortroendevalda/",
    },
    {
        # Ledamotssidan visar endast telefonnummer, inga e-postadresser alls.
        # Kvar som bästa kända källa, ger troligen 0 träffar.
        "namn": "Västerås stad",
        "typ": "mailto",
        "url": "https://www.vasteras.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/kommunfullmaktiges-ledamoter.html",
    },
    {
        # Kommunens Netpublicator-instans används bara för möteshandlingar,
        # inte det publika "elected"-registret som regionen använder.
        "namn": "Jönköpings kommun",
        "typ": "mailto",
        "url": "https://www.jonkoping.se/kommun--politik/kommunens-organisation/kommunfullmaktige",
    },
    # === Kommuner (andra omgången, Troman-verifierade) ===
    {
        "namn": "Ale kommun",
        "typ": "troman",
        "url": "https://ale.tromanpublik.se/organisation/284d0c84-42de-411a-907d-8ef34000966d",
    },
    {
        "namn": "Arvika kommun",
        "typ": "troman",
        "url": "https://arvika.tromanpublik.se/organisation/40d54ad7-dc0d-4d03-9c3c-b8666947110d",
    },
    {
        "namn": "Avesta kommun",
        "typ": "troman",
        "url": "https://avesta.tromanpublik.se/organisation/d5272b72-712f-4d1e-a663-cbe6638d9f62",
    },
    {
        "namn": "Bollebygds kommun",
        "typ": "troman",
        "url": "https://bollebygd.tromanpublik.se/organisation/bbab0ee2-5c13-4e03-b072-97862d52c740",
    },
    {
        "namn": "Borås kommun",
        "typ": "troman",
        "url": "https://boras.tromanpublik.se/organisation/0e066f5d-3b71-4fc3-a57f-361daee1bbd5",
    },
    {
        "namn": "Botkyrka kommun",
        "typ": "troman",
        "url": "https://botkyrka.tromanpublik.se/organisation/b447fd5e-c354-4796-ba82-3b0f838940da",
    },
    {
        "namn": "Burlövs kommun",
        "typ": "troman",
        "url": "https://burlov.tromanpublik.se/organisation/1059cec2-780d-46ee-8557-d557aaeaa8c7",
    },
    {
        "namn": "Båstads kommun",
        "typ": "troman",
        "url": "https://bastad.tromanpublik.se/organisation/92b85d1d-53ac-4383-8046-bd9b124fd85f",
    },
    {
        "namn": "Danderyds kommun",
        "typ": "troman",
        "url": "https://danderyd.tromanpublik.se/organisation/983d5be0-28b1-4493-bb16-46c51e378457",
    },
    {
        "namn": "Degerfors kommun",
        "typ": "troman",
        "url": "https://degerfors.tromanpublik.se/organisation/5cab7073-b84f-4282-9edd-54e939571bd5",
    },
    {
        "namn": "Eda kommun",
        "typ": "troman",
        "url": "https://eda.tromanpublik.se/organisation/8715f78b-ea24-4464-b371-3602d2a9c47a",
    },
    {
        "namn": "Emmaboda kommun",
        "typ": "troman",
        "url": "https://emmaboda.tromanpublik.se/organisation/bbb681b0-5510-42f5-8acf-e044931e0f66",
    },
    {
        "namn": "Eskilstuna kommun",
        "typ": "troman",
        "url": "https://eskilstuna.tromanpublik.se/organisation/2e40ae20-e555-4954-88b9-bf7c14680374",
    },
    {
        "namn": "Finspångs kommun",
        "typ": "troman",
        "url": "https://finspang.tromanpublik.se/organisation/dc0cc9ad-b842-4ae4-bd37-5e40c282ee30",
    },
    {
        "namn": "Flens kommun",
        "typ": "troman",
        "url": "https://flen.tromanpublik.se/organisation/0b9c6240-fcc0-41c8-9c9c-d5748cdb1e8a",
    },
    {
        "namn": "Forshaga kommun",
        "typ": "troman",
        "url": "https://forshaga.tromanpublik.se/organisation/60de73c0-c92a-409a-bd9a-b4cf736c8f63",
    },
    {
        "namn": "Gagnefs kommun",
        "typ": "troman",
        "url": "https://gagnef.tromanpublik.se/organisation/5237fdbf-35dc-4d62-87fd-8c8a57c56be0",
    },
    {
        "namn": "Gislaveds kommun",
        "typ": "troman",
        "url": "https://gislaved.tromanpublik.se/organisation/2fd29714-9f8a-4e56-a640-39e0d6faeea1",
    },
    {
        "namn": "Gnesta kommun",
        "typ": "troman",
        "url": "https://gnesta.tromanpublik.se/organisation/917f6e78-cf77-4b63-ae19-444597087572",
    },
    {
        "namn": "Gnosjö kommun",
        "typ": "troman",
        "url": "https://gnosjo.tromanpublik.se/organisation/992934df-7a20-4518-8c57-8f061616522a",
    },
    {
        "namn": "Gällivare kommun",
        "typ": "troman",
        "url": "https://gallivare.tromanpublik.se/organisation/cf429125-c8f1-444a-9981-719a5df6c789",
    },
    {
        "namn": "Gävle kommun",
        "typ": "troman",
        "url": "https://gavle.tromanpublik.se/organisation/b4ca3498-5172-4b98-a157-bc6f7303e956",
    },
    {
        "namn": "Hagfors kommun",
        "typ": "troman",
        "url": "https://hagfors.tromanpublik.se/organisation/6c91a023-2720-41b4-8035-29f3ed740676",
    },
    {
        "namn": "Hallsbergs kommun",
        "typ": "troman",
        "url": "https://hallsberg.tromanpublik.se/organisation/d6b41149-cf0c-431f-9106-edbed43b090c",
    },
    {
        "namn": "Hammarö kommun",
        "typ": "troman",
        "url": "https://hammaro.tromanpublik.se/organisation/edff2660-f2a8-4351-8e5b-11320973f152",
    },
    {
        "namn": "Haninge kommun",
        "typ": "troman",
        "url": "https://haninge.tromanpublik.se/organisation/21940027-8047-4712-81bb-55b61de14d16",
    },
    {
        "namn": "Haparanda kommun",
        "typ": "troman",
        "url": "https://haparanda.tromanpublik.se/organisation/28f83e2d-96f8-4034-9537-deae22b73d95",
    },
    {
        "namn": "Hedemora kommun",
        "typ": "troman",
        "url": "https://hedemora.tromanpublik.se/organisation/314dc275-ee52-4957-9ef8-f28fbfad1c35",
    },
    {
        "namn": "Hylte kommun",
        "typ": "troman",
        "url": "https://hylte.tromanpublik.se/organisation/0ae75ca2-0e7b-4df7-801b-c60a86c1228f",
    },
    {
        "namn": "Härnösands kommun",
        "typ": "troman",
        "url": "https://harnosand.tromanpublik.se/organisation/2fc0c15d-6966-47af-a3fa-427227c4d61c",
    },
    {
        "namn": "Härryda kommun",
        "typ": "troman",
        "url": "https://harryda.tromanpublik.se/organisation/f005a072-ca6f-4b64-9cd2-0613d3617e2d",
    },
    {
        "namn": "Hässleholms kommun",
        "typ": "troman",
        "url": "https://hassleholm.tromanpublik.se/organisation/67bc961c-29f0-4dde-9d98-4c5630ddac44",
    },
    {
        "namn": "Höganäs kommun",
        "typ": "troman",
        "url": "https://hoganas.tromanpublik.se/organisation/c94b500b-8b85-4a77-9804-8bc4642f4221",
    },
    {
        "namn": "Järfälla kommun",
        "typ": "troman",
        "url": "https://jarfalla.tromanpublik.se/organisation/ec55e51d-9fab-44d4-9909-59d44678c599",
    },
    {
        "namn": "Kalix kommun",
        "typ": "troman",
        "url": "https://kalix.tromanpublik.se/organisation/593e24ed-4664-4d7c-a4b6-2e1464062909",
    },
    {
        "namn": "Kalmar kommun",
        "typ": "troman",
        "url": "https://kalmar.tromanpublik.se/organisation/5368c2ed-f82d-4577-b6c0-03f34170d357",
    },
    {
        "namn": "Karlskoga kommun",
        "typ": "troman",
        "url": "https://karlskoga.tromanpublik.se/organisation/d6212650-0706-4ece-aec4-1369d3db3647",
    },
    {
        "namn": "Karlskrona kommun",
        "typ": "troman",
        "url": "https://karlskrona.tromanpublik.se/organisation/9da5078b-abea-4bb2-bd33-86ecd4c11fc8",
    },
    {
        "namn": "Karlstads kommun",
        "typ": "troman",
        "url": "https://karlstad.tromanpublik.se/organisation/fd2ccc4c-120c-4baa-9f63-e13c4d9c7947",
    },
    {
        "namn": "Katrineholms kommun",
        "typ": "troman",
        "url": "https://katrineholm.tromanpublik.se/organisation/1d2f7922-fe6e-4039-ab94-f4a40002a5e9",
    },
    {
        "namn": "Kils kommun",
        "typ": "troman",
        "url": "https://kil.tromanpublik.se/organisation/a49b6e5a-01c5-49c5-a73f-89ceebaf70dc",
    },
    {
        "namn": "Kinda kommun",
        "typ": "troman",
        "url": "https://kinda.tromanpublik.se/organisation/9dedab02-646d-4ac9-afd8-be42a602c01d",
    },
    {
        "namn": "Knivsta kommun",
        "typ": "troman",
        "url": "https://knivsta.tromanpublik.se/organisation/9e2541c0-d9e4-45ad-b529-5ff0d72bdd5d",
    },
    {
        "namn": "Krokoms kommun",
        "typ": "troman",
        "url": "https://krokom.tromanpublik.se/organisation/cabf9994-4867-4e1a-b368-859649acaa8b",
    },
    {
        "namn": "Kumla kommun",
        "typ": "troman",
        "url": "https://kumla.tromanpublik.se/organisation/017a4dd9-cda0-4d41-9d78-2f5d3506c857",
    },
    {
        "namn": "Kungsbacka kommun",
        "typ": "troman",
        "url": "https://kungsbacka.tromanpublik.se/organisation/7723aaee-423b-43a6-b631-3564b63dd746",
    },
    {
        "namn": "Kungälvs kommun",
        "typ": "troman",
        "url": "https://kungalv.tromanpublik.se/organisation/87044574-bac2-4ba3-8a7c-70eeb8122720",
    },
    {
        "namn": "Kävlinge kommun",
        "typ": "troman",
        "url": "https://kavlinge.tromanpublik.se/organisation/17759e2c-0d22-4616-862f-2e2187b5258e",
    },
    {
        "namn": "Landskrona kommun",
        "typ": "troman",
        "url": "https://landskrona.tromanpublik.se/organisation/ddadc7ad-bd40-4d7a-bcb1-1b80c0c08e0a",
    },
    {
        "namn": "Lekebergs kommun",
        "typ": "troman",
        "url": "https://lekeberg.tromanpublik.se/organisation/dc2fe6d2-e731-4863-ac1d-90cd359263c3",
    },
    {
        "namn": "Lerums kommun",
        "typ": "troman",
        "url": "https://lerum.tromanpublik.se/organisation/46089da5-8ee8-46b3-a120-c564b86482cc",
    },
    {
        "namn": "Lidingö kommun",
        "typ": "troman",
        "url": "https://lidingo.tromanpublik.se/organisation/88b78d38-bf85-4f96-ae75-87fb7c777768",
    },
    {
        "namn": "Lilla Edets kommun",
        "typ": "troman",
        "url": "https://lillaedet.tromanpublik.se/organisation/ba2a541a-2da6-4a65-abb2-74ae0784850a",
    },
    {
        "namn": "Lindesbergs kommun",
        "typ": "troman",
        "url": "https://lindesberg.tromanpublik.se/organisation/756b67ac-8320-4c9f-8832-4e9147b9c8d2",
    },
    {
        "namn": "Ljungby kommun",
        "typ": "troman",
        "url": "https://ljungby.tromanpublik.se/organisation/c44560f5-67cc-4a94-b04d-022d80911e99",
    },
    {
        "namn": "Lomma kommun",
        "typ": "troman",
        "url": "https://lomma.tromanpublik.se/organisation/99aed780-2e5b-4e15-861c-7752989bc996",
    },
    {
        "namn": "Ludvika kommun",
        "typ": "troman",
        "url": "https://ludvika.tromanpublik.se/organisation/b9e1853b-4ef5-4a37-b7f0-99a9b033562c",
    },
    {
        "namn": "Lycksele kommun",
        "typ": "troman",
        "url": "https://lycksele.tromanpublik.se/organisation/4bc3689b-1df2-4669-8220-2e45a1dc2033",
    },
    {
        "namn": "Lysekils kommun",
        "typ": "troman",
        "url": "https://lysekil.tromanpublik.se/organisation/04c17fd3-0979-412b-95d9-88ca758c7f4d",
    },
    {
        "namn": "Marks kommun",
        "typ": "troman",
        "url": "https://mark.tromanpublik.se/organisation/c05416bd-aa5b-40ad-afc2-02b0b6346455",
    },
    {
        "namn": "Mjölby kommun",
        "typ": "troman",
        "url": "https://mjolby.tromanpublik.se/organisation/70a33fff-1169-4700-911f-cade41c1d301",
    },
    {
        "namn": "Motala kommun",
        "typ": "troman",
        "url": "https://motala.tromanpublik.se/organisation/150f4dbb-5fc8-41ea-8553-67d3a3dcd95a",
    },
    {
        "namn": "Munkedals kommun",
        "typ": "troman",
        "url": "https://munkedal.tromanpublik.se/organisation/5b1f1fd3-2c51-4109-a854-ce96ee6bc150",
    },
    {
        "namn": "Mölndals kommun",
        "typ": "troman",
        "url": "https://molndal.tromanpublik.se/organisation/2ef7597f-cfae-468c-bb0e-24aaf0764657",
    },
    {
        "namn": "Nacka kommun",
        "typ": "troman",
        "url": "https://nacka.tromanpublik.se/organisation/8cd21725-1058-4bc5-9cd6-82f78ba4a878",
    },
    {
        "namn": "Nora kommun",
        "typ": "troman",
        "url": "https://nora.tromanpublik.se/organisation/23edda83-aa84-4826-a149-567ef073f545",
    },
    {
        "namn": "Norbergs kommun",
        "typ": "troman",
        "url": "https://norberg.tromanpublik.se/organisation/48000533-66e3-4e3e-b84a-f552946f29ad",
    },
    {
        "namn": "Norrtälje kommun",
        "typ": "troman",
        "url": "https://norrtalje.tromanpublik.se/organisation/fe14d0dc-9f8d-46ef-a997-570f8c97a93d",
    },
    {
        "namn": "Norsjö kommun",
        "typ": "troman",
        "url": "https://norsjo.tromanpublik.se/organisation/f3005192-1f0d-4708-8698-781ed739fc9c",
    },
    {
        "namn": "Nybro kommun",
        "typ": "troman",
        "url": "https://nybro.tromanpublik.se/organisation/61681487-e492-489b-8187-a72164bd00ac",
    },
    {
        "namn": "Nykvarns kommun",
        "typ": "troman",
        "url": "https://nykvarn.tromanpublik.se/organisation/5ee02396-558d-408e-95a4-0e920a2838c8",
    },
    {
        "namn": "Nyköpings kommun",
        "typ": "troman",
        "url": "https://nykoping.tromanpublik.se/organisation/0835d552-40cf-47a4-9308-60e69f2c28f4",
    },
    {
        "namn": "Nynäshamns kommun",
        "typ": "troman",
        "url": "https://nynashamn.tromanpublik.se/organisation/93a83158-fb9e-4e5a-bccd-94c78f01ba81",
    },
    {
        "namn": "Olofströms kommun",
        "typ": "troman",
        "url": "https://olofstrom.tromanpublik.se/organisation/be3473f0-39bb-46e8-9c6c-360bb76dceea",
    },
    {
        "namn": "Orusts kommun",
        "typ": "troman",
        "url": "https://orust.tromanpublik.se/organisation/1033edf4-b8ad-42d0-945e-aee94a815c6a",
    },
    {
        "namn": "Osby kommun",
        "typ": "troman",
        "url": "https://osby.tromanpublik.se/organisation/e9dee37f-5380-497b-a258-199246c03343",
    },
    {
        "namn": "Oxelösunds kommun",
        "typ": "troman",
        "url": "https://oxelosund.tromanpublik.se/organisation/9b6ae153-33e4-4181-8205-35931fbfbb79",
    },
    {
        "namn": "Partille kommun",
        "typ": "troman",
        "url": "https://partille.tromanpublik.se/organisation/21d47aec-ad2f-4ec2-a98a-86195b242580",
    },
    {
        "namn": "Perstorps kommun",
        "typ": "troman",
        "url": "https://perstorp.tromanpublik.se/organisation/8bebb837-97e9-45a7-80d8-eb3bde1af07e",
    },
    {
        "namn": "Piteå kommun",
        "typ": "troman",
        "url": "https://pitea.tromanpublik.se/organisation/95c9ddec-7fd3-47cb-894d-7d7a3fdbc92c",
    },
    {
        "namn": "Sala kommun",
        "typ": "troman",
        "url": "https://sala.tromanpublik.se/organisation/a99e399a-7e7c-45e7-a853-aeb70b44f5f8",
    },
    {
        "namn": "Salems kommun",
        "typ": "troman",
        "url": "https://salem.tromanpublik.se/organisation/dd595819-cb52-4a59-be4b-f1651770ac1b",
    },
    {
        "namn": "Sigtuna kommun",
        "typ": "troman",
        "url": "https://sigtuna.tromanpublik.se/organisation/befa6b5d-bfbd-48d4-8283-97bf18786512",
    },
    {
        "namn": "Simrishamns kommun",
        "typ": "troman",
        "url": "https://simrishamn.tromanpublik.se/organisation/aa6e0ee2-4cf8-4362-930c-190585f1a5ad",
    },
    {
        "namn": "Skellefteå kommun",
        "typ": "troman",
        "url": "https://skelleftea.tromanpublik.se/organisation/b7f592f8-38c9-46d8-b103-0a6f27d5fe1c",
    },
    {
        "namn": "Skövde kommun",
        "typ": "troman",
        "url": "https://skovde.tromanpublik.se/organisation/81e45419-0d57-462a-ad47-c54041b088ed",
    },
    {
        "namn": "Sollefteå kommun",
        "typ": "troman",
        "url": "https://solleftea.tromanpublik.se/organisation/c830fb08-6df4-4355-a8b5-be3ab58d02ac",
    },
    {
        "namn": "Sollentuna kommun",
        "typ": "troman",
        "url": "https://sollentuna.tromanpublik.se/organisation/1604de01-8e76-4256-ac15-2a519c2be1a4",
    },
    {
        "namn": "Solna kommun",
        "typ": "troman",
        "url": "https://solna.tromanpublik.se/organisation/46c5d68d-a31c-4848-8d04-963c636fb6a8",
    },
    {
        "namn": "Sotenäs kommun",
        "typ": "troman",
        "url": "https://sotenas.tromanpublik.se/organisation/d7b1a1b0-8179-480d-9a8c-1254173a8b98",
    },
    {
        "namn": "Staffanstorps kommun",
        "typ": "troman",
        "url": "https://staffanstorp.tromanpublik.se/organisation/5a807926-6b36-423f-b754-b0c042428329",
    },
    {
        "namn": "Stenungsunds kommun",
        "typ": "troman",
        "url": "https://stenungsund.tromanpublik.se/organisation/32c42641-4b2d-4432-82dd-a4bccc8331bc",
    },
    {
        "namn": "Storumans kommun",
        "typ": "troman",
        "url": "https://storuman.tromanpublik.se/organisation/18ef28f5-0691-4a14-9403-cde544dc0e89",
    },
    {
        "namn": "Strängnäs kommun",
        "typ": "troman",
        "url": "https://strangnas.tromanpublik.se/organisation/cc5030e4-bee1-478b-ab27-9855b10361f6",
    },
    {
        "namn": "Sundbybergs kommun",
        "typ": "troman",
        "url": "https://sundbyberg.tromanpublik.se/organisation/47c5c5ab-ceff-4c7b-b720-b6c8e7ed9b23",
    },
    {
        "namn": "Sundsvalls kommun",
        "typ": "troman",
        "url": "https://sundsvall.tromanpublik.se/organisation/3fe94728-e2e7-47d3-85b3-d06fa8125eba",
    },
    {
        "namn": "Sunne kommun",
        "typ": "troman",
        "url": "https://sunne.tromanpublik.se/organisation/f675c7cc-2c28-483c-b35e-e471c9257b7c",
    },
    {
        "namn": "Svalövs kommun",
        "typ": "troman",
        "url": "https://svalov.tromanpublik.se/organisation/95864840-9622-4ddb-9529-39176633cd75",
    },
    {
        "namn": "Svedala kommun",
        "typ": "troman",
        "url": "https://svedala.tromanpublik.se/organisation/64ad169f-dd30-4a73-a95b-6d27329537f9",
    },
    {
        "namn": "Säters kommun",
        "typ": "troman",
        "url": "https://sater.tromanpublik.se/organisation/27117897-83bd-4717-9a52-17e451483acb",
    },
    {
        "namn": "Södertälje kommun",
        "typ": "troman",
        "url": "https://sodertalje.tromanpublik.se/organisation/26081553-f368-41e9-b868-3567df561298",
    },
    {
        "namn": "Tanums kommun",
        "typ": "troman",
        "url": "https://tanum.tromanpublik.se/organisation/9945cd5f-2edb-4eae-8519-1b912703f221",
    },
    {
        "namn": "Tierps kommun",
        "typ": "troman",
        "url": "https://tierp.tromanpublik.se/organisation/2e95016d-a78b-404c-8c9c-4fb7681cb636",
    },
    {
        "namn": "Torsby kommun",
        "typ": "troman",
        "url": "https://torsby.tromanpublik.se/organisation/da15f2a5-d1b9-4b55-bc08-807a767333ef",
    },
    {
        "namn": "Trelleborgs kommun",
        "typ": "troman",
        "url": "https://trelleborg.tromanpublik.se/organisation/7d0b1bd1-74c3-46cf-bd1f-62d3e9512029",
    },
    {
        "namn": "Trosa kommun",
        "typ": "troman",
        "url": "https://trosa.tromanpublik.se/organisation/e6949592-8ca9-490b-87f9-547715d5146c",
    },
    {
        "namn": "Tyresö kommun",
        "typ": "troman",
        "url": "https://tyreso.tromanpublik.se/organisation/a1a6c6e4-a5df-4862-94fc-be6c4691f817",
    },
    {
        "namn": "Uddevalla kommun",
        "typ": "troman",
        "url": "https://uddevalla.tromanpublik.se/organisation/1770b266-061b-456d-a920-ee220e0d6080",
    },
    {
        "namn": "Ulricehamns kommun",
        "typ": "troman",
        "url": "https://ulricehamn.tromanpublik.se/organisation/053ca305-039c-4f23-9385-ba0b08d054ea",
    },
    {
        "namn": "Umeå kommun",
        "typ": "troman",
        "url": "https://umea.tromanpublik.se/organisation/76f7bf84-8d04-4d2f-8124-4c0968bd7099",
    },
    {
        "namn": "Upplands Väsby kommun",
        "typ": "troman",
        "url": "https://upplandsvasby.tromanpublik.se/organisation/a0a22f43-4b75-4d5c-bee5-adf8f5279aac",
    },
    {
        "namn": "Vadstena kommun",
        "typ": "troman",
        "url": "https://vadstena.tromanpublik.se/organisation/977bc86b-1992-422b-9d7b-ddf2de488b4d",
    },
    {
        "namn": "Vaggeryds kommun",
        "typ": "troman",
        "url": "https://vaggeryd.tromanpublik.se/organisation/3160eada-1c3a-43ef-b471-dcef2cd811f5",
    },
    {
        "namn": "Valdemarsviks kommun",
        "typ": "troman",
        "url": "https://valdemarsvik.tromanpublik.se/organisation/0b44015a-ba73-4320-877e-994d4b48cb08",
    },
    {
        "namn": "Vallentuna kommun",
        "typ": "troman",
        "url": "https://vallentuna.tromanpublik.se/organisation/721a1968-4593-4d8f-a17d-2c71a8c6acdf",
    },
    {
        "namn": "Varbergs kommun",
        "typ": "troman",
        "url": "https://varberg.tromanpublik.se/organisation/bbac4dc2-5097-4d29-aece-bb6359e783a3",
    },
    {
        "namn": "Vaxholms kommun",
        "typ": "troman",
        "url": "https://vaxholm.tromanpublik.se/organisation/c973f4e6-65ff-44ef-9dbf-9c25e10102c2",
    },
    {
        "namn": "Vimmerby kommun",
        "typ": "troman",
        "url": "https://vimmerby.tromanpublik.se/organisation/db050e37-c48f-4800-b6bd-9ee1277839f8",
    },
    {
        "namn": "Vingåkers kommun",
        "typ": "troman",
        "url": "https://vingaker.tromanpublik.se/organisation/038a491b-1b66-44e5-94eb-0e341c3ce220",
    },
    {
        "namn": "Värmdö kommun",
        "typ": "troman",
        "url": "https://varmdo.tromanpublik.se/organisation/5b294486-1f5f-4332-82d2-7269af683bf2",
    },
    {
        "namn": "Växjö kommun",
        "typ": "troman",
        "url": "https://vaxjo.tromanpublik.se/organisation/32806894-f94e-463c-901e-45d4cc4d7552",
    },
    {
        "namn": "Älvdalens kommun",
        "typ": "troman",
        "url": "https://alvdalen.tromanpublik.se/organisation/767ae247-d91a-4b7d-972c-a0c027876906",
    },
    {
        "namn": "Åmåls kommun",
        "typ": "troman",
        "url": "https://amal.tromanpublik.se/organisation/0761efc2-1f41-43f1-a921-2578d3c6c5ee",
    },
    {
        "namn": "Ånge kommun",
        "typ": "troman",
        "url": "https://ange.tromanpublik.se/organisation/43797fe5-3f9f-4d4d-bbb9-e45462824f40",
    },
    {
        "namn": "Åsele kommun",
        "typ": "troman",
        "url": "https://asele.tromanpublik.se/organisation/4132a2d3-d041-44b9-be5b-8884f0c5e5d6",
    },
    {
        "namn": "Örkelljunga kommun",
        "typ": "troman",
        "url": "https://orkelljunga.tromanpublik.se/organisation/d122a15a-7b81-4018-90c6-e394e8fbf361",
    },
    {
        "namn": "Örnsköldsviks kommun",
        "typ": "troman",
        "url": "https://ornskoldsvik.tromanpublik.se/organisation/fceaa133-57f7-4836-b3ad-a5359fc93d1e",
    },
    {
        "namn": "Östersunds kommun",
        "typ": "troman",
        "url": "https://ostersund.tromanpublik.se/organisation/2dff76dd-5cee-4511-a108-815b0991d1cc",
    },
    {
        "namn": "Österåkers kommun",
        "typ": "troman",
        "url": "https://osteraker.tromanpublik.se/organisation/81258e86-1d49-447e-a251-388f6e8d95ba",
    },
    {
        "namn": "Östhammars kommun",
        "typ": "troman",
        "url": "https://osthammar.tromanpublik.se/organisation/36630fc2-f28c-4432-bb49-2ecacb47f43f",
    },
    # === Kommuner via Netpublicator-registret ===
    {
        "namn": "Vänersborgs kommun",
        "typ": "netpublicator",
        "netpub_registry": "596eaf0679f34a4ab0e32ba6131a1e25",
        "netpub_board":    "a9bbcb86-89a6-4a9d-85fd-288a24ac4de4",
    },
    {
        "namn": "Västerviks kommun",
        "typ": "netpublicator",
        "netpub_registry": "fe47625d5fb3456bbc61dc5f56b556c6",
        "netpub_board":    "ddef3a1c-3845-4aaa-a423-83d352c34d38",
    },
    {
        "namn": "Borlänge kommun",
        "typ": "netpublicator",
        "netpub_registry": "489d0e22a9a34a658d98c4f0026b1cb3",
        "netpub_board":    "e9f1d57f-bb08-456d-a391-b2b38935c28e",
    },
    {
        "namn": "Åstorps kommun",
        "typ": "netpublicator",
        "netpub_registry": "ed59a2503b384246b8faeb79b56f999c",
        "netpub_board":    "3ab20218-17ed-45bd-b40f-0300a9c5d4c1",
    },
    {
        "namn": "Alvesta kommun",
        "typ": "mailto",
        "url": "https://www.alvesta.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/",
    },
    {
        "namn": "Arboga kommun",
        "typ": "mailto",
        "url": "https://arboga.se/kommun-och-politik/politik-och-beslut/kommunfullmaktige.html",
    },
    {
        "namn": "Arjeplogs kommun",
        "typ": "mailto",
        "url": "https://arjeplog.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/",
    },
    {
        "namn": "Bergs kommun",
        "typ": "netpublicator",
        "netpub_registry": "914c1eb24cb94a2c97b37a8ef66eef16",
        "netpub_board":    "2417e918-98ce-4413-9c09-b145c0245240",
    },
    {
        "namn": "Bjurholms kommun",
        "typ": "mailto",
        "url": "https://www.bjurholm.se/kommun-och-politik/politik/kommunfullmaktige/kommunfullmaktiges-ledamoter",
    },
    {
        "namn": "Bjuvs kommun",
        "typ": "mailto",
        "url": "https://www.bjuv.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige.html",
    },
    {
        "namn": "Boxholms kommun",
        "typ": "mailto",
        "url": "https://www.boxholm.se/kommun-och-politik/kommunfullmaktige",
    },
    {
        "namn": "Bromölla kommun",
        "typ": "netpublicator",
        "netpub_registry": "98f18704cecc493082761b1333bcca92",
        "netpub_board":    "d9da0c34-e4db-48b0-a461-8e8e53ab4a0e",
    },
    {
        "namn": "Dals-Eds kommun",
        "typ": "mailto",
        "url": "https://www.dalsed.se/kommun-och-politik/fortroendevalda/kommunfullmaktige-2022-2026/",
    },
    {
        "namn": "Dorotea kommun",
        "typ": "mailto",
        "url": "https://www.dorotea.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/",
    },
    {
        "namn": "Ekerö kommun",
        "typ": "netpublicator",
        "netpub_registry": "def31ebd7978473c94f8b6e3bbc93717",
        "netpub_board":    "befb6976-80f0-4746-9b40-380b72d62d6f",
    },
    {
        "namn": "Eksjö kommun",
        "typ": "netpublicator",
        "netpub_registry": "90955e392d574c05937df63cc8624dff",
        "netpub_board":    "d97686af-6ec9-4303-ae14-5889e41eb745",
    },
    {
        "namn": "Eslövs kommun",
        "typ": "netpublicator",
        "netpub_registry": "b4744ae1bd8148e1a08307642caee206",
        "netpub_board":    "4cc77930-fa00-4f48-a22a-5ab981da7a32",
    },
    {
        "namn": "Essunga kommun",
        "typ": "netpublicator",
        "netpub_registry": "e385d0365dc644a4abc03ec16b998e6f",
        "netpub_board":    "600b9a5e-e218-4452-b8d4-dc51d8920b9f",
    },
    {
        "namn": "Fagersta kommun",
        "typ": "mailto",
        "url": "https://fagersta.se/organisation--styrning/politik-och-fortroendevalda/kommunfullmaktige",
    },
    {
        "namn": "Falkenbergs kommun",
        "typ": "netpublicator",
        "netpub_registry": "a7b5af4753e745cea62d2e7f8fcad21d",
        "netpub_board":    "1af56ab5-2413-4c60-81f7-96d0f3875338",
    },
    {
        "namn": "Falu kommun",
        "typ": "netpublicator",
        "netpub_registry": "30d39c931a4b414b821182eb6e72848c",
        "netpub_board":    "c36e0272-3f4f-4646-a861-9a6ae24eec4c",
    },
    {
        "namn": "Filipstads kommun",
        "typ": "mailto",
        "url": "https://www.filipstad.se/toppmeny/kommunochpolitik/politikochdemokrati/fortroendevaldainamnderochstyrelser.1524.html",
    },
    {
        "namn": "Gullspångs kommun",
        "typ": "mailto",
        "url": "https://gullspang.se/kommun-och-politik/kommunens-organisation/politisk-organisation/kommunfullmaktige",
    },
    {
        "namn": "Askersunds kommun",
        "typ": "mailto",
        "url": "https://www.askersund.se/kommun--politik/kommunens-organisation/kommunfullmaktige",
    },
    {
        "namn": "Grästorps kommun",
        "typ": "mailto",
        "url": "https://www.grastorp.se/kommun-och-politik/politisk-organisation/kommunfullmaktige.html",
    },
    {
        "namn": "Götene kommun",
        "typ": "netpublicator",
        "netpub_registry": "f9b3d2833ad246419c9d500f4c46ca6f",
        "netpub_board":    "08b898e5-8938-4722-88ad-98b8d26cbc66",
    },
    {
        "namn": "Halmstads kommun",
        "typ": "mailto",
        "url": "https://www.halmstad.se/kommunochpolitik/politikochdemokrati/kommunfullmaktige/ledamoterochersattarekommunfullmaktige.n306.html",
    },
    {
        "namn": "Hallstahammars kommun",
        "typ": "netpublicator",
        "netpub_registry": "02f4a58a74d749af91d3bd1e6c251db1",
        "netpub_board":    "603d9ac0-566f-449c-8fe5-3bdd59d33ba8",
    },
    {
        "namn": "Heby kommun",
        "typ": "mailto",
        "url": "https://www.heby.se/organisation-plats-och-politik/demokrati-dialog-och-inflytande/hitta-din-politiker",
    },
    {
        "namn": "Hofors kommun",
        "typ": "mailto",
        "url": "https://www.hofors.se/kommun--politik/politik/fortroendevalda/kommunfullmaktige.html",
    },
    {
        "namn": "Hudiksvalls kommun",
        "typ": "mailto",
        "url": "https://hudiksvall.se/Sidor/Kommun-och-politik/Kommunens-organisation/Kommunfullmaktige.html",
    },
    {
        "namn": "Hällefors kommun",
        "typ": "mailto",
        "url": "https://www.hellefors.se/kommunfullmaktige.html",
    },
    {
        "namn": "Härjedalens kommun",
        "typ": "netpublicator",
        "netpub_registry": "4fa3657d195a42bb81dc6a568d846124",
        "netpub_board":    "511718a5-ca52-4449-93e8-81f5cf0f4a2f",
    },
    {
        "namn": "Jokkmokks kommun",
        "typ": "mailto",
        "url": "https://www.jokkmokk.se/kommun-och-politik/politik-och-delaktighet/politisk-organisation/",
    },
    {
        "namn": "Karlsborgs kommun",
        "typ": "mailto",
        "url": "https://karlsborg.se/kommun--politik/sa-styrs-karlsborgs-kommun/politik/fortroendevalda/",
    },
    {
        "namn": "Karlshamns kommun",
        "typ": "netpublicator",
        "netpub_registry": "79c39e9c33df49b1b6d5ac6e12af943c",
        "netpub_board":    "c7ca73bf-1718-4270-ac3d-e7b5c5b84cd9",
    },
    {
        "namn": "Klippans kommun",
        "typ": "netpublicator",
        "netpub_registry": "e65cf67fb472436c9e9e8cbb37d00743",
        "netpub_board":    "665ce36d-153f-46cb-aefa-8a2e455f52b3",
    },
    {
        "namn": "Kristinehamns kommun",
        "typ": "mailto",
        "url": "https://www.kristinehamn.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/",
    },
    {
        "namn": "Kungsörs kommun",
        "typ": "mailto",
        "url": "https://kungsor.se/kommun-och-politik/politik-och-beslut/kommunfullmaktige.html",
    },
    {
        "namn": "Laxå kommun",
        "typ": "mailto",
        "url": "https://www.laxa.se/Kommun-och-politik/Demokrati-och-insyn/Politisk-organisation/Kommunfullmaktige.html",
    },
    {
        "namn": "Leksands kommun",
        "typ": "netpublicator",
        "netpub_registry": "1c41ddabcab843dda687fc5f800f6434",
        "netpub_board":    "caadec9c-c046-4fd3-b5aa-4f3006b9408b",
    },
    {
        "namn": "Lessebo kommun",
        "typ": "mailto",
        "url": "https://www.lessebo.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige.html",
    },
    {
        "namn": "Lidköpings kommun",
        "typ": "netpublicator",
        "netpub_registry": "06a2c997f2624e2185f8e9805ff58d29",
        "netpub_board":    "308d9dc4-2bfa-4988-914a-da95d50ad4fa",
    },
    {
        "namn": "Malung-Sälens kommun",
        "typ": "mailto",
        "url": "https://malung-salen.se/kommunochpolitik/kommunensorganisation/kommunfullmaktige.4.319b126613ec68a069b13b.html",
    },
    {
        "namn": "Malå kommun",
        "typ": "mailto",
        "url": "https://www.mala.se/kommun-och-politik/kontakt-politiker-ordforande/",
    },
    {
        "namn": "Mariestads kommun",
        "typ": "mailto",
        "url": "https://mariestad.se/Mariestads-kommun/Kommun--politik/Politik-och-delaktighet/Politisk-organisation/Kommunfullmaktige",
    },
    {
        "namn": "Sorsele kommun",
        "typ": "mailto",
        "url": "https://www.sorsele.se/kommun-och-politik/delta-och-paaverka/kontakta-politiker/",
    },
    {
        "namn": "Storfors kommun",
        "typ": "mailto",
        "url": "https://www.storfors.se/kommunochpolitik/politiskorganisation/kommunfullmaktige.4.789155f3143f6bce326878.html",
    },
    {
        "namn": "Täby kommun",
        "typ": "mailto",
        "url": "https://www.taby.se/kommun-och-politik/politik-och-beslut/kommunalrad-och-gruppledare",
    },
    {
        "namn": "Töreboda kommun",
        "typ": "mailto",
        "url": "https://toreboda.se/Toreboda-kommun/Kommun--politik/Politik-och-delaktighet/Politisk-organisation/Kommunfullmaktige",
    },
    {
        "namn": "Värnamo kommun",
        "typ": "mailto",
        "url": "https://kommun.varnamo.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/ledamoter-kf.html",
    },
    {
        "namn": "Vara kommun",
        "typ": "netpublicator",
        "netpub_registry": "f3692d5258b04380be12d6e243e2dee5",
        "netpub_board":    "7716f01e-0db2-412f-9505-f9733f1ca25c",
    },
    {
        "namn": "Ydre kommun",
        "typ": "mailto",
        "url": "https://www.ydre.se/ydre-kommun/kommun-och-politik/kommunens-organisation/politisk-organisation/kommunfullmaktige/ledamoter",
    },
    {
        "namn": "Ystads kommun",
        "typ": "netpublicator",
        "netpub_registry": "d5090e5e4644480dac6cd42c7148f88f",
        "netpub_board":    "0f75f777-c1f5-4e14-ad7a-6b4a5660c1d1",
    },
    {
        "namn": "Vellinge kommun",
        "typ": "mailto",
        "url": "https://vellinge.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige",
    },
    {
        "namn": "Vetlanda kommun",
        "typ": "netpublicator",
        "netpub_registry": "CTA6P29drGzqtbbg9eXLaVCdwjYskX3P",
        "netpub_board":    "e697879b-f049-4f1f-96f0-18d4288248e9",
    },
    {
        "namn": "Åtvidabergs kommun",
        "typ": "netpublicator",
        "netpub_registry": "6188c42d5b1749c08494d982a76bf6f0",
        "netpub_board":    "6f3b5768-f31b-4bd7-b50f-7c4908b90e77",
    },
    {
        "namn": "Öckerö kommun",
        "typ": "mailto",
        "url": "https://www.ockero.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige",
    },
    {
        "namn": "Ödeshögs kommun",
        "typ": "netpublicator",
        "netpub_registry": "d7248e4da7ea4f128c8e650074727cfc",
        "netpub_board":    "fac2a669-b00a-427a-b76a-f9373464b859",
    },
    {
        "namn": "Bengtsfors kommun",
        "typ": "netpublicator",
        "netpub_registry": "b7d161d2b24c494492c3ccc43d090872",
        "netpub_board":    "e2cccbc0-cfda-42b7-b959-a2937ac54ae7",
    },
    {
        "namn": "Hjo kommun",
        "typ": "mailto",
        "url": "https://hjo.se/kommun--politik/politik-och-organisation/politik/kommunfullmaktige/ledamoter/",
    },
    {
        "namn": "Kristianstads kommun",
        "typ": "netpublicator",
        "netpub_registry": "vq9V55dgmCL2nt9A8RAGI6S6k879aA3o",
        "netpub_board":    "058e2aa4-0345-4eae-9e62-8bd0f6022e06",
    },
    {
        "namn": "Köpings kommun",
        "typ": "mailto",
        "url": "https://koping.se/kommun--politik/politik-ledning-och-namnder/kommunfullmaktige.html",
    },
    {
        "namn": "Mora kommun",
        "typ": "netpublicator",
        "netpub_registry": "a0cfa985bcff4bde9739c902995c4dac",
        "netpub_board":    "4653632b-9bde-47d0-959b-8a570801bc8a",
    },
    {
        "namn": "Mullsjö kommun",
        "typ": "netpublicator",
        "netpub_registry": "9d2611a2eaf749a1ab794120f854cafd",
        "netpub_board":    "fb8dc480-a0da-446d-9ccf-46c88c4c7c84",
    },
    {
        "namn": "Mönsterås kommun",
        "typ": "mailto",
        "url": "https://www.monsteras.se/kommun-och-politik/kommunens-organisation/kommunfullmaktige/",
    },
    {
        "namn": "Mörbylånga kommun",
        "typ": "mailto",
        "url": "https://www.morbylanga.se/kontakt/kommun-och-politik/kommunfullmaktige/",
    },
    {
        "namn": "Nässjö kommun",
        "typ": "netpublicator",
        "netpub_registry": "gwH89a8xU8NMNdCwKXnTKwPn5ZEPvuku",
        "netpub_board":    "e31e0455-35a3-4da0-94b6-b015d42926f7",
    },
    {
        "namn": "Ockelbo kommun",
        "typ": "mailto",
        "url": "https://ockelbo.se/kommun--politik/kommunens-organisation/kommunfullmaktige",
    },
    {
        "namn": "Orsa kommun",
        "typ": "netpublicator",
        "netpub_registry": "a13fab42083b409695fedc3139f0d5a8",
        "netpub_board":    "4d1d098f-0ea2-45b2-aa78-05b15f848bd5",
    },
    {
        "namn": "Oskarshamns kommun",
        "typ": "mailto",
        "url": "https://www.oskarshamn.se/mer-om-kommunen/politik-och-forvaltning/politik/politiker/",
    },
    {
        "namn": "Robertsfors kommun",
        "typ": "mailto",
        "url": "https://www.robertsfors.se/kommunochpolitik/politikochsammantraden/kommunfullmaktige.1104.html",
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
            elif region["typ"] == "mailto":
                emails = await scrape_mailto(context, namn, region["url"])
            else:
                raise ValueError(f"{namn}: okänd typ '{region['typ']}'")

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
