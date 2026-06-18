FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY scraper.py .
COPY entrypoint.sh .
ENTRYPOINT ["/app/entrypoint.sh"]
