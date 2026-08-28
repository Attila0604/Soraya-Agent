"""
Web-Recherche ueber Claude — ohne zweiten Dienst.
Claude sucht selbst im Netz und sammelt die Fundstuecke.
Laeuft ueber denselben Anthropic-Key, den der Content-Agent nutzt.
"""

import os
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SAMMEL_PROMPT = """Du bist Rechercheur. Deine Aufgabe ist SAMMELN, nicht analysieren.

Suche im Netz zu den vorgegebenen Fragen und notiere, was du findest:
- Welche Fragen stellen Menschen zu diesem Thema?
- Welche Formulierungen und Begriffe benutzen sie selbst?
- Welche Sorgen, Wuensche oder Kritikpunkte tauchen auf?
- Was schreiben Foren, Ratgeber und Erfahrungsberichte?

Gib eine nuechterne Liste von Fundstuecken zurueck, Stichpunkt fuer Stichpunkt.
Keine Zusammenfassung, keine Empfehlungen, keine eigene Meinung.
Wenn du zu etwas nichts findest, schreib das dazu."""


def quelle_websuche(begriffe: list[str], land: str = "at", max_zeichen: int = 9000) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY fehlt.")

    fragen = "\n".join(f"- {b}" for b in begriffe if b.strip())
    land_text = {"at": "Österreich", "de": "Deutschland", "ch": "Schweiz"}.get(land, land)

    antwort = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4000,
            "system": SAMMEL_PROMPT,
            "messages": [{
                "role": "user",
                "content": (
                    f"Markt: deutschsprachiger Raum, Schwerpunkt {land_text}.\n\n"
                    f"Recherchiere zu diesen Fragen:\n{fragen}"
                ),
            }],
            "tools": [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 6,
            }],
        },
        timeout=180,
    )
    if antwort.status_code >= 400:
        raise RuntimeError(f"Websuche Fehler {antwort.status_code}: {antwort.text[:300]}")

    teile = []
    for block in antwort.json().get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            teile.append(block.get("text", ""))
    inhalt = "\n".join(t for t in teile if t.strip()).strip()

    if not inhalt:
        raise RuntimeError("Die Websuche hat nichts geliefert.")
    return inhalt[:max_zeichen]
