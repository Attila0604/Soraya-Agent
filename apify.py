"""
Apify-Anbindung (Recherche aus mehreren Quellen).

Jede Quelle ist eine eigene Funktion und liefert Text zurueck.
Die Actor-Namen lassen sich per Railway-Variable ueberschreiben,
falls ein Actor mal umbenannt wird.
"""

import os
import requests

APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

# Actor-IDs (per Umgebungsvariable ueberschreibbar)
ACTOR_CRAWLER = os.environ.get("APIFY_ACTOR_CRAWLER", "apify~website-content-crawler")
ACTOR_GOOGLE = os.environ.get("APIFY_ACTOR_GOOGLE", "apify~google-search-scraper")
ACTOR_INSTAGRAM = os.environ.get("APIFY_ACTOR_INSTAGRAM", "apify~instagram-hashtag-scraper")
ACTOR_TIKTOK = os.environ.get("APIFY_ACTOR_TIKTOK", "clockworks~tiktok-scraper")
ACTOR_REDDIT = os.environ.get("APIFY_ACTOR_REDDIT", "trudax~reddit-scraper-lite")
ACTOR_PLAYSTORE = os.environ.get("APIFY_ACTOR_PLAYSTORE", "epctex~google-play-scraper")


def _pruefe_token():
    if not APIFY_API_TOKEN:
        raise RuntimeError(
            "APIFY_API_TOKEN fehlt. Bitte in Railway unter Variables setzen."
        )


def _lauf(actor: str, eingabe: dict, timeout: int = 300) -> list:
    """Startet einen Apify-Actor und wartet auf das Ergebnis."""
    _pruefe_token()
    endpoint = (
        f"https://api.apify.com/v2/acts/{actor}"
        f"/run-sync-get-dataset-items?token={APIFY_API_TOKEN}"
    )
    antwort = requests.post(endpoint, json=eingabe, timeout=timeout)
    if antwort.status_code >= 400:
        raise RuntimeError(
            f"Apify ({actor}) Fehler {antwort.status_code}: {antwort.text[:250]}"
        )
    daten = antwort.json()
    return daten if isinstance(daten, list) else []


# ---------------------------------------------------------------- Webseite

def hole_webseiten_text(url: str, max_zeichen: int = 6000) -> str:
    items = _lauf(ACTOR_CRAWLER, {
        "startUrls": [{"url": url}],
        "maxCrawlPages": 1,
        "crawlerType": "cheerio",
    }, timeout=180)
    texte = [i.get("text") or i.get("markdown") or "" for i in items]
    return "\n\n".join(t for t in texte if t).strip()[:max_zeichen]


# ---------------------------------------------------------------- Google

def quelle_google(begriffe: list[str], land: str = "at", max_zeichen: int = 7000) -> str:
    items = _lauf(ACTOR_GOOGLE, {
        "queries": "\n".join(b for b in begriffe if b.strip()),
        "resultsPerPage": 10,
        "maxPagesPerQuery": 1,
        "countryCode": land,
        "languageCode": "de",
    }, timeout=240)

    zeilen = []
    for seite in items:
        begriff = (seite.get("searchQuery") or {}).get("term", "")
        if begriff:
            zeilen.append(f"\n[Suche] {begriff}")
        for t in (seite.get("organicResults") or [])[:10]:
            titel = (t.get("title") or "").strip()
            besch = (t.get("description") or "").strip()
            if titel:
                zeilen.append(f"- {titel} — {besch}")
        for v in (seite.get("peopleAlsoAsk") or seite.get("relatedQueries") or [])[:8]:
            frage = v.get("question") or v.get("title") or ""
            if frage:
                zeilen.append(f"- [Auch gefragt] {frage}")
    return "\n".join(zeilen).strip()[:max_zeichen]


# ---------------------------------------------------------------- Instagram

def quelle_instagram(hashtags: list[str], max_zeichen: int = 5000) -> str:
    sauber = [h.lstrip("#").replace(" ", "") for h in hashtags if h.strip()][:2]
    items = _lauf(ACTOR_INSTAGRAM, {
        "hashtags": sauber,
        "resultsLimit": 25,
    }, timeout=300)

    zeilen = []
    for p in items[:25]:
        text = (p.get("caption") or "").replace("\n", " ").strip()
        likes = p.get("likesCount") or 0
        if text:
            zeilen.append(f"- ({likes} Likes) {text[:280]}")
    return "\n".join(zeilen).strip()[:max_zeichen]


# ---------------------------------------------------------------- TikTok

def quelle_tiktok(hashtags: list[str], max_zeichen: int = 5000) -> str:
    sauber = [h.lstrip("#").replace(" ", "") for h in hashtags if h.strip()][:2]
    items = _lauf(ACTOR_TIKTOK, {
        "hashtags": sauber,
        "resultsPerPage": 25,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }, timeout=300)

    zeilen = []
    for v in items[:25]:
        text = (v.get("text") or "").replace("\n", " ").strip()
        plays = v.get("playCount") or 0
        if text:
            zeilen.append(f"- ({plays} Aufrufe) {text[:280]}")
    return "\n".join(zeilen).strip()[:max_zeichen]


# ---------------------------------------------------------------- Reddit

def quelle_reddit(begriffe: list[str], max_zeichen: int = 6000) -> str:
    items = _lauf(ACTOR_REDDIT, {
        "searches": begriffe[:2],
        "type": "posts",
        "sort": "relevance",
        "maxItems": 25,
    }, timeout=300)

    zeilen = []
    for p in items[:25]:
        titel = (p.get("title") or "").strip()
        text = (p.get("body") or p.get("text") or "").replace("\n", " ").strip()
        if titel:
            zeilen.append(f"- {titel} :: {text[:260]}")
    return "\n".join(zeilen).strip()[:max_zeichen]


# ---------------------------------------------------------------- Play Store

def quelle_playstore(suche: str = "astrologie horoskop", max_zeichen: int = 6000) -> str:
    """Bewertungen von Astrologie-Apps im Google Play Store."""
    items = _lauf(ACTOR_PLAYSTORE, {
        "search": [suche],
        "maxItems": 30,
        "includeReviews": True,
        "maxReviews": 30,
        "language": "de",
        "country": "at",
    }, timeout=300)

    zeilen = []
    for app in items[:10]:
        name = app.get("title") or app.get("name") or ""
        if name:
            zeilen.append(f"\n[App] {name} (Bewertung: {app.get('score', '?')})")
        for r in (app.get("reviews") or [])[:10]:
            txt = (r.get("text") or "").replace("\n", " ").strip()
            sterne = r.get("score", "?")
            if txt:
                zeilen.append(f"- ({sterne}\u2605) {txt[:260]}")
        # Manche Actors liefern Bewertungen direkt als eigene Zeilen
        if not name and app.get("text"):
            zeilen.append(f"- ({app.get('score','?')}\u2605) {app['text'][:260]}")
    return "\n".join(zeilen).strip()[:max_zeichen]
