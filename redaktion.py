"""
Redaktion: was der Tagesplan heute erzaehlt -- und ob ein Post gut genug zum Posten ist

1. Wochenthema: Jeder Wochentag hat ein eigenes Format (Abwechslung haelt Follower,
   die Plattformen belohnen Speichern, Teilen und Kommentare). Grosse Himmels-
   ereignisse (Neu-/Vollmond, Rueckläufigkeit beginnt) haben Vorrang.
2. Handlungsaufforderung: wechselt zwischen echten Funktionen der App.
3. Qualitaetspruefung: Laenge, Hashtags, Sprache, heikle Versprechen. Posts mit Befund
   gehen beim automatischen Posten erst raus, wenn du sie freigibst.
4. Lernen: Posts, deren Link die meisten Besucher gebracht hat, fliessen als Vorbild ein.
"""

from __future__ import annotations

import re
import time
from datetime import date

# ---------------------------------------------------------------------------
# 1. Wochenthemen (Montag = 0)
# ---------------------------------------------------------------------------
WOCHENTHEMEN = [
    {"name": "Deine Woche",
     "auftrag": "Ausblick auf die neue Woche: welche Stimmung die Mondphase und die kommenden Ereignisse "
                "(Neu-/Vollmond, Rückläufigkeiten aus den Daten) bringen, mit einem konkreten Tipp für die Woche."},
    {"name": "Sternzeichen im Fokus",
     "auftrag": "Drei Sternzeichen, die der heutige Himmel besonders betrifft – astrologisch begründet: das Zeichen, "
                "in dem der Mond steht, und zwei passende (gleiches Element oder Gegenzeichen). Jedes Zeichen mit einem "
                "konkreten Satz. Schließe mit einer Kommentar-Aufforderung (z. B. „Schreib dein Zeichen in die Kommentare“)."},
    {"name": "Liebe & Beziehung",
     "auftrag": "Was der heutige Himmel für Liebe, Freundschaft und Nähe bedeutet: ein ehrlicher, alltagsnaher Impuls "
                "für Paare und Singles."},
    {"name": "Astro-Wissen",
     "auftrag": "Erkläre einen Begriff, den der heutige Himmel zeigt (z. B. Mondzeichen, Mondphase, Rückläufigkeit, "
                "Sonnenzeichen vs. Mondzeichen) – einfach, überraschend, mit einem Aha-Moment. Lädt zum Speichern ein."},
    {"name": "Ritual",
     "auftrag": "Ein kleines, praktisches Ritual oder eine Journaling-Frage passend zur heutigen Mondphase "
                "(höchstens 3 einfache Schritte). Lädt zum Speichern ein."},
    {"name": "Mitmachen",
     "auftrag": "Ein Mitmach-Post: eine spielerische Frage, ein Mini-Quiz oder „Welches Zeichen …?“ zum heutigen Himmel. "
                "Ziel sind Kommentare und Antworten."},
    {"name": "Rückblick & Vorschau",
     "auftrag": "Ruhige Sonntags-Reflexion: was die vergangene Woche bewegt hat (nur allgemein, nichts erfinden) und "
                "worauf man sich laut den Daten in der nächsten Woche freuen kann."},
]

# Handlungsaufforderungen -- nur echte Funktionen der App
AUFFORDERUNGEN = [
    {"schluessel": "mondzeichen",
     "auftrag": "Finde dein Sonnen- und Mondzeichen in Sekunden – gratis, ohne Konto."},
    {"schluessel": "partner",
     "auftrag": "Partner-Vergleich: wie gut ihr zusammenpasst, in Prozent."},
    {"schluessel": "horoskop",
     "auftrag": "Dein persönliches Tageshoroskop aus deinem eigenen Geburtshoroskop."},
    {"schluessel": "chat",
     "auftrag": "Stell Soraya deine Frage im Astro-Chat."},
]
_THEMA_AUFFORDERUNG = {0: "horoskop", 1: "mondzeichen", 2: "partner", 3: "mondzeichen", 4: "horoskop",
                       5: "chat", 6: "horoskop"}


def wochenthema(tag: date, info: dict) -> dict:
    """{"name", "auftrag", "aufforderung", "anlass"} -- grosse Ereignisse haben Vorrang."""
    thema = dict(WOCHENTHEMEN[tag.weekday()])
    anlass = ""
    for name, schluessel in (("Neumond", "neumond"), ("Vollmond", "vollmond")):
        e = info.get(schluessel)
        if e and 0 <= e.get("in_tagen", 99) <= 1:
            anlass = f"{name} {'heute' if e['in_tagen'] <= 0 else 'morgen'}"
    if not anlass:
        for r in info.get("bald_ruecklaeufig") or []:
            if r.get("ab") and r["ab"] in (info.get("datum_kurz"),):
                anlass = f"{r['planet']} wird heute rückläufig"
    if anlass:
        thema = {"name": f"Großes Ereignis: {anlass}",
                 "auftrag": f"Heute ist das Ereignis das Hauptthema: {anlass}. Was es bedeutet, wie man es nutzt, "
                            f"worauf man achten sollte – konkret und alltagsnah."}
    key = _THEMA_AUFFORDERUNG[tag.weekday()]
    thema["aufforderung"] = next(a for a in AUFFORDERUNGEN if a["schluessel"] == key)
    thema["anlass"] = anlass
    return thema


