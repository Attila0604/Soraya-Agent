"""
Redaktion: was der Tagesplan heute erzaehlt -- und ob ein Post gut genug zum Posten ist

1. Wochenthema: Jeder Wochentag hat ein eigenes Format (Abwechslung haelt Follower,
   die Plattformen belohnen Speichern, Teilen und Kommentare). Grosse Himmels-
   ereignisse (Neu-/Vollmond, Rueckläufigkeit beginnt) haben Vorrang.
2. Handlungsaufforderung: wechselt zwischen echten Funktionen der App.
3. Qualitaetspruefung: Laenge, Hashtags, Sprache, heikle Versprechen. Posts mit ernstem Befund
   (siehe schwer()) gehen beim automatischen Posten erst raus, wenn du sie freigibst.
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
    # Dienstag: frueher "Sternzeichen im Fokus" (kam schwach an) -- jetzt Mitmachen rund um die Sternzeichen,
    # so bleiben die Zeichen im Plan, aber der Post laedt zum Antworten ein
    {"name": "Mitmachen", "variante": "Sternzeichen-Check",
     "auftrag": "Ein Mitmach-Post rund um die Sternzeichen: das Zeichen, in dem der Mond heute steht, und zwei passende "
                "(gleiches Element oder Gegenzeichen) – je ein konkreter Satz, in dem man sich sofort wiedererkennt. "
                "Dann eine leichte Frage, auf die jedes Zeichen antworten kann (z. B. „Welches Zeichen bist du – trifft "
                "es?“). Ziel sind Kommentare und Antworten."},
    # Mittwoch: frueher "Liebe & Beziehung" (kam schwach an) -- jetzt ein Ritual fuer Naehe (Rituale bringen die
    # meisten Besuche); die Einladung bleibt der Partner-Vergleich
    {"name": "Ritual", "variante": "Herz-Ritual",
     "auftrag": "Ein kleines Ritual für Liebe, Freundschaft und Nähe passend zum heutigen Himmel (höchstens 3 einfache "
                "Schritte, für Paare und Singles – z. B. eine Nachricht, ein ehrliches Gespräch, eine Journaling-Frage "
                "über Nähe). Alltagsnah und warm. Lädt zum Speichern ein."},
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
# Formate, die es im Wochenplan gibt (aeltere wie "Sternzeichen im Fokus" stehen nur noch in alten Posts)
AKTUELLE_FORMATE = {t["name"] for t in WOCHENTHEMEN}

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
    import anlaesse
    thema = dict(WOCHENTHEMEN[tag.weekday()])
    besondere = anlaesse.anlaesse(tag, info)
    anlass, auftrag = "", ""
    for name, schluessel in (("Neumond", "neumond"), ("Vollmond", "vollmond")):
        e = info.get(schluessel)
        if e and 0 <= e.get("in_tagen", 99) <= 1:
            anlass = f"{name} {'heute' if e['in_tagen'] <= 0 else 'morgen'}"
            vm = next((b for b in besondere if b.get("vollmond")), None) if schluessel == "vollmond" else None
            if vm:
                anlass += f" – {vm['name'].split(' ', 1)[1]}"
                auftrag = vm["auftrag"]
    if not anlass:
        for r in info.get("bald_ruecklaeufig") or []:
            if r.get("ab") and r["ab"] in (info.get("datum_kurz"),):
                anlass = f"{r['planet']} wird heute rückläufig"
    tag_anlass = next((b for b in besondere if b["wann"] == "heute" and not b.get("vollmond")), None)
    if not anlass and tag_anlass:          # Saisonbeginn oder Feiertag, wenn der Mond nichts Grosses macht
        anlass, auftrag = tag_anlass["name"], tag_anlass["auftrag"]
    if anlass:
        thema = {"name": f"Großes Ereignis: {anlass}",
                 "auftrag": f"Heute ist das Ereignis das Hauptthema: {anlass}. Was es bedeutet, wie man es nutzt, "
                            f"worauf man achten sollte – konkret und alltagsnah." + (f" {auftrag}" if auftrag else "")}
    # was sonst noch ansteht (z. B. "morgen beginnt die Skorpion-Saison") darf erwaehnt werden
    thema["hinweise"] = [f"{b['name']} ({b['wann']})" for b in besondere
                         if b["name"] not in anlass and not (b.get("vollmond") and "Vollmond" in anlass)]
    key = _THEMA_AUFFORDERUNG[tag.weekday()]
    thema["aufforderung"] = next(a for a in AUFFORDERUNGEN if a["schluessel"] == key)
    thema["anlass"] = anlass
    return thema


def thema_text(thema: dict, link_in_bio: str) -> str:
    name = thema["name"] + (f" ({thema['variante']})" if thema.get("variante") else "")
    text = (f"Heutiges Format: {name}\n{thema['auftrag']}\n"
            f"Handlungsaufforderung heute (sinngemäß, in der Sprache des Posts, mit „{link_in_bio}“): "
            f"{thema['aufforderung']['auftrag']}")
    if thema.get("hook_stil"):
        text += f"\nHook-Stil heute (für Feed-Post und Reel): {thema['hook_stil']['auftrag']}"
    if thema.get("hinweise"):
        text += "\nAußerdem steht an (darf als kurzer Ausblick erwähnt werden): " + "; ".join(thema["hinweise"])
    return text


# ---------------------------------------------------------------------------
# 3. Qualitaetspruefung (ohne zusaetzliche KI-Kosten)
# ---------------------------------------------------------------------------
_HEIKEL = re.compile(
    r"\b(garantiert|garantie|guarantee[ds]?|100\s?%|heilt|heilen|cure[ds]?|diagnos\w*|krankheit\w*|disease\w*|"
    r"lotto|lottery|reich werden|get rich|gewinnspiel|giveaway)\b", re.IGNORECASE)
_DEUTSCH_IN_FREMD = re.compile(r"\b(und|nicht|deine?n?|für|heute|Mond|Sonne|Sternzeichen|Liebe|Woche)\b")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_GRENZEN = {"post": (40, 110), "reel": (5, 60), "story": (4, 25)}
FOLIE_WOERTER = 14       # Text je Karussell-Folie (steht gross im Bild)
HOOK_ZEICHEN = 100        # Hook steht sicher vor "… mehr" (Instagram zeigt ~125 Zeichen)
HASHTAGS_MAX = 5          # Instagram nimmt hoechstens 5 Hashtags je Beitrag
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


# ---------------------------------------------------------------------------
# 2b. Eine leichte Frage zum Kommentieren unter jedem Feed-Post und Reel
#     (ein Wort, ein Emoji oder das eigene Zeichen -- so kommentieren mehr Menschen)
# ---------------------------------------------------------------------------
KOMMENTAR_FRAGEN = {
    "de": ["Welches Zeichen bist du? Schreib dein Emoji in die Kommentare 👇",
           "Tipp ein 🌙, wenn du das heute spürst.",
           "Ja oder nein? Ein Wort reicht – unten in die Kommentare.",
           "Erkennst du dich wieder? Schick ein ✨",
           "Welches Zeichen muss das heute hören? Schreib es unten 👇",
           "Trifft es bei dir zu? Antworte mit 🔥 oder 🌙"],
    "en": ["Which sign are you? Drop your emoji below 👇",
           "Type 🌙 if you felt this today.",
           "Yes or no? One word in the comments.",
           "Does this sound like you? Drop a ✨",
           "Which sign needs to hear this today? Tell me below 👇",
           "Is this you right now? Answer with 🔥 or 🌙"],
    "hu": ["Te melyik csillagjegy vagy? Írd meg egy emojival kommentben 👇",
           "Írj egy 🌙-t, ha te is érzed ma.",
           "Igen vagy nem? Egy szó is elég kommentben.",
           "Magadra ismertél? Küldj egy ✨-t",
           "Melyik jegynek kell ezt ma hallania? Írd meg lent 👇",
           "Rád is igaz? Válaszolj 🔥-val vagy 🌙-val"],
    "it": ["Di che segno sei? Lascia la tua emoji nei commenti 👇",
           "Scrivi 🌙 se lo senti anche tu oggi.",
           "Sì o no? Basta una parola nei commenti.",
           "Ti ci ritrovi? Lascia un ✨",
           "Quale segno ha bisogno di sentirlo oggi? Scrivilo qui sotto 👇",
           "Ti somiglia? Rispondi con 🔥 o 🌙"],
}
# beim Format "Mitmachen" mit Antwortmoeglichkeiten im Bild (Umfrage A/B/C)
KOMMENTAR_UMFRAGE = {"de": ("{abc}? Schreib deinen Buchstaben in die Kommentare 👇", "oder"),
                     "en": ("{abc}? Tell me your letter below 👇", "or"),
                     "hu": ("{abc}? Írd meg a betűdet kommentben 👇", "vagy"),
                     "it": ("{abc}? Scrivi la tua lettera nei commenti 👇", "o")}
BIO = re.compile(r"\bbio\b|bióban", re.IGNORECASE)
# Woran man eine Aufforderung zum Kommentieren erkennt (in allen vier Sprachen)
_KOMMENTAR = re.compile(
    r"(komment|comment|👇|\bbelow\b|\bunten\b|\blent\b|alább|qui sotto|tell me|dimmi|írd meg|\bírj\b|"
    r"\bschreib\w*|\bscrivi\w*|\blascia\b|\bdrop\b|\btype\b|\btipp\b|antworte|\banswer\b|\breply\b|"
    r"válaszolj|rispondi|küldj|\bschick\b)", re.IGNORECASE)
_SATZENDE = re.compile(r"(?<=[.!?…])\s+")


def _absaetze(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"\n\s*\n", (text or "").strip()) if a.strip()]


def hat_kommentar_frage(text: str) -> bool:
    """Steht am Ende (vor der Handlungsaufforderung mit Link in Bio) schon eine Frage oder Aufforderung
    zum Kommentieren? Der Hook (erster Satz) zaehlt nicht."""
    saetze = []
    for a in _absaetze(text):
        saetze += [s for s in _SATZENDE.split(a.replace("\n", " ")) if s.strip()]
    saetze = [s for s in saetze[1:] if not BIO.search(s)]
    return any(_KOMMENTAR.search(s) or s.rstrip(" 👇✨🌙🔥").endswith("?") for s in saetze[-3:])


def kommentar_frage(sprache: str, saat: str = "", antworten: int = 0) -> str:
    """Eine leichte Frage zum Kommentieren, abwechselnd (gleiche Saat -> gleiche Frage)."""
    import zlib
    sprache = sprache if sprache in KOMMENTAR_FRAGEN else "en"
    if antworten >= 2:
        vorlage, oder = KOMMENTAR_UMFRAGE[sprache]
        buchstaben = "ABC"[:min(antworten, 3)]
        abc = ", ".join(buchstaben[:-1]) + f" {oder} {buchstaben[-1]}"
        return vorlage.format(abc=abc)
    liste = KOMMENTAR_FRAGEN[sprache]
    return liste[zlib.crc32(saat.encode()) % len(liste)]


def mit_kommentar_frage(text: str, sprache: str, saat: str = "", antworten: int = 0) -> str:
    """Haengt GENAU EINE leichte Frage zum Kommentieren an -- vor der Handlungsaufforderung mit „Link in Bio“
    (Hashtags und Link fuegt der Agent ohnehin danach an). Steht schon eine da, bleibt der Text, wie er ist."""
    if not (text or "").strip() or hat_kommentar_frage(text):
        return text
    frage = kommentar_frage(sprache, saat, antworten)
    absaetze = _absaetze(text)
    i = next((k for k in range(len(absaetze) - 1, -1, -1) if BIO.search(absaetze[k])), None)
    if i is None:
        return "\n\n".join(absaetze + [frage])
    saetze = [s for s in _SATZENDE.split(absaetze[i]) if s.strip()]
    j = next(k for k in range(len(saetze) - 1, -1, -1) if BIO.search(saetze[k]))
    if j and len(saetze[j].split()) <= 4:
        j -= 1                             # "… gratis, ohne Konto. Link in Bio ✨" bleibt zusammen
    davor, cta = " ".join(saetze[:j]), " ".join(saetze[j:])
    return "\n\n".join(absaetze[:i] + ([davor] if davor else []) + [frage, cta] + absaetze[i + 1:])


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
    erste = re.split(r"(?<=[.!?…])\s", (post.get("text") or "").strip().split("\n", 1)[0], maxsplit=1)[0]
    if art in ("post", "reel") and (_woerter(erste) > 22 or len(erste) > HOOK_ZEICHEN):
        befunde.append(f"Erste Zeile zu lang (der Hook sollte kurz sein, max. {HOOK_ZEICHEN} Zeichen)")
    lo, hi = _GRENZEN.get(art, (1, 300))
    n = _woerter(post.get("text"))
    if n < lo:
        befunde.append(f"Text zu kurz ({n} Wörter)")
    if n > hi:
        befunde.append(f"Text zu lang ({n} Wörter, max. {hi})")
    tags = [t for t in re.split(r"\s+", post.get("hashtags") or "") if t] if isinstance(post.get("hashtags"), str) \
        else list(post.get("hashtags") or [])
    if art != "story" and not 3 <= len(tags) <= HASHTAGS_MAX:
        befunde.append(f"{len(tags)} Hashtags (3 bis {HASHTAGS_MAX} sinnvoll)")
    emojis = len(_EMOJI.findall(post.get("text") or ""))
    if emojis > 3:
        befunde.append(f"Zu viele Emojis ({emojis}, höchstens 2–3)")
    folien = post.get("_folien") or post.get("folien") or (post.get("meta") or {}).get("folien") or []
    if any(_woerter(f.get("text")) > FOLIE_WOERTER for f in folien if isinstance(f, dict)):
        befunde.append(f"Folien-Text zu lang (max. {FOLIE_WOERTER} Wörter)")
    if art in ("post", "reel") and (post.get("text") or "").strip() and not hat_kommentar_frage(post.get("text")):
        befunde.append("Frage zum Kommentieren fehlt (z. B. „Welches Zeichen bist du? 👇“)")
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
    """Ernste Befunde: der Tagesplan schreibt einmal neu, und automatisch gepostet wird erst nach Freigabe."""
    return any(b.startswith(("Heikle", "Deutsche Wörter", "Enthält einen Link", "Reel ohne Hook", "Überschrift fehlt"))
               for b in befunde)


# ---------------------------------------------------------------------------
# 4. Lernen aus der Wirkung
# ---------------------------------------------------------------------------
_CACHE = {"zeit": 0.0, "daten": None}


SPRACH_NAME = {"de": "DE", "en": "EN", "hu": "HU", "it": "IT"}


def punkte(besuche: int = 0, konten: int = 0, reaktionen: int = 0, kommentare: int = 0, geteilt: int = 0,
           reichweite: int = 0, gespeichert: int = 0) -> int:
    """Eine Zahl fuer "wie gut kam der Post an": neue Konten zaehlen am meisten, dann Teilen,
    Kommentare und Speichern (Instagram), Besuche ueber den Link und Gefaellt-mir; je 100 erreichte Menschen 1 Punkt."""
    return (int(besuche) * 2 + int(konten) * 15 + int(reaktionen) + int(kommentare) * 3 + int(geteilt) * 4
            + int(gespeichert or 0) * 3 + int(reichweite or 0) // 100)


def _statistik():
    if time.time() - _CACHE["zeit"] > 3600:
        from wirkung import hole_statistik
        _CACHE.update(zeit=time.time(), daten=hole_statistik(30))
    return _CACHE["daten"] or {}


def bewerte(lade_post, statistik=None, lern_posts=None) -> list[dict]:
    """Alle Posts der letzten 30 Tage mit Besuchen (Link), Reaktionen (Facebook, Instagram, TikTok) und Punkten."""
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
                          "reichweite": int(p.get("reichweite") or 0), "gespeichert": int(p.get("gespeichert") or 0),
                          # False: noch keine Zahlen (z. B. Story abgelaufen, bevor Instagram sie lieferte)
                          "gemessen": p.get("gemessen") is not False}
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
                          "reichweite": 0, "gespeichert": 0, "gemessen": True}
        posts[pid]["besuche"] = int((q.get("schritte") or {}).get("besuch") or 0)
        posts[pid]["konten"] = int(q.get("konten") or 0)
        if posts[pid]["besuche"] or posts[pid]["konten"]:
            posts[pid]["gemessen"] = True          # Besuche ueber den Post-Link sind eine Messung
    out = []
    for e in posts.values():
        e["punkte"] = punkte(e["besuche"], e["konten"], e["reaktionen"], e["kommentare"], e["geteilt"],
                             e["reichweite"], e.get("gespeichert", 0))
        out.append(e)
    return sorted(out, key=lambda e: e["punkte"], reverse=True)


def _details(e: dict) -> str:
    teile = []
    for wert, eins, viele in ((e.get("reichweite", 0), "erreicht", "erreicht"),
                              (e["besuche"], "Besuch", "Besuche"), (e["konten"], "neues Konto", "neue Konten"),
                              (e["reaktionen"], "Reaktion", "Reaktionen"), (e["kommentare"], "Kommentar", "Kommentare"),
                              (e["geteilt"], "mal geteilt", "mal geteilt"),
                              (e.get("gespeichert", 0), "mal gespeichert", "mal gespeichert")):
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


def _art_stunde(p: dict) -> str | None:
    """"post 12" = Feed-Post, gepostet zwischen 12 und 13 Uhr (Wiener Zeit)."""
    g = p.get("gepostet")
    if not g or not hasattr(g, "astimezone"):
        return None
    from himmel import WIEN
    return f"{p.get('art') or 'post'} {g.astimezone(WIEN).hour}"


def zeit_vorschlaege(erk: dict, min_posts: int = 3) -> list[dict]:
    """Je Art: beste Uhrzeit, wenn mindestens zwei Uhrzeiten mit je min_posts gemessenen Posts verglichen
    werden koennen (sonst leer). [{"art", "stunde", "schnitt", "statt", "statt_schnitt"}]"""
    je_art: dict = {}
    for z in erk.get("zeiten") or []:
        if z["posts"] >= min_posts:
            art, stunde = z["name"].rsplit(" ", 1)
            je_art.setdefault(art, []).append({**z, "stunde": int(stunde)})
    out = []
    for art, liste in je_art.items():
        if len(liste) < 2:
            continue
        liste.sort(key=lambda z: z["schnitt"], reverse=True)
        out.append({"art": art, "stunde": liste[0]["stunde"], "schnitt": liste[0]["schnitt"],
                    "statt": liste[-1]["stunde"], "statt_schnitt": liste[-1]["schnitt"]})
    return out


def gemessen(bewertet: list[dict]) -> list[dict]:
    """Nur Posts mit echten Zahlen: ein nie gemessener Post (z. B. eine Story, die nach 24 Stunden weg war,
    bevor Instagram Zahlen lieferte) zaehlt nicht als 0 in den Durchschnitten."""
    return [e for e in bewertet or [] if e.get("gemessen", True)]


def nicht_gemessen(bewertet: list[dict]) -> dict:
    """{art: Anzahl} der geposteten, aber (noch) nicht gemessenen Posts -- fuers Dashboard."""
    out = {}
    for e in bewertet or []:
        if not e.get("gemessen", True):
            art = e["post"].get("art") or "post"
            out[art] = out.get(art, 0) + 1
    return out


def erkenntnisse(bewertet: list[dict], min_posts: int = 2) -> dict:
    """Durchschnittliche Punkte je Format und je Art (Post/Reel/Story) -- was kommt an, was weniger?
    Nicht gemessene Posts zaehlen nicht mit."""
    bewertet = gemessen(bewertet)

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
            "zeiten": gruppen(_art_stunde),
            "stile": gruppen(lambda p: HOOK_NAMEN.get((p.get("meta") or {}).get("hook_stil"))),
            "aufforderungen": gruppen(lambda p: AUFFORDERUNG_NAMEN.get((p.get("meta") or {}).get("aufforderung")))}


def erkenntnis_text(erk: dict, heute: str | None = None) -> str:
    """Kurzer Hinweis fuer den Prompt (leer, solange es zu wenige Daten gibt). heute = Format des Tages:
    ist es eines der staerksten, soll der Tagesplan dabei bleiben; ist es schwach, besonders zum Mitmachen
    schreiben. Als "schwaecher" wird nur ein Format genannt, das es im Wochenplan noch gibt."""
    f = erk.get("formate") or []
    if len(f) < 2:
        return ""
    gut = ", ".join(f"{x['name']} (Ø {x['schnitt']:g} Punkte)" for x in f[:2])
    text = f"Bisher kamen diese Formate am besten an: {gut}."
    if heute and heute in [x["name"] for x in f[:2]]:
        return text + (f" Heute ist {heute} dran – bleib bei dem, was dort funktioniert hat (Ton, Aufbau, "
                       "Art der Frage), aber mit neuem Inhalt.")
    aktuell = [x for x in f if x["name"] in AKTUELLE_FORMATE]
    schwach = next((x for x in aktuell if x["name"] == heute), None) or (aktuell[-1] if aktuell else None)
    if schwach and schwach["schnitt"] < f[0]["schnitt"] / 2:
        text += (f" Schwächer: {schwach['name']} (Ø {schwach['schnitt']:g}) – ist heute dieses Format dran, "
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
    werte = _werte_je(gemessen(bewertet), schluessel, wert)
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
