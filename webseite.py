"""
Webseiten auslesen — kostenlos, ohne Apify.
Holt den Textinhalt einer Seite mit requests + BeautifulSoup.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

KOPFZEILEN = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

MAX_WEITERLEITUNGEN = 5


def pruefe_url(url: str) -> None:
    """Nur oeffentliche http(s)-Adressen zulassen -- kein Zugriff auf interne Dienste."""
    teile = urlparse(url)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        raise ValueError("Bitte eine vollstaendige Adresse mit http:// oder https:// angeben.")
    port = teile.port or (443 if teile.scheme == "https" else 80)
    try:
        adressen = {info[4][0] for info in socket.getaddrinfo(teile.hostname, port)}
    except socket.gaierror:
        raise ValueError(f"Adresse nicht gefunden: {teile.hostname}")
    for adresse in adressen:
        if not ipaddress.ip_address(adresse.split("%")[0]).is_global:
            raise ValueError("Interne oder private Adressen sind nicht erlaubt.")


def hole_webseiten_text(url: str, max_zeichen: int = 6000) -> str:
    # Weiterleitungen selbst folgen, damit auch jedes Ziel geprueft wird
    for _ in range(MAX_WEITERLEITUNGEN + 1):
        pruefe_url(url)
        antwort = requests.get(url, headers=KOPFZEILEN, timeout=30, allow_redirects=False)
        if not antwort.is_redirect:
            break
        url = urljoin(url, antwort.headers.get("location", ""))
    else:
        raise RuntimeError("Die Seite leitet zu oft weiter.")
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
