"""
Sprach-Lektorat fuer die Posts des Tagesplans (wie das Lektorat der Engine).

Nach dem Schreiben liest ein zweiter Claude-Aufruf alle Texte eines Tages als muttersprachlicher
Korrektor: Rechtschreibung, Grammatik/Endungen, woertliche Uebersetzungen, unnatuerliche Wendungen.
Claude liefert nur eine kurze Liste "alt -> neu" (kein Neuschreiben), die hier eingesetzt wird.
Standard alle vier Sprachen. Einschraenken ueber Railway: LEKTORAT_SPRACHEN=hu (oder z. B. hu,it)
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
           "the meaning (\"Visszaírnál valakinek, akivel már rég nem beszéltél?\"). Replace anglicisms and English "
           "calques Hungarians do not say, e.g. \"kivel van ma kémia?\" -> \"Ki felé húz ma a szíved?\", "
           "\"tartsd észben\" -> \"ne feledd\", \"csinálj időt magadnak\" -> \"szánj időt magadra\", "
           "\"vibe\" -> \"hangulat\", stilted bookish phrases -> everyday warm Hungarian (\"mesébe illővé válik/varázsolja\" -> "
           "\"meghitt lesz\", \"otthonotok melegebb lesz\" (sounds like heating) -> \"ma este hazatalál a meghittség\", "
           "\"a Neptunusz álomszép fényt ad otthonodnak\" -> \"ma este minden szebbnek tűnik otthon\"); planet names only "
           "where a Hungarian reader understands why, otherwise say it simply. \"ez nem egy véletlen\" -> \"ez nem véletlen\", \"szó szerint\" used like English 'literally' "
           "(drop it), superfluous \"egy\" "
           "as English 'a/an'. Be especially strict with the short on-screen lines (titles, reel lines): they must not "
           "read like translated English captions, e.g. \"Gyors, de őszinte szerelem\" -> \"Hamar lángra lobban, de "
           "őszintén szeret\". If in doubt, rewrite the line naturally. Empty announcement lines that say nothing (\"Ma este "
           "nektek szól ez\", \"Ma ez vár rátok\") must be replaced by a concrete statement that fits the rest of the post, "
           "e.g. \"Ma este végre kimondjátok, amit érzetek\"."),
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
    roh = os.environ.get("LEKTORAT_SPRACHEN", "hu,de,en,it")
    return {s.strip().lower() for s in roh.split(",") if s.strip().lower() in SPRACHNAMEN}


def _system(sprache: str) -> str:
    name = SPRACHNAMEN[sprache]
    return (
        f"You are a meticulous native {name} copy editor for the social media posts of an astrology app. "
        f"You receive {name} texts written by an AI. The posts must read as if a native {name} speaker wrote them. "
        "Find ONLY real problems: spelling and accent errors, grammar or suffix errors, words from another "
        "language, and phrases a native speaker would find clumsy, unnatural or nonsensical (literal translations, "
        "odd word choices). Do not change content, meaning, tone, emojis, hashtags' meaning or anything that is fine. "
        "Also check the logic of every post: the first sentence (hook) must fit what follows. If the hook promises something "
        "the rest does not deliver (e.g. the hook says a scent takes three signs back in time, but the paragraphs talk about "
        "a melody, a scent and a photo), rewrite the hook so it fits all of it (e.g. \"a small memory takes you back in time\"). "
        "Also fix sentences that are grammatical but unclear or illogical. Keep the zodiac sign names at the start of a hook. "
        "If a text names a difficulty (tension, conflict, doubt, tiredness) but leaves the reader without a way forward, add "
        "one short, gentle, concrete hint (a small ritual or a sentence to say) in the same tone – minimal change, no new paragraph. "
        "The comment question at the end must be positive and easy to answer in public (zodiac sign, an emoji, yes/no, A/B, "
        "accepting a wish). Tone must be positive and uplifting: if a hook, video line or caption frames the reader through a "
        "burden, flaw or reproach (\"you carry too much\", \"you don't always have to …\", \"finally you say: enough\", "
        "\"someone asks too much of you\", \"but …\" sentences hinting at a weakness), rewrite it into the gift, strength or "
        "good news of the day with the same meaning and length. It must never ask about the reader's own life (plans, dates, people, feelings, events – e.g. 'when do you set off this week?'). If it asks for something private, personal or negative (names of people, past events, conflicts, 'when did "
        "you last …'), replace it with such a light, positive question in the same language."
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


# ---------------------------------------------------------------------------
# Muttersprachliche Neufassung (Standard: Ungarisch)
# Einzelne "alt -> neu"-Korrekturen lassen verkrampfte, uebersetzt klingende Saetze und falsche Hashtags
# stehen. Darum schreibt hier eine muttersprachliche Texterin jeden Text so neu, als waere er in der
# Sprache erdacht -- gleicher Inhalt, gleiche Laenge, gleiche Struktur. Ein Aufruf pro Tag wie bisher.
# Railway: UMSCHREIBEN_SPRACHEN=hu (leer = aus, dann gilt fuer alle Sprachen das Korrektur-Lektorat).
# ---------------------------------------------------------------------------
_NEU_HINWEISE = {
    "hu": (
        "\n\nREWRITE MODE. Rewrite every field the way a Hungarian woman in her thirties who writes popular astrology posts "
        "for Facebook would have written it in Hungarian from the start – not translated, not 'AI Hungarian'. Keep the meaning, "
        "the zodiac signs and their order, the emojis, the paragraph breaks and the closing comment question; keep every list the "
        "same length. Limits: titel max. 6 words, untertitel max. 8, hook max. 8, every einblendung max. 10 words, other fields not "
        "longer than before. If the hook equals the first line of text, keep them identical. A field that already sounds natural "
        "stays exactly as it is.\n"
        "Typical problems to remove:\n"
        "- Kitsch and over-poetic filler Hungarians find 'giccses': \"mesébe illő\", \"mesébe illővé varázsolja\", "
        "\"varázslatos\", \"álomszép fény\", \"kozmikus ölelés\", \"csodás energiák\". Use concrete, everyday pictures instead "
        "(\"ma este jólesik egy meleg takaró és egy bögre tea\").\n"
        "- Astrology phrasing: the Moon is IN a sign: \"a Hold ma a jegyedben jár\" / \"a Hold ma a Vízöntőben jár\" – never "
        "\"a Hold ma nálad jár\".\n"
        "- Number: one sign addressed = 'te' (otthonod, érzed); only a sentence addressing several signs together uses 'ti' "
        "(otthonotok, érzitek). Never mix inside one post part (e.g. \"Vízöntő, Bika, Halak: ma este otthonotok melegebb lesz\" is ok "
        "only if the following lines also use ti, otherwise \"ma este meghitt lesz az otthonod\").\n"
        "- Hashtags: only real Hungarian words people actually search, correctly spelled compounds with accents "
        "(\"#estihangulat\" not \"#esthangulat\", \"#horoszkóp\", \"#csillagjegyek\", \"#asztrológia\"); keep the count.\n"
        "Return every post with all fields, in the same order."
    ),
}

_NEU_SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "titel": {"type": "string"}, "untertitel": {"type": "string"}, "text": {"type": "string"},
            "hook": {"type": "string"}, "schluss": {"type": "string"},
            "einblendungen": {"type": "array", "items": {"type": "string"}},
            "szenen": {"type": "array", "items": {"type": "string"}},
            "bild_punkte": {"type": "array", "items": {"type": "string"}},
            "folien": {"type": "array", "items": {
                "type": "object", "properties": {"titel": {"type": "string"}, "text": {"type": "string"}},
                "required": ["titel", "text"], "additionalProperties": False}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["titel", "untertitel", "text", "hook", "schluss", "einblendungen", "szenen", "bild_punkte", "folien",
                     "hashtags"],
        "additionalProperties": False}}},
    "required": ["posts"],
    "additionalProperties": False,
}


def umschreiben_sprachen() -> set[str]:
    roh = os.environ.get("UMSCHREIBEN_SPRACHEN", "hu")
    return {s.strip().lower() for s in roh.split(",") if s.strip().lower() in _NEU_HINWEISE}


def _hashtags(p: dict) -> list[str]:
    h = p.get("hashtags")
    if isinstance(h, str):
        return [t for t in h.split() if t]
    return [str(t) for t in (h or [])]


def _eingabe(p: dict) -> dict:
    sk = p.get("skript") or {}
    return {"art": p.get("art") or "post", "titel": p.get("titel") or "", "untertitel": p.get("untertitel") or "",
            "text": p.get("text") or "", "hook": sk.get("hook") or "", "schluss": sk.get("schluss") or "",
            "einblendungen": list(sk.get("einblendungen") or []), "szenen": list(sk.get("szenen") or []),
            "bild_punkte": list(p.get("_bild_punkte") or []),
            "folien": [{"titel": f.get("titel") or "", "text": f.get("text") or ""} for f in (p.get("_folien") or [])],
            "hashtags": _hashtags(p)}


def _kurz(t) -> str:
    t = t if isinstance(t, str) else " · ".join(str(x) for x in t)
    return t if len(t) <= 70 else t[:67] + "…"


def _setze(p: dict, n: dict) -> list[str]:
    """Uebernimmt die Neufassung n in den Post p (nur passende, nicht leere Felder). Gibt 'alt → neu' zurueck."""
    alt = _eingabe(p)
    geaendert = []

    def neu_wert(feld):
        w = n.get(feld)
        a = alt[feld]
        if isinstance(a, list):
            if not isinstance(w, list) or len(w) != len(a) or (a and not all(
                    (isinstance(x, dict) and (x.get("titel") or x.get("text"))) or (isinstance(x, str) and x.strip())
                    for x in w)):
                return None
            return w if w != a else None
        if not isinstance(w, str) or not w.strip() or not a.strip() or w == a:
            return None
        return w

    for feld in ("titel", "untertitel", "text"):
        w = neu_wert(feld)
        if w is not None:
            geaendert.append(f"{_kurz(p[feld])} → {_kurz(w)}")
            p[feld] = w
    sk = p.get("skript")
    if isinstance(sk, dict):
        sk = p["skript"] = dict(sk)
        for feld in ("hook", "schluss", "einblendungen", "szenen"):
            w = neu_wert(feld)
            if w is not None:
                geaendert.append(f"{_kurz(sk.get(feld) or '')} → {_kurz(w)}")
                sk[feld] = w
        # Reel: Hook und erste Textzeile gleich halten (Facebook zeigt die erste Zeile)
        erste = (alt["text"].split("\n", 1)[0]).strip()
        if alt["hook"] and erste == alt["hook"].strip() and sk.get("hook") and p.get("text"):
            rest = p["text"].split("\n", 1)
            p["text"] = sk["hook"] + ("\n" + rest[1] if len(rest) > 1 else "")
    w = neu_wert("bild_punkte")
    if w is not None:
        geaendert.append(f"{_kurz(alt['bild_punkte'])} → {_kurz(w)}")
        p["_bild_punkte"] = w
    w = neu_wert("folien")
    if w is not None:
        p["_folien"] = [{**f, "titel": x.get("titel") or f.get("titel"), "text": x.get("text") or f.get("text")}
                        for f, x in zip(p.get("_folien") or [], w)]
        geaendert.append("Folien neu formuliert")
    w = neu_wert("hashtags")
    if w is not None:
        w = [t if t.startswith("#") else "#" + t for t in (x.strip().replace(" ", "") for x in w) if len(t) > 1]
        if len(w) == len(alt["hashtags"]) and w != alt["hashtags"]:
            geaendert.append(f"{_kurz(alt['hashtags'])} → {_kurz(w)}")
            p["hashtags"] = " ".join(w) if isinstance(p.get("hashtags"), str) else w
    if geaendert:
        p.setdefault("_lektorat", []).extend(geaendert)
    return geaendert


def umschreiben(posts: list[dict], sprache: str) -> list[str]:
    """Muttersprachliche Neufassung aller Texte eines Tages (an Ort und Stelle). Gibt die Aenderungen zurueck."""
    import json
    eingabe = json.dumps({"posts": [_eingabe(p) for p in posts]}, ensure_ascii=False, indent=1)
    antwort = frage_json(_system(sprache) + _NEU_HINWEISE[sprache], eingabe, _NEU_SCHEMA, effort="high",
                         max_tokens=24000)
    neu = antwort.get("posts") or []
    if len(neu) != len(posts):
        raise ValueError(f"Neufassung mit {len(neu)} statt {len(posts)} Einträgen")
    erledigt = []
    for p, n in zip(posts, neu):
        erledigt += _setze(p, n if isinstance(n, dict) else {})
    return erledigt


def pruefen(posts: list[dict], sprache: str) -> list[str]:
    """Korrigiert die Posts eines Tages an Ort und Stelle (nur Sprachen aus LEKTORAT_SPRACHEN).
    Gibt die Liste der Korrekturen zurueck (fuers Dashboard)."""
    if sprache not in sprachen() or not posts:
        return []
    if sprache in umschreiben_sprachen():
        try:
            return umschreiben(posts, sprache)
        except Exception as e:   # dann wenigstens das normale Korrektur-Lektorat
            log.warning("Neufassung %s fehlgeschlagen, nur Korrekturen: %s", sprache, e)
    bloecke = []
    for i, p in enumerate(posts, 1):
        bloecke.append(f"--- Post {i} ({p.get('art') or 'post'}) ---\n" + "\n".join(_texte(p)))
    try:
        antwort = frage_json(_system(sprache), "\n\n".join(bloecke), _SCHEMA, effort="high", max_tokens=24000)
        return anwenden(posts, antwort.get("korrekturen") or [])
    except Exception as e:   # Lektorat darf den Tagesplan nie aufhalten
        log.warning("Lektorat %s fehlgeschlagen: %s", sprache, e)
        return []
