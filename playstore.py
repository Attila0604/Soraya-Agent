"""
Play-Store-Recherche — kostenlos, ohne Apify.
Nutzt das Paket google-play-scraper, das direkt bei Google Play anfragt.
Kein Konto, kein Token, keine Kosten.
"""

from google_play_scraper import search as gp_search, reviews as gp_reviews, Sort


def quelle_playstore(
    suche: str = "astrologie horoskop",
    anzahl_apps: int = 5,
    pro_app: int = 25,
    land: str = "de",
    max_zeichen: int = 8000,
) -> str:
    treffer = gp_search(suche, lang="de", country=land, n_hits=anzahl_apps)
    if not treffer:
        raise RuntimeError(f"Keine Apps gefunden zu '{suche}'.")

    zeilen = []
    namen = []

    for app in treffer[:anzahl_apps]:
        app_id = app.get("appId")
        name = app.get("title") or app_id
        note = app.get("score")
        if not app_id:
            continue
        namen.append(f"{name} ({note}\u2605)" if note else name)

        # Bewusst die schlechten Bewertungen zuerst: dort steht,
        # was Nutzer wirklich stoert.
        for sortierung, kennzeichen in ((Sort.NEWEST, "neu"), (Sort.RATING, "kritisch")):
            try:
                ergebnis, _ = gp_reviews(
                    app_id, lang="de", country=land,
                    sort=sortierung, count=pro_app,
                    filter_score_with=2 if kennzeichen == "kritisch" else None,
                )
            except Exception:
                continue
            for r in ergebnis:
                txt = (r.get("content") or "").replace("\n", " ").strip()
                if txt:
                    zeilen.append(f"- [{name}] ({r.get('score','?')}\u2605) {txt[:280]}")

    if not zeilen:
        raise RuntimeError("Apps gefunden, aber keine Bewertungstexte erhalten.")

    kopf = "[Untersuchte Apps] " + ", ".join(namen)
    return (kopf + "\n" + "\n".join(zeilen)).strip()[:max_zeichen]


def quelle_playstore_ids(
    app_ids: list[str], pro_app: int = 30, land: str = "de", max_zeichen: int = 8000
) -> str:
    """Variante: direkt bestimmte Apps auswerten (App-ID aus der Play-Store-URL)."""
    zeilen = []
    for app_id in app_ids[:6]:
        for sortierung, kennzeichen in ((Sort.NEWEST, "neu"), (Sort.RATING, "kritisch")):
            try:
                ergebnis, _ = gp_reviews(
                    app_id, lang="de", country=land,
                    sort=sortierung, count=pro_app,
                    filter_score_with=2 if kennzeichen == "kritisch" else None,
                )
            except Exception as e:
                zeilen.append(f"- [{app_id}] konnte nicht gelesen werden: {e}")
                continue
            for r in ergebnis:
                txt = (r.get("content") or "").replace("\n", " ").strip()
                if txt:
                    zeilen.append(f"- [{app_id}] ({r.get('score','?')}\u2605) {txt[:280]}")
    if not zeilen:
        raise RuntimeError("Keine Bewertungen erhalten.")
    return "\n".join(zeilen).strip()[:max_zeichen]
