#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Periodisk verifiering av e-postadresser i D1-tabellen `politicians`
(politiker-webapp-projektet). Körs via cron/systemd-timer på mp100 — INTE
i Cloudflare Workers, eftersom Cloudflare blockerar utgående port 25
ovillkorligt (dokumenterat i politiker-webapp/README.md).

Tekniken: en "SMTP callout" per domän — koppla upp mot mottagardomänens
MX-server på port 25, skicka EHLO/MAIL FROM/RCPT TO för varje adress på den
domänen, läs svarskoderna, och avsluta INNAN något DATA-kommando skickas.
Inget mail skickas någonsin till mottagaren.

Begränsning värd att känna till: stora leverantörer (Microsoft 365, Google
Workspace) svarar ofta "accepterad" på RCPT TO oavsett om mottagaren
faktiskt finns kvar, just för att motverka denna typ av probing. Skriptet
upptäcker "catch-all"-domäner genom att även testa en uppenbart påhittad
adress per domän — om även den accepteras flaggas hela domänens resultat
som osäkert (catchall_unverified) istället för falskt "valid".

Miljövariabler som krävs (samma .env som sync_to_d1.py):
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN_POLITIKER
  D1_DATABASE_UUID
"""

import os
import random
import smtplib
import socket
import string
import sys
import time
from collections import defaultdict

import dns.resolver
import requests

SMTP_TIMEOUT = 10
DELAY_BETWEEN_DOMAINS = 1.5  # sekunder — var en god nätgranne, ingen brådska
HELO_NAME = "denied.se"
PROBE_FROM = "politiker@denied.se"  # riktig, levererbar adress vi äger — inte spoofad


def env():
    return (
        os.environ["CLOUDFLARE_ACCOUNT_ID"],
        os.environ["CLOUDFLARE_API_TOKEN_POLITIKER"],
        os.environ["D1_DATABASE_UUID"],
    )


def d1_query(account_id: str, token: str, db_uuid: str, sql: str, params=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_uuid}/query"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"sql": sql, "params": params or []},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"D1-fel: {data.get('errors')}")
    return data["result"][0]["results"]


def fetch_politicians(account_id, token, db_uuid):
    rows = d1_query(account_id, token, db_uuid, "SELECT id, email FROM politicians")
    return rows


def random_local_part() -> str:
    return "probe-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def resolve_mx(domain: str):
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=10)
        return sorted(((r.preference, str(r.exchange).rstrip(".")) for r in answers), key=lambda x: x[0])
    except Exception:
        return []


def probe_domain(domain: str, emails: list[str]) -> dict[str, str]:
    """Returnerar {email: status} för alla emails på denna domän."""
    results = {e: "unknown" for e in emails}

    mx_hosts = resolve_mx(domain)
    if not mx_hosts:
        for e in emails:
            results[e] = "unreachable_no_mx"
        return results

    smtp = None
    last_error = None
    for _, host in mx_hosts:
        try:
            smtp = smtplib.SMTP(timeout=SMTP_TIMEOUT)
            smtp.connect(host, 25)
            smtp.helo(HELO_NAME)
            break
        except (socket.error, smtplib.SMTPException) as err:
            last_error = err
            smtp = None
            continue

    if smtp is None:
        for e in emails:
            results[e] = "unreachable_connect_failed"
        return results

    try:
        # Catch-all-detektion: en uppenbart påhittad adress på samma domän.
        is_catchall = False
        try:
            code, _ = smtp.mail(PROBE_FROM)
            probe_addr = f"{random_local_part()}@{domain}"
            code, _ = smtp.rcpt(probe_addr)
            if 250 <= code < 260:
                is_catchall = True
            smtp.rset()
        except smtplib.SMTPException:
            pass  # om själva probe-steget kraschar, fortsätt ändå med de riktiga adresserna

        for e in emails:
            try:
                smtp.mail(PROBE_FROM)
                code, _ = smtp.rcpt(e)
                smtp.rset()
                if 250 <= code < 260:
                    results[e] = "catchall_unverified" if is_catchall else "valid"
                elif code in (550, 551, 553, 450, 452):
                    results[e] = "dead"
                else:
                    results[e] = f"unknown_code_{code}"
            except smtplib.SMTPException as err:
                results[e] = f"error_{type(err).__name__}"
    finally:
        try:
            smtp.quit()
        except Exception:
            pass

    return results


def main():
    account_id, token, db_uuid = env()
    politicians = fetch_politicians(account_id, token, db_uuid)
    print(f"Hämtade {len(politicians)} politiker-rader från D1.")

    by_domain: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in politicians:
        email = row["email"]
        if "@" not in email:
            continue
        domain = email.rsplit("@", 1)[1].lower()
        by_domain[domain].append((row["id"], email))

    print(f"{len(by_domain)} unika domäner att kontrollera.")

    counts = defaultdict(int)
    now_ms = int(time.time() * 1000)

    for i, (domain, rows) in enumerate(sorted(by_domain.items()), 1):
        emails = [email for _, email in rows]
        print(f"[{i}/{len(by_domain)}] {domain} ({len(emails)} adresser)...")
        try:
            status_by_email = probe_domain(domain, emails)
        except Exception as err:
            print(f"  OVÄNTAT FEL för {domain}: {err}", file=sys.stderr)
            status_by_email = {e: "error_unexpected" for e in emails}

        for politician_id, email in rows:
            status = status_by_email.get(email, "unknown")
            counts[status] += 1
            d1_query(
                account_id,
                token,
                db_uuid,
                "UPDATE politicians SET verification_status = ?, last_verified_at = ? WHERE id = ?",
                [status, now_ms, politician_id],
            )

        time.sleep(DELAY_BETWEEN_DOMAINS)

    print("\nKlart. Sammanfattning:")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n}")


if __name__ == "__main__":
    main()
