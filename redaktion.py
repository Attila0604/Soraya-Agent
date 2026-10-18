"""
Redaktion: was der Tagesplan heute erzaehlt -- und ob ein Post gut genug zum Posten ist

1. Wochenthema: Jeder Wochentag hat ein eigenes Format (Abwechslung haelt Follower,
   die Plattformen belohnen Speichern, Teilen und Kommentare). Grosse Himmels-
   ereignisse (Neu-/Vollmond, Rueckläufigkeit beginnt) haben Vorrang.
2. Handlungsaufforderung: wechselt zwischen echten Funktionen der App.
3. Qualitaetspruefung: Laenge, Hashtags, Sprache, heikle Versprechen. Posts mit Befund
   gehen beim automatischen Posten erst raus, wenn du sie freigibst.
4. Lernen: Punkte je Post aus Link-Besuchen, neuen Konten, Reichweite und Facebook-Reaktionen. Die besten
   Posts (auch aus anderen Sprachen) fliessen als Vorbild ein, dazu welche Formate am besten ankommen.
5. Selbst-Tests: Jeder Tagesplan probiert einen Hook-Stil und eine Handlungsaufforderung aus. Was mehr
   Punkte (bzw. Besuche) bringt, kommt danach oefter dran; ab und zu wird weiter Neues probiert.
"""

from __future__ import annotations

import random
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
    text = (f"Heutiges Format: {thema['name']}\n{thema['auftrag']}\n"
            f"Handlungsaufforderung heute (sinngemäß, in der Sprache des Posts, mit „{link_in_bio}“): "
            f"{thema['aufforderung']['auftrag']}")
    if thema.get("hook_stil"):
        text += f"\nHook-Stil heute (für Feed-Post und Reel): {thema['hook_stil']['auftrag']}"
    return text


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


SPRACH_NAME = {"de": "DE", "en": "EN", "hu": "HU", "it": "IT"}


