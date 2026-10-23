"""
Content-Agent
Laesst Claude fertige Social-Media-Posts fuer die Soraya-App schreiben,
in der gewuenschten Sprache (de, en, hu, it). Jeder Post bringt eine kurze
Bild-Ueberschrift mit, damit das Dashboard daraus ein Post-Bild machen kann.
"""

from claude import frage_json
from sprachen import sprach_anweisung

SYSTEM_PROMPT = """Du bist der Social-Media-Texter der App "Soraya Luxury Astrology Guide".

Über Soraya:
- Eine luxuriöse Astrologie-App mit persönlichem Tageshoroskop aus dem eigenen
  Geburtshoroskop, Synastrie (Partner-Vergleich in Prozent) und einem KI-Chat.
- Ohne Konto zeigt sie in Sekunden Sonnen- und Mondzeichen und das Tageshoroskop.
- Verfügbar auf Deutsch, Englisch, Ungarisch und Italienisch.
- Ton: elegant, warm, edel, ein bisschen mystisch — nie billig oder reißerisch.
- Zielgruppe: Menschen, die sich für Astrologie, Selbstreflexion und
  persönliche Entwicklung interessieren.

Deine Aufgabe: fertige, sofort postbare Social-Media-Posts schreiben.
Jeder Post funktioniert eigenständig und macht Lust auf die App, ohne
aufdringlich zu wirken. Keine Heilsversprechen, keine Angstmacherei.

Zu jedem Post gehören:
- "titel": Bild-Überschrift, höchstens 6 Wörter, ohne Hashtags und Emojis.
- "untertitel": eine kurze Zeile unter der Überschrift, höchstens 12 Wörter.
- "text": der Post-Text, 40 bis 90 Wörter, ohne Füllsätze: erste Zeile ein kurzer Hook (höchstens 100 Zeichen,
  Instagram kürzt danach), dann eine Leerzeile und kurze Absätze mit 1–2 Sätzen, durch Leerzeilen
  getrennt; höchstens 2 Emojis.
- "hashtags": 3 bis 5 passende Hashtags in der Sprache des Posts, mit # (Instagram nimmt höchstens 5)."""

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string", "enum": ["instagram", "facebook", "linkedin", "tiktok"]},
        "titel": {"type": "string"},
        "untertitel": {"type": "string"},
        "text": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["platform", "titel", "untertitel", "text", "hashtags"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": POST_SCHEMA}},
    "required": ["posts"],
    "additionalProperties": False,
}


def erstelle_posts(
    thema: str | None = None,
    anzahl: int = 3,
    kontext: str | None = None,
    sprache: str = "de",
) -> list[dict]:
    anzahl = max(1, min(int(anzahl), 6))
    thema_text = (
        f'Das Thema für die Posts ist: "{thema}".'
        if thema
        else "Wähle selbst ein passendes, ansprechendes Astro-/Horoskop-Thema."
    )
    kontext_text = ""
    if kontext:
        kontext_text = (
            "\n\nNutze folgenden Inhalt als Grundlage/Inspiration für die Posts "
            "(fasse zusammen, übernimm Ideen, aber schreibe eigenständig):\n"
            f"---\n{kontext}\n---"
        )
    frage = (
        f"Schreibe {anzahl} Social-Media-Posts für Soraya. {thema_text} "
        "Verteile sie sinnvoll auf die Plattformen instagram, facebook und linkedin "
        "(LinkedIn etwas sachlicher, Instagram/Facebook emotionaler)."
        f"{kontext_text}\n\n{sprach_anweisung(sprache)}"
    )
    daten = frage_json(SYSTEM_PROMPT, frage, SCHEMA, effort="medium")
    posts = daten.get("posts", [])[:anzahl]
    for p in posts:
        p["sprache"] = sprache
    return posts
