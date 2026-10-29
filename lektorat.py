"""
Sprach-Lektorat fuer die Posts des Tagesplans (wie das Lektorat der Engine).

Nach dem Schreiben liest ein zweiter Claude-Aufruf alle Texte eines Tages als muttersprachlicher
Korrektor: Rechtschreibung, Grammatik/Endungen, woertliche Uebersetzungen, unnatuerliche Wendungen.
Claude liefert nur eine kurze Liste "alt -> neu" (kein Neuschreiben), die hier eingesetzt wird.
Standard nur Ungarisch (Facebook). Weitere Sprachen ueber Railway: LEKTORAT_SPRACHEN=hu,it
Kosten: ein kleiner Aufruf pro Sprache und Tag. Fehler -> Texte bleiben unveraendert.
"""

import logging
import os

from claude import frage_json

log = logging.getLogger("lektorat")

SPRACHNAMEN = {"en": "English", "hu": "Hungarian", "it": "Italian", "de": "German"}
MAX_KORREKTUREN = 30

_HINWEISE = {
    "hu": (" Hungarian specifics: check accents (á/é/í/ó/ö/ő/ú/ü/ű) and long vs. short vowels, vowel harmony "
           "in suffixes, definite vs. indefinite conjugation, word order and natural collocations. Use the informal "
           "'te' form throughout. Typical AI mistakes to fix: missing or wrong accents (\"ritule\" -> \"rituálé\"), "
           "word-for-word translations from English/German, invented compound words. Zodiac signs: Kos, Bika, Ikrek, "
           "Rák, Oroszlán, Szűz, Mérleg, Skorpió, Nyilas, Bak, Vízöntő, Halak; Hold, Nap, Telihold, Újhold. "
           "Read every sentence as a Hungarian woman on Instagram would: if it is grammatical but strange or illogical "
           "(e.g. \"Visszaírnál valakinek, akit rég nem akartál?\"), replace the whole sentence with a natural one that keeps "
           "the meaning (\"Visszaírnál valakinek, akivel már rég nem beszéltél?\")."),
}

_SCHEMA = {
    "type": "object",
    "properties": {"korrekturen": {"type": "array", "items": {
        "type": "object",
        "properties": {"alt": {"type": "string"}, "neu": {"type": "string"}},
        "required": ["alt", "neu"], "additionalProperties": False}}},
    "required": ["korrekturen"],
    "additionalProperties": False,
}


def sprachen() -> set[str]:
    roh = os.environ.get("LEKTORAT_SPRACHEN", "hu")
    return {s.strip().lower() for s in roh.split(",") if s.strip().lower() in SPRACHNAMEN}


def _system(sprache: str) -> str:
    name = SPRACHNAMEN[sprache]
    return (
        f"You are a meticulous native {name} copy editor for the social media posts of an astrology app. "
        f"You receive {name} texts written by an AI. The posts must read as if a native {name} speaker wrote them. "
        "Find ONLY real problems: spelling and accent errors, grammar or suffix errors, words from another "
        "language, and phrases a native speaker would find clumsy, unnatural or nonsensical (literal translations, "
        "odd word choices). Do not change content, meaning, tone, emojis, hashtags' meaning or anything that is fine."
        + _HINWEISE.get(sprache, "") +
        "\n\nEvery correction: \"alt\" = the exact passage copied character for character from the texts (2-15 words, "
        "a single word only if it is unique; a whole sentence when it must be rewritten), \"neu\" = the corrected passage. At most "
        f"{MAX_KORREKTUREN} corrections; an empty list if everything is fine."
    )


def _texte(p: dict) -> list[str]:
    """Alle Texte eines Posts, die im Bild, im Reel oder im Beitrag erscheinen."""
    sk = p.get("skript") or {}
    werte = [p.get("titel"), p.get("untertitel"), p.get("text"), sk.get("hook"), sk.get("schluss")]
    werte += list(sk.get("szenen") or []) + list(sk.get("einblendungen") or []) + list(p.get("_bild_punkte") or [])
    for f in p.get("_folien") or []:
        werte += [f.get("titel"), f.get("text")]
    return [w for w in werte if isinstance(w, str) and w.strip()]


def _ersetze(wert, alt: str, neu: str):
    if isinstance(wert, str):
        return wert.replace(alt, neu) if alt in wert else wert
    if isinstance(wert, list):
        return [_ersetze(w, alt, neu) for w in wert]
    if isinstance(wert, dict):
        return {k: _ersetze(v, alt, neu) for k, v in wert.items()}
    return wert


_FELDER = ("titel", "untertitel", "text", "skript", "_bild_punkte", "_folien")


def anwenden(posts: list[dict], korrekturen: list) -> list[str]:
    """Setzt die Korrekturen in alle Textfelder ein (nicht in Hashtags/Links). Gibt die angewandten zurueck."""
    erledigt = []
    for k in (korrekturen or [])[:MAX_KORREKTUREN]:
        alt, neu = (k or {}).get("alt"), (k or {}).get("neu")
        if not isinstance(alt, str) or not isinstance(neu, str) or not alt.strip() or alt == neu:
            continue
        if len(alt.strip()) < 3 or len(neu) > 3 * len(alt) + 40:   # kein Umschreiben ganzer Passagen
            continue
        treffer = False
        for p in posts:
            hier = False
            for f in _FELDER:
                if f in p and p[f] is not None:
                    neu_wert = _ersetze(p[f], alt, neu)
                    if neu_wert != p[f]:
                        p[f], hier = neu_wert, True
            if hier:   # je Post merken, was korrigiert wurde (Dashboard)
                p.setdefault("_lektorat", []).append(f"{alt} → {neu}")
                treffer = True
        if treffer:
            erledigt.append(f"{alt} → {neu}")
    return erledigt


def pruefen(posts: list[dict], sprache: str) -> list[str]:
    """Korrigiert die Posts eines Tages an Ort und Stelle (nur Sprachen aus LEKTORAT_SPRACHEN).
    Gibt die Liste der Korrekturen zurueck (fuers Dashboard)."""
    if sprache not in sprachen() or not posts:
        return []
    bloecke = []
    for i, p in enumerate(posts, 1):
        bloecke.append(f"--- Post {i} ({p.get('art') or 'post'}) ---\n" + "\n".join(_texte(p)))
    try:
        antwort = frage_json(_system(sprache), "\n\n".join(bloecke), _SCHEMA, effort="medium", max_tokens=6000)
        return anwenden(posts, antwort.get("korrekturen") or [])
    except Exception as e:   # Lektorat darf den Tagesplan nie aufhalten
        log.warning("Lektorat %s fehlgeschlagen: %s", sprache, e)
        return []