def thema_text(thema: dict, link_in_bio: str) -> str:
    return (f"Heutiges Format: {thema['name']}\n{thema['auftrag']}\n"
            f"Handlungsaufforderung heute (sinngemäß, in der Sprache des Posts, mit „{link_in_bio}“): "
            f"{thema['aufforderung']['auftrag']}")


# ---------------------------------------------------------------------------
# 3. Qualitaetspruefung (ohne zusaetzliche KI-Kosten)
# ---------------------------------------------------------------------------
_HEIKEL = re.compile(
    r"\b(garantiert|garantie|guarantee[ds]?|100\s?%|heilt|heilen|cure[ds]?|diagnos\w*|krankheit\w*|disease\w*|"
    r"lotto|lottery|reich werden|get rich|gewinnspiel|giveaway)\b", re.IGNORECASE)
_DEUTSCH_IN_FREMD = re.compile(r"\b(und|nicht|deine?n?|für|heute|Mond|Sonne|Sternzeichen|Liebe|Woche)\b")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_GRENZEN = {"post": (40, 230), "reel": (5, 70), "story": (4, 50)}


def _woerter(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def pruefe_post(post: dict, sprache: str) -> list[str]:
    """Liste von Befunden (leer = in Ordnung)."""
    befunde = []
    art = post.get("art") or "post"
    alles = " ".join(str(post.get(k) or "") for k in ("titel", "untertitel", "text"))
    sk = post.get("skript") or {}
    if art == "reel":
        alles += " " + " ".join([sk.get("hook") or "", sk.get("schluss") or ""] + list(sk.get("einblendungen") or []))
    if _woerter(post.get("titel")) == 0:
        befunde.append("Überschrift fehlt")
    elif _woerter(post.get("titel")) > 8:
        befunde.append("Überschrift zu lang (max. 8 Wörter)")
    if _woerter(post.get("untertitel")) > 14:
        befunde.append("Unterzeile zu lang")
    lo, hi = _GRENZEN.get(art, (1, 300))
    n = _woerter(post.get("text"))
    if n < lo:
        befunde.append(f"Text zu kurz ({n} Wörter)")
    if n > hi:
        befunde.append(f"Text zu lang ({n} Wörter, max. {hi})")
    tags = [t for t in re.split(r"\s+", post.get("hashtags") or "") if t] if isinstance(post.get("hashtags"), str) \
        else list(post.get("hashtags") or [])
    if art != "story" and not 3 <= len(tags) <= 10:
        befunde.append(f"{len(tags)} Hashtags (3 bis 10 sinnvoll)")
    if any(not t.startswith("#") or len(t) < 3 for t in tags):
        befunde.append("Hashtag ohne # oder zu kurz")
    if art == "reel":
        if not (sk.get("hook") or "").strip():
            befunde.append("Reel ohne Hook")
        elif _woerter(sk.get("hook")) > 12:
            befunde.append("Hook zu lang (max. 12 Wörter)")
        ein = list(sk.get("einblendungen") or [])
        if not 2 <= len(ein) <= 4:
            befunde.append("Reel braucht 2 bis 4 Einblendungen")
        if any(_woerter(e) > 10 for e in ein):
            befunde.append("Einblendung zu lang (max. 10 Wörter)")
    heikel = sorted({m.group(0).lower() for m in _HEIKEL.finditer(alles)})
    if heikel:
        befunde.append("Heikle Versprechen: " + ", ".join(heikel))
    if _URL.search(alles):
        befunde.append("Enthält einen Link (der Agent fügt Links selbst ein)")
    if sprache != "de":
        reste = sorted({m.group(0) for m in _DEUTSCH_IN_FREMD.finditer(alles)})
        if reste:
            befunde.append("Deutsche Wörter im Text: " + ", ".join(reste))
    return befunde


def schwer(befunde: list[str]) -> bool:
    """Befunde, bei denen der Tagesplan einmal neu geschrieben wird."""
    return any(b.startswith(("Heikle", "Deutsche Wörter", "Enthält einen Link", "Reel ohne Hook", "Überschrift fehlt"))
               for b in befunde)


# ---------------------------------------------------------------------------
# 4. Lernen aus der Wirkung
# ---------------------------------------------------------------------------
_CACHE = {"zeit": 0.0, "daten": None}


def gut_angekommen(lade_post, sprache: str, statistik=None, min_besuche: int = 3) -> list[str]:
    """Bis zu 3 eigene Posts, deren Link am meisten Besucher gebracht hat (letzte 30 Tage)."""
    try:
        if statistik is None:
            if time.time() - _CACHE["zeit"] > 3600:
                from wirkung import hole_statistik
                _CACHE.update(zeit=time.time(), daten=hole_statistik(30))
            statistik = _CACHE["daten"] or {}
        quellen = statistik.get("quellen") or {}
    except Exception:
        return []
    rangliste = []
    for code, q in quellen.items():
        if not re.fullmatch(r"p\d+", code or ""):
            continue
        besuche = int((q.get("schritte") or {}).get("besuch") or 0)
        if besuche < min_besuche:
            continue
        try:
            post = lade_post(int(code[1:]))
        except Exception:
            post = None
        if post and post.get("sprache") == sprache and post.get("titel"):
            rangliste.append((besuche, int(q.get("konten") or 0), post))
    rangliste.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return [f"„{p['titel']}“ ({p.get('art')}, {b} Besuche{f', {k} neue Konten' if k else ''})"
            for b, k, p in rangliste[:3]]
