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
ACTOR_PLAYSTORE = os.environ.get("APIFY_ACTOR_PLAYSTORE", "automation-lab~google-play-scraper")


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

def quelle_playstore(suche: str = "astrologie horoskop", max_zeichen: int = 7000) -> str:
    """Sucht Astrologie-Apps im Play Store und holt deren Bewertungen."""
    # Schritt 1: Apps zum Suchbegriff finden
    apps = _lauf(ACTOR_PLAYSTORE, {
        "mode": "search",
        "searchTerms": [suche],
        "maxItems": 8,
        "country": "de",
        "language": "de",
    }, timeout=240)

    app_ids, namen = [], {}
    for a in apps[:8]:
        aid = a.get("appId") or a.get("packageName") or a.get("id")
        if aid:
            app_ids.append(aid)
            namen[aid] = a.get("title") or a.get("name") or aid

    if not app_ids:
        raise RuntimeError(f"Keine Apps gefunden zu '{suche}'.")

    # Schritt 2: Bewertungen zu diesen Apps holen
    reviews = _lauf(ACTOR_PLAYSTORE, {
        "mode": "reviews",
        "appIds": app_ids[:5],
        "maxReviews": 40,
        "maxItems": 40,
        "country": "de",
        "language": "de",
        "sort": "newest",
    }, timeout=300)

    zeilen = [f"[Gefundene Apps] {', '.join(namen.values())}"]
    for r in reviews[:60]:
        txt = (r.get("text") or r.get("content") or r.get("review") or "")
        txt = txt.replace("\n", " ").strip()
        sterne = r.get("score") or r.get("rating") or "?"
        app = namen.get(r.get("appId", ""), r.get("appId", ""))
        if txt:
            zeilen.append(f"- [{app}] ({sterne}\u2605) {txt[:280]}")

    if len(zeilen) <= 1:
        raise RuntimeError("Apps gefunden, aber keine Bewertungstexte erhalten.")

    return "\n".join(zeilen).strip()[:max_zeichen]