def punkte(besuche: int = 0, konten: int = 0, reaktionen: int = 0, kommentare: int = 0, geteilt: int = 0,
           reichweite: int = 0) -> int:
    """Eine Zahl fuer "wie gut kam der Post an": neue Konten zaehlen am meisten, dann Teilen,
    Kommentare, Besuche ueber den Link und Gefaellt-mir; je 100 erreichte Menschen 1 Punkt."""
    return (int(besuche) * 2 + int(konten) * 15 + int(reaktionen) + int(kommentare) * 3 + int(geteilt) * 4
            + int(reichweite or 0) // 100)


def _statistik():
    if time.time() - _CACHE["zeit"] > 3600:
        from wirkung import hole_statistik
        _CACHE.update(zeit=time.time(), daten=hole_statistik(30))
    return _CACHE["daten"] or {}


def bewerte(lade_post, statistik=None, lern_posts=None) -> list[dict]:
    """Alle Posts der letzten 30 Tage mit Besuchen (Link) und Reaktionen (Facebook) und Punkten."""
    if statistik is None:
        try:
            statistik = _statistik()
        except Exception:
            statistik = {}
    if lern_posts is None:
        try:
            import db
            from datetime import datetime, timedelta, timezone
            lern_posts = db.lade_lern_posts(datetime.now(timezone.utc) - timedelta(days=30))
        except Exception:
            lern_posts = []
    posts = {}
    for p in lern_posts or []:
        posts[p["id"]] = {"post": p, "besuche": 0, "konten": 0, "reaktionen": int(p.get("reaktionen") or 0),
                          "kommentare": int(p.get("kommentare") or 0), "geteilt": int(p.get("geteilt") or 0),
                          "reichweite": int(p.get("reichweite") or 0)}
    for code, q in ((statistik or {}).get("quellen") or {}).items():
        if not re.fullmatch(r"p\d+", code or ""):
            continue
        pid = int(code[1:])
        if pid not in posts:
            try:
                post = lade_post(pid)
            except Exception:
                post = None
            if not post:
                continue
            posts[pid] = {"post": post, "besuche": 0, "konten": 0, "reaktionen": 0, "kommentare": 0, "geteilt": 0,
                          "reichweite": 0}
        posts[pid]["besuche"] = int((q.get("schritte") or {}).get("besuch") or 0)
        posts[pid]["konten"] = int(q.get("konten") or 0)
    out = []
    for e in posts.values():
        e["punkte"] = punkte(e["besuche"], e["konten"], e["reaktionen"], e["kommentare"], e["geteilt"],
                             e["reichweite"])
        out.append(e)
    return sorted(out, key=lambda e: e["punkte"], reverse=True)


def _details(e: dict) -> str:
    teile = []
    for wert, eins, viele in ((e.get("reichweite", 0), "erreicht", "erreicht"),
                              (e["besuche"], "Besuch", "Besuche"), (e["konten"], "neues Konto", "neue Konten"),
                              (e["reaktionen"], "Reaktion", "Reaktionen"), (e["kommentare"], "Kommentar", "Kommentare"),
                              (e["geteilt"], "mal geteilt", "mal geteilt")):
        if wert:
            teile.append(f"{wert} {eins if wert == 1 else viele}")
    return ", ".join(teile)


def gut_angekommen(lade_post, sprache: str, statistik=None, min_punkte: int = 6, bewertet=None) -> list[str]:
    """Bis zu 3 eigene Posts, die am besten ankamen (letzte 30 Tage): zuerst aus dieser Sprache,
    dann aus den anderen -- Thema und Ton funktionieren oft ueber Sprachen hinweg."""
    try:
        bewertet = bewertet if bewertet is not None else bewerte(lade_post, statistik)
    except Exception:
        return []
    gut = [e for e in bewertet if e["punkte"] >= min_punkte and e["post"].get("titel")]
    gut.sort(key=lambda e: (e["post"].get("sprache") != sprache, -e["punkte"]))
    zeilen = []
    for e in gut[:3]:
        p = e["post"]
        extra = [p.get("art") or "post"]
        thema = (p.get("meta") or {}).get("thema")
        if thema:
            extra.append(f"Format {thema}")
        if p.get("sprache") != sprache:
            extra.append(SPRACH_NAME.get(p.get("sprache"), p.get("sprache") or ""))
        zeilen.append(f"„{p['titel']}“ ({', '.join(extra)}: {_details(e)})")
    return zeilen


def erkenntnisse(bewertet: list[dict], min_posts: int = 2) -> dict:
    """Durchschnittliche Punkte je Format und je Art (Post/Reel/Story) -- was kommt an, was weniger?"""
    def gruppen(schluessel):
        g = {}
        for e in bewertet:
            k = schluessel(e["post"])
            if k:
                g.setdefault(k, []).append(e["punkte"])
        return sorted(({"name": k, "posts": len(v), "schnitt": round(sum(v) / len(v), 1)}
                       for k, v in g.items() if len(v) >= min_posts), key=lambda x: x["schnitt"], reverse=True)
    return {"formate": gruppen(lambda p: (p.get("meta") or {}).get("thema")),
            "arten": gruppen(lambda p: p.get("art")),
            "sprachen": gruppen(lambda p: p.get("sprache")),
            "stile": gruppen(lambda p: HOOK_NAMEN.get((p.get("meta") or {}).get("hook_stil"))),
            "aufforderungen": gruppen(lambda p: AUFFORDERUNG_NAMEN.get((p.get("meta") or {}).get("aufforderung")))}


def erkenntnis_text(erk: dict) -> str:
    """Kurzer Hinweis fuer den Prompt (leer, solange es zu wenige Daten gibt)."""
    f = erk.get("formate") or []
    if len(f) < 2:
        return ""
    gut = ", ".join(f"{x['name']} (Ø {x['schnitt']:g} Punkte)" for x in f[:2])
    text = f"Bisher kamen diese Formate am besten an: {gut}."
    if f[-1]["schnitt"] < f[0]["schnitt"] / 2:
        text += (f" Schwächer: {f[-1]['name']} (Ø {f[-1]['schnitt']:g}) – ist heute dieses Format dran, "
                 "mach es besonders konkret, persönlich und zum Mitmachen.")
    return text + " Übertrage, was dort funktioniert (Ton, Aufbau, Art der Frage), auf das heutige Format."


# ---------------------------------------------------------------------------
# 5. Selbst-Tests: Hook-Stil und Handlungsaufforderung
# ---------------------------------------------------------------------------
HOOK_STILE = [
    {"schluessel": "frage", "name": "Direkte Frage",
     "auftrag": "Der Hook ist eine direkte, persönliche Frage, auf die man innerlich sofort antwortet."},
    {"schluessel": "aussage", "name": "Mutige Aussage",
     "auftrag": "Der Hook ist eine überraschende, mutige Aussage, die man so nicht erwartet (ohne zu übertreiben)."},
    {"schluessel": "geheimnis", "name": "Neugier-Lücke",
     "auftrag": "Der Hook öffnet eine Neugier-Lücke („Was kaum jemand über … weiß“), die erst im Text aufgeht."},
    {"schluessel": "szene", "name": "Alltags-Szene",
     "auftrag": "Der Hook beginnt mit einer kleinen Szene aus dem Alltag, in der man sich sofort wiedererkennt "
                "(z. B. die Nachricht, die man seit Tagen nicht abschickt)."},
    {"schluessel": "zeichen", "name": "Sternzeichen direkt",
     "auftrag": "Der Hook spricht ein oder mehrere Sternzeichen direkt mit Namen an."},
    {"schluessel": "zahl", "name": "Zahl & Liste",
     "auftrag": "Der Hook kündigt eine kurze Liste mit Zahl an (z. B. „3 Dinge, die …“) – der Text löst sie ein."},
]
HOOK_NAMEN = {h["schluessel"]: h["name"] for h in HOOK_STILE}
AUFFORDERUNG_NAMEN = {"mondzeichen": "Sonne & Mond gratis", "partner": "Partner-Vergleich",
                      "horoskop": "Persönliches Tageshoroskop", "chat": "Astro-Chat"}


def _werte_je(bewertet: list[dict], schluessel: str, wert) -> dict:
    g = {}
    for e in bewertet or []:
        k = (e["post"].get("meta") or {}).get(schluessel)
        if k:
            g.setdefault(k, []).append(wert(e))
    return g


def waehle_variante(namen: list[str], bewertet: list[dict], schluessel: str, *, wert=None,
                    mindest: int = 3, neugier: float = 0.2, rnd=None, standard: str | None = None) -> dict:
    """Welche Variante heute dran ist: Noch zu wenig erprobte zuerst (zufaellig), danach meist die beste
    (Durchschnitt), mit Wahrscheinlichkeit `neugier` eine andere -- so lernt Soraya weiter dazu.
    Antwort: {"wahl", "grund"} -- grund: "standard", "test" oder "beste"."""
    rnd = rnd or random.Random()
    wert = wert or (lambda e: e["punkte"])
    werte = _werte_je(bewertet, schluessel, wert)
    if not any(werte.values()) and standard in namen:
        return {"wahl": standard, "grund": "standard"}     # noch nichts gemessen: der gewohnte Wechsel
    wenig = [n for n in namen if len(werte.get(n, [])) < mindest]
    if wenig and (len(wenig) == len(namen) or rnd.random() < 0.5):
        return {"wahl": rnd.choice(wenig), "grund": "test"}
    erprobt = [n for n in namen if n not in wenig]
    beste = max(erprobt, key=lambda n: sum(werte[n]) / len(werte[n]))
    if rnd.random() < neugier:
        andere = [n for n in namen if n != beste]
        return {"wahl": rnd.choice(andere), "grund": "test"}
    return {"wahl": beste, "grund": "beste"}


def selbsttest(thema: dict, bewertet: list[dict], rnd: random.Random | None = None) -> dict:
    """Hook-Stil und Handlungsaufforderung fuer den heutigen Tagesplan (veraendert `thema`).
    Die Handlungsaufforderung wird nach Besuchen und neuen Konten bewertet, nicht nach Gefaellt-mir."""
    rnd = rnd or random.Random()
    stil = waehle_variante([h["schluessel"] for h in HOOK_STILE], bewertet, "hook_stil", rnd=rnd)
    auff = waehle_variante([a["schluessel"] for a in AUFFORDERUNGEN], bewertet, "aufforderung",
                           wert=lambda e: e["besuche"] * 2 + e["konten"] * 15, rnd=rnd,
                           standard=thema["aufforderung"]["schluessel"])
    thema["hook_stil"] = next(h for h in HOOK_STILE if h["schluessel"] == stil["wahl"])
    thema["aufforderung"] = next(a for a in AUFFORDERUNGEN if a["schluessel"] == auff["wahl"])
    thema["selbsttest"] = {"hook_stil": stil["grund"], "aufforderung": auff["grund"]}
    return thema
