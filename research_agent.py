"""
Recherche-Agent (Zielgruppen-Analyse)
Nimmt gesammelte Rechercheergebnisse und laesst Claude daraus ein
verstaendliches Zielgruppen-Profil fuer Soraya machen.
"""

from claude import frage_json

SYSTEM_PROMPT = """Du bist Marktforscher für die App "Soraya Luxury Astrology Guide"
(personalisierte Horoskope, Synastrie/Partnervergleich, KI-Astrologe-Chat;
elegant, hochwertig; auf Deutsch, Englisch, Ungarisch und Italienisch).

Du bekommst echte Rechercheergebnisse aus bis zu drei Quellen: einer Websuche
(Suchtreffer, Ratgeber, Foren, häufige Fragen), Reddit-Diskussionen und
Bewertungen von Astrologie-Apps im Play Store. Jede Quelle ist markiert.

Daraus erstellst du ein praxistaugliches Zielgruppen-Profil für EINEN Bereich.

Regeln:
- Stütze dich nur auf die gelieferten Daten. Erfinde nichts.
- Wenn nur wenige Quellen Daten geliefert haben, sag das unter "unsicher".
- Nutze die Stärken der Quellen: Die Websuche zeigt, was Menschen suchen und
  fragen; Reddit zeigt ehrliche Meinungen; App-Bewertungen zeigen, was Nutzer
  an anderen Apps stört.
- Schreibe auf Deutsch, konkret, ohne Marketing-Floskeln.
- "antwort_auf_frage": Wenn eine zusätzliche Frage gestellt wird, beantworte
  sie in 2-4 Sätzen nur auf Basis der Daten. Ohne Frage bleibt das Feld leer ("")."""

_LISTE = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "bereich": {"type": "string"},
        "wer_sind_sie": {"type": "string"},
        "beschaeftigt_sie": _LISTE,
        "wuensche": _LISTE,
        "sprache": _LISTE,
        "content_ideen": _LISTE,
        "worauf_achten": _LISTE,
        "luecke_am_markt": _LISTE,
        "unsicher": _LISTE,
        "antwort_auf_frage": {"type": "string"},
    },
    "required": ["bereich", "wer_sind_sie", "beschaeftigt_sie", "wuensche", "sprache",
                 "content_ideen", "worauf_achten", "luecke_am_markt", "unsicher",
                 "antwort_auf_frage"],
    "additionalProperties": False,
}


def analysiere_zielgruppe(bereich: str, recherche: str, eigene_frage: str = "") -> dict:
    if not recherche.strip():
        raise RuntimeError("Die Recherche hat keine Ergebnisse geliefert.")

    frage_text = ""
    if eigene_frage.strip():
        frage_text = (
            'Zusätzliche Frage, bitte im Feld "antwort_auf_frage" beantworten:\n'
            f"{eigene_frage.strip()}\n\n"
        )
    frage = (
        f'Untersuchter Bereich: "{bereich}".\n\n'
        f"Hier die Rechercheergebnisse aus dem Netz:\n---\n{recherche}\n---\n\n"
        f"{frage_text}"
        "Erstelle daraus das Zielgruppen-Profil."
    )
    profil = frage_json(SYSTEM_PROMPT, frage, SCHEMA, effort="high")
    if not profil.get("antwort_auf_frage"):
        profil.pop("antwort_auf_frage", None)
    return profil
