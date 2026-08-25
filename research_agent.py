"""
Recherche-Agent (Zielgruppen-Analyse)
Nimmt gesammelte Web-Rechercheergebnisse und laesst Claude daraus ein
verstaendliches Zielgruppen-Profil fuer Soraya machen.
"""

import os
import json
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Du bist Marktforscher fuer die App "Soraya Luxury Astrology Guide"
(personalisierte Horoskope, Synastrie/Partnervergleich, KI-Astrologe-Chat;
elegant, hochwertig, deutschsprachiger Markt).

Du bekommst echte Rechercheergebnisse aus mehreren Quellen: Google-Suchtreffer
und haeufige Fragen, Instagram- und TikTok-Beitraege, Reddit-Diskussionen und
Bewertungen von Astrologie-Apps im Play Store. Jede Quelle ist markiert.

Daraus erstellst du ein praxistaugliches Zielgruppen-Profil fuer EINEN Bereich.

Regeln:
- Stuetze dich nur auf die gelieferten Daten. Erfinde nichts.
- Wenn nur wenige Quellen Daten geliefert haben, sag das unter "unsicher".
- Nutze die Staerken der Quellen: Google zeigt, was Menschen suchen;
  Social Media zeigt, welche Tonalitaet ankommt; Reddit zeigt ehrliche
  Meinungen; App-Bewertungen zeigen, was Nutzer an anderen Apps stoert.
- Schreibe auf Deutsch, konkret, ohne Marketing-Floskeln.

Antworte AUSSCHLIESSLICH mit gueltigem JSON, ohne Erklaerung, ohne Markdown:

{
  "bereich": "Kurzname des untersuchten Bereichs",
  "wer_sind_sie": "2-4 Saetze: wer diese Menschen sind, Lebenssituation, Motivation",
  "beschaeftigt_sie": ["konkrete Fragen oder Sorgen, die sie umtreiben"],
  "wuensche": ["was sie sich erhoffen"],
  "sprache": ["Begriffe und Formulierungen, die sie selbst benutzen"],
  "content_ideen": ["konkrete Post-Ideen, die bei ihnen zuenden"],
  "worauf_achten": ["was man vermeiden sollte, Skepsis, Fallstricke"],
  "luecke_am_markt": ["was Nutzer an bestehenden Apps vermissen oder kritisieren"],
  "unsicher": ["was die Daten NICHT hergeben"]
}
"""


def analysiere_zielgruppe(bereich: str, recherche: str) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY fehlt.")
    if not recherche.strip():
        raise RuntimeError("Die Recherche hat keine Ergebnisse geliefert.")

    user_prompt = (
        f'Untersuchter Bereich: "{bereich}".\n\n'
        f"Hier die Rechercheergebnisse aus dem Netz:\n---\n{recherche}\n---\n\n"
        f"Erstelle daraus das Zielgruppen-Profil."
    )

    antwort = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=120,
    )
    if antwort.status_code >= 400:
        raise RuntimeError(f"Claude-API Fehler {antwort.status_code}: {antwort.text[:300]}")

    teile = []
    for block in antwort.json().get("content", []):
        if isinstance(block, dict) and "text" in block:
            teile.append(block["text"])
    inhalt = "".join(teile).strip()

    if inhalt.startswith("```"):
        inhalt = inhalt.strip("`")
        if inhalt.lstrip().lower().startswith("json"):
            inhalt = inhalt.lstrip()[4:]
        inhalt = inhalt.strip()

    try:
        return json.loads(inhalt)
    except json.JSONDecodeError:
        raise RuntimeError("Claude lieferte kein sauberes JSON: " + inhalt[:400])
