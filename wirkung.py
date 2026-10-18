"""
Wirkung messen: holt die zusammengezaehlten App-Zahlen aus der astro-engine
(/internal/statistik). Dort gibt es nur Summen pro Tag, keine Personendaten.

Railway-Variable AGENT_STATS_TOKEN: derselbe geheime Wert wie beim Dienst
astro-engine (mindestens 24 Zeichen).
"""

import os

import requests

from himmel import engine_url


def link_basis() -> str:
    """Wohin die Post- und Bio-Links zeigen (Landingpage). Railway-Variable LINK_BASIS, optional."""
    basis = (os.environ.get("LINK_BASIS") or "https://www.sorayaluxuryastroguide.com/").strip()
    return basis if basis.endswith("/") else basis + "/"


BIO_LINKS = {"instagram": "bio-ig", "tiktok": "bio-tt", "facebook": "bio-fb"}


def links() -> dict:
    """Link pro Post: <basis>?q=p<id>. Bio-Links: einmal ins jeweilige Profil eintragen."""
    basis = link_basis()
    return {"basis": basis, "post_muster": basis + "?q=p{id}",
            "bio": {plattform: basis + "?q=" + code for plattform, code in BIO_LINKS.items()}}


class NichtEingerichtet(LookupError):
    """Statistik noch nicht verbunden. stand: "agent_fehlt", "engine_fehlt" oder "passt_nicht"."""

    def __init__(self, text: str, stand: str):
        super().__init__(text)
        self.stand = stand


def hole_statistik(tage: int = 30) -> dict:
    token = (os.environ.get("AGENT_STATS_TOKEN") or "").strip()
    if len(token) < 24:
        raise NichtEingerichtet(
            "Noch nicht eingerichtet: Bitte in Railway bei BEIDEN Diensten (astro-engine und "
            "Soraya-Agent) die Variable AGENT_STATS_TOKEN mit demselben langen Zufallswert setzen.", "agent_fehlt")
    try:
        antwort = requests.get(
            engine_url() + "/internal/statistik",
            params={"tage": max(1, min(int(tage), 180))},
            headers={"X-Agent-Token": token},
            timeout=30,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Backend nicht erreichbar: {e}")
    if antwort.status_code == 401:
        raise NichtEingerichtet("Der AGENT_STATS_TOKEN im Agent passt nicht zu dem in der astro-engine.", "passt_nicht")
    if antwort.status_code == 503:
        raise NichtEingerichtet("In der astro-engine ist AGENT_STATS_TOKEN noch nicht gesetzt (mind. 24 Zeichen).",
                                "engine_fehlt")
    if antwort.status_code >= 400:
        raise RuntimeError(f"Backend-Fehler {antwort.status_code}: {antwort.text[:200]}")
    daten = antwort.json()
    if not daten.get("ok"):
        raise RuntimeError("Statistik nicht verfügbar: " + str(daten.get("error")))
    return daten.get("data") or {}
