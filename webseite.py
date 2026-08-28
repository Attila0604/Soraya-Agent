"""
Webseiten auslesen — kostenlos, ohne Apify.
Holt den Textinhalt einer Seite mit requests + BeautifulSoup.
"""

import requests
from bs4 import BeautifulSoup

KOPFZEILEN = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def hole_webseiten_text(url: str, max_zeichen: int = 6000) -> str:
    antwort = requests.get(url, headers=KOPFZEILEN, timeout=30)
    antwort.raise_for_status()

    suppe = BeautifulSoup(antwort.text, "html.parser")

    # Alles entfernen, was kein Inhalt ist
    for tag in suppe(["script", "style", "nav", "header", "footer", "noscript", "aside"]):
        tag.decompose()

    text = suppe.get_text(separator="\n")
    zeilen = [z.strip() for z in text.splitlines()]
    sauber = "\n".join(z for z in zeilen if len(z) > 2)

    if not sauber.strip():
        raise RuntimeError("Die Seite enthielt keinen lesbaren Text.")
    return sauber[:max_zeichen]
