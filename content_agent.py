"""
Content-Agent
Spricht DIREKT mit Claude (Anthropic API) und laesst fertige
Social-Media-Posts fuer die Soraya-App schreiben.
"""

import os
import json
import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Du bist der Social-Media-Texter der App "Soraya Luxury Astrology Guide".

Ueber Soraya:
- Eine luxurioese Astrologie-App mit personalisierten Horoskopen, Synastrie
  (Partner-Vergleich) und einem KI-Chat fuer individuelle Astro-Fragen.
- Ton: elegant, warm, edel, ein bisschen mystisch — nie billig oder reisserisch.
- Zielgruppe: Menschen, die sich fuer Astrologie, Selbstreflexion und
  persoenliche Entwicklung interessieren.

Deine Aufgabe: fertige, sofort postbare Social-Media-Posts schreiben.
Jeder Post muss eigenstaendig funktionieren und Lust auf die App machen,
ohne aufdringlich zu wirken.

WICHTIG: Antworte AUSSCHLIESSLICH mit gueltigem JSON, ohne Erklaerung,
ohne Markdown, ohne ```-Zeichen. Format:

{
  "posts": [
    {
      "platform": "instagram",
      "text": "Der fertige Post-Text ...",
      "hashtags": ["#astrologie", "#horoskop"]
    }
  ]
}
"""


def erstelle_posts(
    thema: str | None = None,
    anzahl: int = 3,
    kontext: str | None = None,
) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY fehlt. Bitte in Railway unter Variables setzen."
        )

    thema_text = (
        f'Das Thema fuer die Posts ist: "{thema}".'
        if thema
        else "Waehle selbst ein passendes, ansprechendes Astro-/Horoskop-Thema."
    )

    kontext_text = ""
    if kontext:
        kontext_text = (
            "\n\nNutze folgenden Inhalt als Grundlage/Inspiration fuer die Posts "
            "(fasse zusammen, uebernimm Ideen, aber schreibe eigenstaendig):\n"
            f"---\n{kontext}\n---"
        )

    user_prompt = (
        f"Schreibe {anzahl} Social-Media-Posts fuer Soraya. {thema_text} "
        f"Verteile sie sinnvoll auf die Plattformen instagram, facebook und linkedin "
        f"(LinkedIn etwas sachlicher, Instagram/Facebook emotionaler). "
        f"Jeder Post mit 3 bis 6 passenden Hashtags."
        f"{kontext_text}"
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
            "max_tokens": 1500,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=90,
    )

    # Klartext-Fehler statt anonymem 500:
    if antwort.status_code >= 400:
        raise RuntimeError(
            f"Claude-API Fehler {antwort.status_code}: {antwort.text}"
        )

    inhalt = antwort.json()["content"][0]["text"]

    inhalt = inhalt.strip()
    if inhalt.startswith("```"):
        inhalt = inhalt.strip("`")
        if inhalt.lstrip().lower().startswith("json"):
            inhalt = inhalt.lstrip()[4:]

    try:
        daten = json.loads(inhalt)
    except json.JSONDecodeError:
        raise RuntimeError(
            "Claude hat kein sauberes JSON geliefert. Antwort war: "
            + inhalt[:500]
        )

    return daten.get("posts", [])
