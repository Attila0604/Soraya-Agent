"""
Reddit-Recherche — kostenlos, ohne Apify.
Reddit stellt seine Suche als offene JSON-Schnittstelle bereit.
Kein Konto, kein Token, keine Kosten.
"""

import time
import requests

KOPFZEILEN = {
    # Reddit verlangt eine erkennbare Kennung, sonst wird geblockt.
    "User-Agent": "SorayaAgent/1.0 (Zielgruppenforschung)"
}


def quelle_reddit(begriffe: list[str], pro_suche: int = 15, max_zeichen: int = 8000) -> str:
    zeilen = []

    for begriff in [b for b in begriffe if b.strip()][:3]:
        try:
            antwort = requests.get(
                "https://www.reddit.com/search.json",
                params={
                    "q": begriff,
                    "limit": pro_suche,
                    "sort": "relevance",
                    "t": "year",
                },
                headers=KOPFZEILEN,
                timeout=30,
            )
            antwort.raise_for_status()
            daten = antwort.json()
        except Exception as e:
            zeilen.append(f"[Suche] {begriff} — nicht abrufbar: {e}")
            continue

        zeilen.append(f"\n[Suche] {begriff}")
        for eintrag in daten.get("data", {}).get("children", []):
            p = eintrag.get("data", {})
            titel = (p.get("title") or "").strip()
            text = (p.get("selftext") or "").replace("\n", " ").strip()
            sub = p.get("subreddit", "")
            punkte = p.get("score", 0)
            kommentare = p.get("num_comments", 0)
            if titel:
                zeilen.append(
                    f"- [r/{sub}] ({punkte} Punkte, {kommentare} Kommentare) "
                    f"{titel} :: {text[:260]}"
                )
        time.sleep(1)  # freundlich zu Reddit bleiben

    inhalt = "\n".join(zeilen).strip()
    if not inhalt:
        raise RuntimeError("Reddit hat keine Ergebnisse geliefert.")
    return inhalt[:max_zeichen]
