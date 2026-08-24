"""
Content-Agent
Ruft ein Sprachmodell (ueber OpenRouter) auf und laesst fertige
Social-Media-Posts fuer die Soraya-App schreiben.

Rueckgabe: eine Liste von Posts, jeder mit:
  platform  -> "instagram" | "facebook" | "linkedin"
  text      -> der fertige Post-Text
  hashtags  -> Liste passender Hashtags
"""

import os
import json
import requests

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# Guenstiges, gutes Modell als Standard. Kannst du in Railway ueberschreiben.
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# So "denkt" der Agent. Hier steckt die Marken-Stimme von Soraya drin.
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


def erstelle_posts(thema: str | None = None, anzahl: int = 3) -> list[dict]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY fehlt. Bitte in Railway unter Variables setzen."
        )

    thema_text = (
        f'Das Thema fuer die Posts ist: "{thema}".'
        if thema
        else "Waehle selbst ein passendes, ansprechendes Astro-/Horoskop-Thema."
    )

    user_prompt = (
        f"Schreibe {anzahl} Social-Media-Posts fuer Soraya. {thema_text} "
        f"Verteile sie sinnvoll auf die Plattformen instagram, facebook und linkedin "
        f"(LinkedIn etwas sachlicher, Instagram/Facebook emotionaler). "
        f"Jeder Post mit 3 bis 6 passenden Hashtags."
    )

    antwort = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.8,
        },
        timeout=90,
    )
    antwort.raise_for_status()
    inhalt = antwort.json()["choices"][0]["message"]["content"]

    # Sicherheitsnetz: falls doch ```json ... ``` drumherum kommt, entfernen.
    inhalt = inhalt.strip()
    if inhalt.startswith("```"):
        inhalt = inhalt.strip("`")
        if inhalt.lstrip().lower().startswith("json"):
            inhalt = inhalt.lstrip()[4:]

    daten = json.loads(inhalt)
    return daten.get("posts", [])
