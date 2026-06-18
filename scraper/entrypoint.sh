#!/bin/bash
set -e
playwright install chromium --with-deps
exec python3 scraper.py
