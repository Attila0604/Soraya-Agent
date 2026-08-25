"""
Apify-Anbindung (Recherche).
- hole_webseiten_text: liest den Textinhalt einer Webseite aus.
- suche_im_netz: sucht ueber Google und liefert Titel + Beschreibungen
  der Treffer (gut, um zu sehen, was Menschen zu einem Thema bewegt).
"""

import os
import requests

APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

ACTOR_CRAWLER = "apify~website-content-crawler"
ACTOR_SUCHE = "apify~google-search-scraper"


def _pruefe_token():
    if not APIFY_API_TOKEN:
        raise RuntimeError(
            "APIFY_API_TOKEN fehlt. Bitte in Railway unter Variables setzen."
        )


def hole_webseiten_text(url: str, max_zeichen: int = 6000) -> str:
    _pruefe_token()
    endpoint = (
        f"https://api.apify.com/v2/acts/{ACTOR_CRAWLER}"
        f"/run-sync-get-dataset-items?token={APIFY_API_TOKEN}"
    )
    antwort = requests.post(
        endpoint,
        json={
            "startUrls": [{"url": url}],
            "maxCrawlPages": 1,
            "crawlerType": "cheerio",
        },
        timeout=180,
    )
    if antwort.status_code >= 400:
        raise RuntimeError(f"Apify Fehler {antwort.status_code}: {antwort.text[:300]}")

    texte = []
    for item in antwort.json():
        t = item.get("text") or item.get("markdown") or ""
        if t:
            texte.append(t)
    return "\n\n".join(texte).strip()[:max_zeichen]


def suche_im_netz(begriffe: list[str], land: str = "at", max_zeichen: int = 9000) -> str:
    """Sucht zu mehreren Begriffen und sammelt Titel + Beschreibungen der Treffer."""
    _pruefe_token()
    endpoint = (
        f"https://api.apify.com/v2/acts/{ACTOR_SUCHE}"
        f"/run-sync-get-dataset-items?token={APIFY_API_TOKEN}"
    )

    anfrage = "\n".join(b for b in begriffe if b.strip())

    antwort = requests.post(
        endpoint,
        json={
            "queries": anfrage,
            "resultsPerPage": 10,
            "maxPagesPerQuery": 1,
            "countryCode": land,
            "languageCode": "de",
        },
        timeout=240,
    )
    if antwort.status_code >= 400:
        raise RuntimeError(f"Apify Fehler {antwort.status_code}: {antwort.text[:300]}")

    zeilen = []
    for seite in antwort.json():
        suchbegriff = (seite.get("searchQuery") or {}).get("term", "")
        if suchbegriff:
            zeilen.append(f"\n### Suche: {suchbegriff}")
        # organische Treffer
        for t in seite.get("organicResults", []) or []:
            titel = (t.get("title") or "").strip()
            besch = (t.get("description") or "").strip()
            if titel:
                zeilen.append(f"- {titel} — {besch}")
        # verwandte Suchanfragen: zeigen, was Menschen sonst noch fragen
        verwandte = seite.get("relatedQueries") or seite.get("peopleAlsoAsk") or []
        for v in verwandte:
            frage = v.get("title") or v.get("question") or ""
            if frage:
                zeilen.append(f"- [Auch gefragt] {frage}")

    return "\n".join(zeilen).strip()[:max_zeichen]
