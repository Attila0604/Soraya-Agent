"""
Apify-Anbindung (Recherche).
Liest den Textinhalt einer Webseite aus, damit der Content-Agent daraus
Posts schreiben kann.

Nutzt den bekannten Apify-Actor "website-content-crawler" ueber den
run-sync-Endpunkt (ein Aufruf, Ergebnis kommt direkt zurueck).
"""

import os
import requests

APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

# Standard-Actor von Apify zum Auslesen von Webseiten-Text.
APIFY_ACTOR = "apify~website-content-crawler"


def hole_webseiten_text(url: str, max_zeichen: int = 6000) -> str:
    if not APIFY_API_TOKEN:
        raise RuntimeError(
            "APIFY_API_TOKEN fehlt. Bitte in Railway unter Variables setzen."
        )

    endpoint = (
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR}"
        f"/run-sync-get-dataset-items?token={APIFY_API_TOKEN}"
    )

    antwort = requests.post(
        endpoint,
        json={
            "startUrls": [{"url": url}],
            "maxCrawlPages": 1,
            "crawlerType": "cheerio",  # schnell, kein Browser noetig
        },
        timeout=180,
    )
    antwort.raise_for_status()
    items = antwort.json()

    # Text aus den Ergebnissen zusammensetzen.
    texte = []
    for item in items:
        t = item.get("text") or item.get("markdown") or ""
        if t:
            texte.append(t)

    gesamt = "\n\n".join(texte).strip()
    return gesamt[:max_zeichen]
