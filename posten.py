"""
Automatisch posten (Facebook-Seite, Instagram, TikTok, LinkedIn)

Ablauf jede Minute, wenn der Hauptschalter an ist:
1. Planen: Posts von heute und morgen in der Posting-Sprache bekommen pro Plattform
   einen Termin (Story, Feed-Post, Reel und zweites Reel zu festen Uhrzeiten, Wiener Zeit).
2. Faellige Termine ausfuehren: Bild/Video erzeugen, posten, Ergebnis merken.
   Fehler werden bis zu 3x wiederholt (alle 15 Minuten), danach bleibt der Fehler stehen.

Freigabe:
- "auto": geht raus, ausser du setzt den Post auf "Nicht posten" (gestoppt)
- "freigabe": geht nur raus, wenn der Post "Freigegeben" ist
Nach mehr als 12 Stunden Verspaetung wird ein Termin nicht mehr nachgeholt.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

import db
import himmel
import linkedin
import meta
import paket
import redaktion
import tiktok
from claude import frage_json
from wirkung import link_basis

STANDARD = {"an": False, "sprache": "en", "modus": "auto", "tiktok_modus": "entwurf",
            "zeiten": {"story": "09:00", "post": "12:30", "reel": "19:00", "reel2": "19:30"},
            "plattformen": {"facebook": True, "instagram": True, "tiktok": False, "linkedin": False}}
PLATTFORMEN = ("facebook", "instagram", "tiktok", "linkedin")
# TikTok nimmt nur Videos: dort gehen nur die Reels hin
NUR_REELS = {"tiktok"}
# Storys gibt es auf LinkedIn nicht
OHNE_STORYS = {"linkedin"}
# Auf dem persoenlichen LinkedIn-Profil waeren zwei Reels am Tag zu viel: automatisch nur das erste
NUR_ERSTES_REEL = {"linkedin"}


def platz(post: dict) -> str:
    """Termin-Platz eines Posts: story, post, reel oder reel2 (= zweites Reel des Tages, eigene Uhrzeit)."""
    art = post.get("art") or "post"
    if art == "reel" and (post.get("meta") or {}).get("reel_nr") == 2:
        return "reel2"
    return art


def passt(plattform: str, art: str) -> bool:
    """Geht diese Art von Post auf diese Plattform?"""
    if plattform in NUR_REELS:
        return art == "reel"
    if plattform in OHNE_STORYS:
        return art != "story"
    return True
# "alle": jeder der drei Posts eines Tages in einer anderen Sprache, die Reihenfolge rotiert taeglich --
# so kommt jede Sprache gleich oft dran (in 4 Tagen je dreimal) und jede Art in jeder Sprache.
# Das zweite Reel ("reel2") bekommt die vierte Sprache des Tages -- so kommt jeden Tag jede Sprache einmal dran,
# und Story/Feed-Post/Reel behalten ihre bisherige Rotation.
ROTATION = ("en", "de", "hu", "it")
ARTEN = ("story", "post", "reel", "reel2")


def sprache_fuer(tag: date, art: str, e: dict) -> str:
    """art: Termin-Platz (story, post, reel, reel2). Das Dashboard rechnet das in spracheFuer() nach."""
    if e.get("sprache") != "alle":
        return e["sprache"]
    return ROTATION[(tag.toordinal() * 3 + ARTEN.index(art if art in ARTEN else "post")) % len(ROTATION)]


def benoetigte_sprachen(e: dict, tage: list[date]) -> list[str]:
    """Welche Sprachen der Tagesplan an diesen Tagen fuers Posten liefern muss."""
    if e.get("sprache") != "alle":
        return [e["sprache"]]
    return sorted({sprache_fuer(t, a, e) for t in tage for a in ARTEN}, key=ROTATION.index)
MAX_VERSUCHE = 3
_SPERRE = threading.Lock()


def einstellungen() -> dict:
    try:
        gespeichert = db.lade_einstellung("posten", {}) or {}
    except Exception:
        gespeichert = {}
    e = {**STANDARD, **{k: v for k, v in gespeichert.items() if k in STANDARD}}
    e["zeiten"] = {**STANDARD["zeiten"], **(gespeichert.get("zeiten") or {})}
    e["plattformen"] = {**STANDARD["plattformen"], **(gespeichert.get("plattformen") or {})}
    return e


def speichere_einstellungen(neu: dict) -> dict:
    e = einstellungen()
    if "an" in neu:
        e["an"] = bool(neu["an"])
    if neu.get("sprache") in ("de", "en", "hu", "it", "alle"):
        e["sprache"] = neu["sprache"]
    if neu.get("modus") in ("auto", "freigabe"):
        e["modus"] = neu["modus"]
    if neu.get("tiktok_modus") in ("entwurf", "direkt"):
        e["tiktok_modus"] = neu["tiktok_modus"]
    for art, zeit in (neu.get("zeiten") or {}).items():
        if art in STANDARD["zeiten"]:
            datetime.strptime(zeit, "%H:%M")       # wirft bei falscher Uhrzeit
            e["zeiten"][art] = zeit
    for p, an in (neu.get("plattformen") or {}).items():
        if p in PLATTFORMEN:
            e["plattformen"][p] = bool(an)
    db.setze_einstellung("posten", e)
    return e


def termin(tag: date, zeit: str) -> datetime:
    h, m = (int(x) for x in zeit.split(":"))
    return datetime(tag.year, tag.month, tag.day, h, m, tzinfo=himmel.WIEN)


def verbindungen() -> dict:
    """Facebook, Instagram, TikTok und LinkedIn zusammen (fuers Dashboard und den Zeitplan)."""
    return {**meta.verbindungen(), "tiktok": tiktok.verbindung(), "linkedin": linkedin.verbindung()}


def _aktive_plattformen(e: dict) -> list[str]:
    v = verbindungen()
    return [p for p in PLATTFORMEN if e["plattformen"].get(p) and v[p]["verbunden"]]


def planen(e: dict | None = None, jetzt: datetime | None = None) -> int:
    """Termine fuer heute und morgen anlegen (bestehende bleiben, wie sie sind)."""
    e = e or einstellungen()
    jetzt = jetzt or datetime.now(himmel.WIEN)
    heute = jetzt.astimezone(himmel.WIEN).date()
    neu = 0
    plattformen = _aktive_plattformen(e)
    tage = [heute, heute + timedelta(days=1)]
    for post in db.lade_posts_zeitraum(heute, heute + timedelta(days=1), sprachen=benoetigte_sprachen(e, tage)):
        wo = platz(post)
        zeit = e["zeiten"].get(wo)
        if not zeit or post.get("status") == "gestoppt":
            continue
        if post.get("sprache") != sprache_fuer(post["geplant_fuer"], wo, e):
            continue
        for p in plattformen:
            if not passt(p, post.get("art") or "post") or (wo == "reel2" and p in NUR_ERSTES_REEL):
                continue
            neu += db.plane_veroeffentlichung(post["id"], p, termin(post["geplant_fuer"], zeit))
    return neu


# Auf Facebook gibt es keine Bio: der Link steht direkt unter dem Text
BIO_ERSATZ = [(r"link in (the )?bio", "link below"), (r"Link in (der )?Bio", "Link unten"),
              (r"link a bióban", "link lent"), (r"link nella bio|link in bio", "link qui sotto")]


def _ohne_bio(text: str, sprache: str) -> str:
    regeln = {"en": BIO_ERSATZ[:1], "de": BIO_ERSATZ[1:2], "hu": BIO_ERSATZ[2:3], "it": BIO_ERSATZ[3:]}.get(sprache, [])
    for muster, ersatz in regeln:
        text = re.sub(muster, lambda m: ersatz[0].upper() + ersatz[1:] if m.group(0)[0].isupper() else ersatz,
                      text, flags=re.IGNORECASE)
    return text


HASHTAGS_MAX = 5
HOOK_MAX = 125           # so viel zeigt Instagram vor "… mehr"
ABSATZ_MAX = 160          # laengere Absaetze werden an Satzgrenzen geteilt (sehr kurz, gut lesbar am Handy)
_ABK = re.compile(r"\b(z\. ?B\.|d\. ?h\.|u\. ?a\.|bzw\.|ca\.|Nr\.|vs\.|e\. ?g\.|i\. ?e\.|pl\.|kb\.|ill\.|ecc\.)", re.IGNORECASE)
_SATZ = re.compile(r"(?<=[.!?…])\s+(?=[^\s])|(?<=[\U0001F300-\U0001FAFF☀-➿])\s+(?=[A-ZÄÖÜÁÉÍÓŐÚŰ])")
_BIO = re.compile(r"\bbio\b|bióban", re.IGNORECASE)


def _saetze(absatz: str) -> list[str]:
    geschuetzt = _ABK.sub(lambda m: m.group(0).replace(".", "\x00"), absatz)
    return [s.replace("\x00", ".").strip() for s in _SATZ.split(geschuetzt) if s.strip()]


def _teile_absatz(absatz: str) -> list[str]:
    """Zu langen Absatz in Stuecke von hoechstens ABSATZ_MAX Zeichen teilen (nur an Satzgrenzen)."""
    if len(absatz) <= ABSATZ_MAX:
        return [absatz]
    stuecke, akt = [], ""
    for s in _saetze(absatz):
        if akt and len(akt) + 1 + len(s) > ABSATZ_MAX:
            stuecke.append(akt)
            akt = s
        else:
            akt = f"{akt} {s}".strip()
    return stuecke + ([akt] if akt else [])


def _luftig(text: str) -> str:
    """Bildunterschrift wie von einer Social-Media-Redaktion gesetzt:
    - Hook allein in der ersten Zeile (steht er mit weiteren Saetzen in einem Absatz, wird er abgetrennt,
      sofern er in die ersten 125 Zeichen passt -- mehr zeigt Instagram nicht vor "… mehr"),
    - kurze Absaetze (lange werden an Satzgrenzen geteilt), genau eine Leerzeile dazwischen,
    - die Handlungsaufforderung mit "Link in Bio" als eigener letzter Absatz."""
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r", "").strip())
    absaetze = [a.strip() for a in re.split(r"\n\s*\n", text) if a.strip()]
    if not absaetze:
        return ""
    # Zeilen innerhalb des ersten Absatzes: die erste Zeile ist der Hook
    erste = absaetze[0].split("\n")
    if len(erste) > 1:
        absaetze[0:1] = [erste[0].strip(), "\n".join(erste[1:]).strip()]
    else:
        s = _saetze(absaetze[0])
        if len(s) > 1 and len(s[0]) <= HOOK_MAX:
            absaetze[0:1] = [s[0], " ".join(s[1:])]
    # Aufforderung mit Link in Bio ans Ende, als eigener Absatz
    letzter = absaetze[-1]
    if len(absaetze) > 1 or "\n" not in letzter:
        s = _saetze(letzter)
        i = next((k for k in range(len(s) - 1, -1, -1) if _BIO.search(s[k])), None)
        if i and len(s[i].split()) <= 4 and not s[i - 1].rstrip().endswith("?"):
            i -= 1                                   # "… gratis, ohne Konto. Link in Bio ✨" bleibt zusammen
        if i:
            absaetze[-1:] = [" ".join(s[:i]), " ".join(s[i:])]
    # die Frage zum Kommentieren ("Welches Zeichen bist du? Schreib es in die Kommentare 👇") steht allein
    k = len(absaetze) - (2 if len(absaetze) > 1 and _BIO.search(absaetze[-1]) else 1)
    if k >= 1 and "\n" not in absaetze[k]:
        s = _saetze(absaetze[k])
        j = next((x for x in range(len(s) - 1, max(-1, len(s) - 3), -1) if s[x].rstrip().endswith("?")), None)
        if j:
            absaetze[k:k + 1] = [" ".join(s[:j]), " ".join(s[j:])]
    aus = []
    for a in absaetze:
        aus += [a] if "\n" in a else _teile_absatz(a)
    return "\n\n".join(aus)


# Auf Instagram sind Links im Text nicht klickbar: der Weg zur App geht ueber das Profil (Link in Bio)
IG_HINWEIS = {"de": "🔗 Dein Horoskop gratis: Link in Bio", "en": "🔗 Your free horoscope: link in bio",
              "hu": "🔗 Ingyenes horoszkóp: link a bióban", "it": "🔗 Il tuo oroscopo gratis: link in bio"}


def _instagram_name() -> str | None:
    try:
        return (meta.zugang("instagram") or {}).get("name")
    except Exception:  # noqa: BLE001 -- ohne Namen geht der Hinweis auch
        return None


def _mit_bio_hinweis(text: str, sprache: str) -> str:
    """Schlusszeile mit 'Link in Bio' und dem Profil (@name ist auf Instagram antippbar)."""
    name = _instagram_name()
    zeilen = []
    if not (name and f"@{name}".lower() in text.lower()):
        absaetze = text.split("\n\n")
        mit_bio = [i for i, a in enumerate(absaetze) if _BIO.search(a)]
        if mit_bio and name:
            # "@name" direkt hinter "Link in Bio" (eine Aufforderung statt zwei Zeilen)
            absaetze[mit_bio[-1]] = f"{absaetze[mit_bio[-1]].rstrip()} 👉 @{name}"
            text = "\n\n".join(absaetze)
        elif not mit_bio:
            zeile = IG_HINWEIS.get(sprache, IG_HINWEIS["en"])
            zeilen.append(f"{zeile} 👉 @{name}" if name else zeile)
    # Die Adresse der Landingpage zum Abtippen (im Instagram-Text nicht klickbar)
    adresse = re.sub(r"^https?://(www\.)?", "", link_basis()).rstrip("/")
    if adresse.lower() not in text.lower():
        zeilen.append(f"🌐 {adresse}")
    return f"{text}\n\n" + "\n".join(zeilen) if zeilen else text


# ---------------------------------------------------------------------------
# LinkedIn: dein persoenliches Profil -- sachlicher Ton, klickbarer Link, hoechstens 3 Hashtags
# ---------------------------------------------------------------------------
LI_LINK = {"de": "Dein persönliches Horoskop, kostenlos", "en": "Your personal horoscope, free",
           "hu": "A személyes horoszkópod, ingyen", "it": "Il tuo oroscopo personale, gratis"}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
_SPRACHE_NAME = {"de": "Deutsch", "en": "Englisch", "hu": "Ungarisch", "it": "Italienisch"}
LI_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
             "additionalProperties": False}
LI_SYSTEM = ("Du bist Redakteurin für das persönliche LinkedIn-Profil des Gründers der Astrologie-App Soraya. "
             "Du schreibst Social-Media-Texte für LinkedIn um: ruhig, sachlich, professionell, nahbar – "
             "wie ein kurzer Gedanke eines Gründers, nicht wie Werbung.")


def _li_regelbasiert(text: str, sprache: str) -> str:
    """Ohne KI: Emojis und "Link in Bio" raus, Absaetze bleiben."""
    text = _EMOJI.sub("", _ohne_bio(text, sprache))
    zeilen = [z for z in text.split("\n") if not _BIO.search(z)]
    text = re.sub(r"[ \t]+", " ", "\n".join(zeilen))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(z.strip() for z in text.split("\n"))).strip()


def linkedin_text(post: dict) -> str:
    """Sachliche Fassung des Post-Textes fuer LinkedIn (einmal erzeugt, im Post gemerkt -- Wiederholungen
    kosten nichts). Railway-Variable LINKEDIN_KI=0: ohne KI, nur aufgeraeumt."""
    gemerkt = (post.get("meta") or {}).get("linkedin_text")
    if gemerkt:
        return gemerkt
    sprache = post.get("sprache") or "en"
    roh = _luftig(post.get("text") or "")
    text = ""
    if (os.environ.get("LINKEDIN_KI") or "1").strip() != "0" and roh:
        try:
            text = (frage_json(LI_SYSTEM, (
                f"Schreib diesen Text für LinkedIn um. Sprache: {_SPRACHE_NAME.get(sprache, 'Englisch')} (dieselbe "
                "wie das Original, muttersprachlich). Gleicher Inhalt und Anlass, aber sachlicher, professioneller Ton; "
                "erste Zeile ein klarer Gedanke (kein Clickbait); kurze Absätze mit Leerzeile; höchstens ein Emoji; "
                "keine Hashtags, keine Links, kein „Link in Bio“, keine Heils- oder Glücksversprechen; "
                "400 bis 1000 Zeichen.\n\nOriginal:\n" + roh), LI_SCHEMA, effort="low", max_tokens=1500)
                    .get("text") or "").strip()
        except Exception as ex:  # noqa: BLE001 -- dann eben die aufgeraeumte Fassung
            print(f"[LinkedIn] Umschreiben ging nicht: {ex}", flush=True)
            text = ""
        if text and (len(text) < 120 or "http" in text or _BIO.search(text)):
            text = ""           # unbrauchbar -> aufgeraeumte Fassung
    text = text or _li_regelbasiert(roh, sprache)
    try:
        db.setze_meta(post["id"], "linkedin_text", text)
    except Exception:  # noqa: BLE001
        pass
    return text


TIKTOK_TEXT_MAX = 420


def tiktok_text(post: dict) -> str:
    """Beschreibung fuer TikTok: Reel-Titel vorn (damit Soraya das Video spaeter zuordnet), kurzer Text mit
    einer Kommentar-Frage, 5 Hashtags. Bei Entwuerfen setzt TikTok keinen Text -- Attila kopiert ihn im Studio."""
    sprache = post.get("sprache") or "en"
    titel = (post.get("titel") or "").strip()
    text = redaktion.mit_kommentar_frage(post.get("text") or "", sprache, f"p{post.get('id')}", 0)
    # "Link in Bio" ist auf TikTok (unter 1000 Followern) nicht antippbar -> stattdessen die kurze Adresse zum Lesen
    absaetze = [a.strip() for a in _luftig(text).split("\n\n") if a.strip() and not _BIO.search(a)]
    kurz = []
    for a in absaetze:
        if kurz and len("\n\n".join(kurz + [a])) > TIKTOK_TEXT_MAX:
            break
        kurz.append(a)
    if absaetze and absaetze[-1] not in kurz and redaktion.hat_kommentar_frage(absaetze[-1]):
        kurz.append(absaetze[-1])                       # die Kommentar-Frage bleibt immer dabei
    teile = [] if not titel or (kurz and kurz[0].lower().startswith(titel.lower()[:30])) else [titel]
    teile += kurz
    teile.append(f"🔮 {paket.medien.LINK_IN_BIO.get(sprache, paket.medien.LINK_IN_BIO['en'])}: sorayaluxuryastroguide.com")
    tags = (post.get("hashtags") or "").split()[:HASHTAGS_MAX]
    if tags:
        teile.append(" ".join(tags))
    return "\n\n".join(teile)


def tiktok_texte(tage: int = 3) -> list[dict]:
    """Reels, die an TikTok gingen (neueste zuerst), mit dem fertigen Text zum Kopieren."""
    seit = datetime.now(himmel.WIEN) - timedelta(days=tage)
    out = []
    for z in db.lade_gemerkte_zahlen("tiktok", seit, limit=12):
        post = db.lade_post(z["post_id"])
        if post:
            out.append({"post_id": post["id"], "titel": post.get("titel"), "sprache": post.get("sprache"),
                        "gepostet": z.get("gepostet"), "zuordnet": z.get("zahlen_am") is not None,
                        "text": tiktok_text(post)})
    return out


def text_fuer(post: dict, plattform: str) -> str:
    if plattform == "tiktok":
        return tiktok_text(post)
    if plattform == "linkedin":
        sprache = post.get("sprache") or "en"
        teile = [linkedin_text(post), f"{LI_LINK.get(sprache, LI_LINK['en'])}: {link_basis()}?q=p{post['id']}&lang={sprache}"]
        if post.get("hashtags"):
            teile.append(" ".join(post["hashtags"].split()[:3]))
        return "\n\n".join(t for t in teile if t)
    text = post.get("text") or ""
    if post.get("art") in ("post", "reel"):
        # genau eine leichte Frage zum Kommentieren (steht meist schon da -- dann bleibt alles, wie es ist)
        m = post.get("meta") or {}
        antworten = len(m.get("bild_punkte") or []) if post.get("art") == "post" and m.get("thema") == "Mitmachen" else 0
        text = redaktion.mit_kommentar_frage(text, post.get("sprache") or "en", f"p{post.get('id')}", antworten)
    teile = [_luftig(text)]
    if plattform == "facebook" and post.get("art") != "story":
        teile[0] = _ohne_bio(teile[0], post.get("sprache") or "de")
    if plattform == "facebook" and post.get("art") != "story":
        # auf Facebook ist der Link klickbar; lang= oeffnet Landingpage und App in der Sprache des Posts
        sprache = post.get("sprache") or "en"
        vorne = IG_HINWEIS.get(sprache, IG_HINWEIS["en"]).split(":")[0]
        teile.append(f"{vorne} 👉 {link_basis()}?q=p{post['id']}&lang={sprache}")
    if plattform == "instagram" and post.get("art") != "story":
        teile[0] = _mit_bio_hinweis(teile[0], post.get("sprache") or "en")
    if post.get("hashtags"):
        tags = post["hashtags"].split()
        # Auf Facebook wirken viele Hashtags wie Werbung -- dort nur die ersten drei; Instagram nimmt
        # hoechstens 5 Hashtags je Beitrag (mehr wirken dort auch nicht besser)
        teile.append(" ".join(tags[:3] if plattform == "facebook" else tags[:HASHTAGS_MAX]))
    return "\n\n".join(t for t in teile if t)


# Instagram zeigt Fremden fast nur Reels: an diesen Wochentagen bleibt der Feed-Post ein Karussell (Mo, Mi, Fr),
# an den anderen wird er auf Instagram als Reel aus seinen Folien gepostet (Diashow). Facebook bleibt Karussell.
KARUSSELL_TAGE = (0, 2, 4)


def als_diashow(post: dict, tag: date | None = None) -> bool:
    tag = tag or datetime.now(himmel.WIEN).date()
    return post.get("art") == "post" and tag.weekday() not in KARUSSELL_TAGE


def medien_url(post: dict, nr: int = 1, art: str | None = None) -> str:
    """Oeffentliche, signierte Adresse, von der Instagram Bild oder Video holt (nr > 1: Karussell-Folie)."""
    art = art or ("reel" if post.get("art") == "reel" else (f"folie{nr}" if nr > 1 else paket.medien.standard_format(post)))
    fp = paket._fingerabdruck(post, art)
    endung = "mp4" if art in ("reel", "diashow") else "jpg"
    sig = meta.signiere(f"{post['id']}:{art}:{fp}")
    return f"{meta.basis_url()}/oeffentlich/medien/{post['id']}-{art}-{sig}.{endung}"


def oeffentliches_medium(name: str) -> tuple[bytes, str] | None:
    """Gegenstueck zu medien_url: liefert die Datei nur bei passender Signatur."""
    try:
        stamm, endung = name.rsplit(".", 1)
        pid, art, sig = stamm.split("-", 2)
        post = db.lade_post(int(pid))
    except (ValueError, TypeError):
        return None
    if not post or not (art in ("feed", "story", "reel", "diashow") or re.fullmatch(r"folie([2-9]|10)", art)):
        return None
    fp = paket._fingerabdruck(post, art)
    if sig != meta.signiere(f"{post['id']}:{art}:{fp}"):
        return None
    if art == "reel":
        return paket._rendere_video(post), "video/mp4"
    if art == "diashow":
        return paket.rendere_diashow(post), "video/mp4"
    if art.startswith("folie"):
        return paket.hole_folie(post, int(art[5:])), "image/jpeg"
    return paket.hole_bild(post, art), "image/jpeg"


def _freigegeben(post: dict, e: dict) -> tuple[bool, str]:
    st = post.get("status") or "entwurf"
    if st == "gestoppt":
        return False, "gestoppt"
    if e["modus"] == "freigabe" and st not in ("freigegeben", "gepostet"):
        return False, "warte"
    # Ernster Befund der Qualitaetspruefung (heikle Versprechen, falsche Sprache, Link ...): erst nach deiner
    # Freigabe. Kleinigkeiten (Laenge, Zahl der Hashtags) halten den Post nicht auf.
    if redaktion.schwer((post.get("meta") or {}).get("pruefung") or []) and st not in ("freigegeben", "gepostet"):
        return False, "warte"
    return True, ""


def veroeffentliche(zeile: dict, post: dict, e: dict | None = None) -> dict:
    p, art = zeile["plattform"], post.get("art") or "post"
    if not passt(p, art):
        raise ValueError("Auf TikTok gehen nur Reels (Videos)." if p == "tiktok" else "Storys gibt es auf LinkedIn nicht.")
    text = text_fuer(post, p)
    if p == "tiktok":
        return tiktok.poste_video(paket.rendere_tiktok(post), text, (e or einstellungen()).get("tiktok_modus", "entwurf"))
    if p == "linkedin":
        alt = post.get("titel") or "Soraya"
        if art == "reel":
            return linkedin.poste("reel", text, video=paket._rendere_video(post), bild=paket.hole_bild(post), alt=alt)
        if paket.medien.anzahl_bilder(post) > 1:
            return linkedin.poste("post", text, bilder=paket.hole_karussell(post), alt=alt)
        return linkedin.poste("post", text, bild=paket.hole_bild(post), alt=alt)
    if p == "facebook":
        if art == "reel":
            return meta.poste_facebook("reel", text, video=paket._rendere_video(post))
        if art == "post" and paket.medien.anzahl_bilder(post) > 1:
            return meta.poste_facebook(art, text, bilder=paket.hole_karussell(post))
        return meta.poste_facebook(art, text, bild=paket.hole_bild(post))
    if art == "reel":
        paket._rendere_video(post)       # vorher erzeugen, damit Instagram es sofort holen kann
    elif als_diashow(post):
        paket.rendere_diashow(post)
        return meta.poste_instagram("reel", text, medien_url(post, art="diashow"))
    elif art == "post" and paket.medien.anzahl_bilder(post) > 1:
        paket.hole_karussell(post)
        n = paket.medien.anzahl_bilder(post)
        return meta.poste_instagram(art, text, medien_url(post), medien_urls=[medien_url(post, i) for i in range(1, n + 1)])
    else:
        paket.hole_bild(post)
    return meta.poste_instagram(art, text, medien_url(post))


def fuehre_aus(jetzt: datetime | None = None, e: dict | None = None) -> list[dict]:
    e = e or einstellungen()
    jetzt = jetzt or datetime.now(himmel.WIEN)
    ergebnisse = []
    for zeile in db.faellige_veroeffentlichungen(jetzt, MAX_VERSUCHE):
        post = db.lade_post(zeile["post_id"])
        if not post:
            continue
        if jetzt - zeile["geplant_um"] > timedelta(hours=12):
            db.setze_veroeffentlichung(zeile["id"], "verpasst", fehler="Mehr als 12 Stunden zu spät – nicht nachgeholt.")
            continue
        ok, grund = _freigegeben(post, e)
        if not ok:
            if grund == "gestoppt":
                db.setze_veroeffentlichung(zeile["id"], "abgebrochen", fehler="Auf „Nicht posten“ gesetzt.")
            continue                                   # "warte": spaeter noch einmal ansehen
        db.setze_veroeffentlichung(zeile["id"], "laeuft", versuch=True)
        try:
            r = veroeffentliche(zeile, post, e)
            db.setze_veroeffentlichung(zeile["id"], "fertig", extern_id=r.get("id"), url=r.get("url"))
            ergebnisse.append({"id": zeile["id"], "status": "fertig"})
        except Exception as ex:  # noqa: BLE001 -- landet im Protokoll
            db.setze_veroeffentlichung(zeile["id"], "fehler", fehler=str(ex)[:400])
            ergebnisse.append({"id": zeile["id"], "status": "fehler", "fehler": str(ex)[:200]})
            print(f"[Posten] {zeile['plattform']} Post {post['id']}: FEHLER {ex}", flush=True)
            continue
        if db.alle_veroeffentlicht(post["id"]):
            db.aendere_post(post["id"], {"status": "gepostet"})
    return ergebnisse


_ZAHLEN = {"zuletzt": 0.0}
ZAHLEN_ALLE_S = 6 * 3600


def _merke(plattform: str, zeilen: list[dict]) -> int:
    n = 0
    for z in zeilen:
        if "fehler" not in z:
            db.speichere_zahlen(z["post_id"], plattform, z.get("reaktionen", 0), z.get("kommentare", 0),
                                z.get("geteilt", 0), z.get("reichweite"), z.get("gespeichert"), z.get("aufrufe"))
            n += 1
    return n


ABRUF = "zahlen_abruf"


def merke_abruf(plattform: str, ok: int, fehler: int, meldung: str | None = None) -> None:
    """Wie der letzte Zahlen-Abruf einer Plattform lief (fuer den Hinweis in „Wirkung“)."""
    d = db.lade_einstellung(ABRUF, {}) or {}
    d[plattform] = {"am": datetime.now(himmel.WIEN).isoformat(timespec="minutes"), "ok": ok, "fehler": fehler,
                    "meldung": (meldung or "")[:300] or None}
    db.setze_einstellung(ABRUF, d)


def abruf_stand() -> dict:
    return db.lade_einstellung(ABRUF, {}) or {}


def merke_facebook(zeilen: list[dict]) -> int:
    zeilen = [z for z in zeilen if not z.get("nicht_messbar")]     # Storys: Facebook gibt keine Zahlen
    n = _merke("facebook", zeilen)
    fehler = [z for z in zeilen if "fehler" in z]
    merke_abruf("facebook", n, len(fehler), fehler[0]["fehler"] if fehler else None)
    if fehler:
        print(f"[Posten] Facebook: {len(fehler)} Beitrag/Beitraege ohne Zahlen, z. B. {fehler[0]['fehler']}", flush=True)
    return n


def merke_follower(anzahl: int | None, heute: date | None = None, schluessel: str = "instagram_follower") -> None:
    """Follower je Tag (90 Tage), damit Wirkung den Zuwachs zeigen kann (Instagram, TikTok)."""
    if anzahl is None:
        return
    d = db.lade_einstellung(schluessel, {}) or {}
    verlauf = d.get("verlauf") or {}
    verlauf[(heute or datetime.now(himmel.WIEN).date()).isoformat()] = int(anzahl)
    verlauf = dict(sorted(verlauf.items())[-90:])
    db.setze_einstellung(schluessel, {"verlauf": verlauf})


def follower_stand(schluessel: str = "instagram_follower") -> dict:
    """Aktuelle Follower und Zuwachs gegen vor 7 Tagen (aus dem gemerkten Verlauf)."""
    verlauf = (db.lade_einstellung(schluessel, {}) or {}).get("verlauf") or {}
    if not verlauf:
        return {}
    tage = sorted(verlauf)
    jetzt = verlauf[tage[-1]]
    grenze = (date.fromisoformat(tage[-1]) - timedelta(days=7)).isoformat()
    frueher = [t for t in tage if t <= grenze]
    return {"follower": jetzt, "am": tage[-1], "zuwachs_7": jetzt - verlauf[frueher[-1]] if frueher else None}


def follower_verlauf(schluessel: str = "instagram_follower") -> dict:
    """{iso-datum: follower} (bis zu 90 Tage, aelteste zuerst) fuer die Wachstumskurve im Zahlen-Cockpit."""
    return dict(sorted(((db.lade_einstellung(schluessel, {}) or {}).get("verlauf") or {}).items()))


def facebook_follower_merken() -> None:
    """Follower der Facebook-Seite merken (fuer den Zuwachs im Zahlen-Cockpit). Fehler stoppen nichts."""
    try:
        merke_follower(meta.facebook_konto().get("follower"), schluessel="facebook_follower")
    except Exception as ex:  # noqa: BLE001
        print(f"[Posten] Facebook-Follower nicht geholt: {ex}", flush=True)


def zahlen_instagram(seit: datetime, limit: int = 60) -> dict:
    """Instagram-Zahlen holen und merken. Rueckgabe wie meta.instagram_zahlen."""
    jetzt = datetime.now(himmel.WIEN)
    # abgelaufene Storys (> 24 h) liefert Instagram nicht mehr -- die gemerkten Zahlen bleiben stehen
    eintraege = [x for x in db.lade_gepostete("instagram", seit, limit=limit)
                 if x.get("art") != "story" or not x.get("aktualisiert") or jetzt - x["aktualisiert"] < STORY_LEBEN]
    r = meta.instagram_zahlen(eintraege)
    _merke("instagram", r["beitraege"])
    try:
        merke_follower(meta.instagram_konto().get("follower"))
    except Exception as ex:  # noqa: BLE001
        print(f"[Posten] Instagram-Follower nicht geholt: {ex}", flush=True)
    return r


_TIKTOK_STAND: dict = {}      # wie viele Videos TikTok beim letzten Abruf geliefert hat (fuers Dashboard)


TIKTOK_VIDEOS = "tiktok_videos"
TIKTOK_VIDEOS_TAGE = 120


def merke_tiktok_videos(liste: list[dict], zugeordnet: dict, jetzt: datetime | None = None) -> None:
    """Alle TikTok-Videos des Kontos mit ihren Zahlen merken -- auch die ohne Soraya-Post (selbst gemacht),
    damit TikTok in „Wirkung“ ueberall mitzaehlt. Aeltere Eintraege bleiben stehen (bis 120 Tage)."""
    jetzt = jetzt or datetime.now(timezone.utc)
    alt = ((db.lade_einstellung(TIKTOK_VIDEOS, {}) or {}).get("videos")) or {}
    for v in liste:
        vid, ct = str(v.get("id") or ""), v.get("create_time")
        if not vid or not ct:
            continue
        alt[vid] = {"zeit": datetime.fromtimestamp(int(ct), timezone.utc).isoformat(timespec="minutes"),
                    "titel": ((v.get("title") or v.get("video_description") or "").strip())[:80],
                    "aufrufe": int(v.get("view_count") or 0), "gefaellt": int(v.get("like_count") or 0),
                    "kommentare": int(v.get("comment_count") or 0), "geteilt": int(v.get("share_count") or 0),
                    "url": v.get("share_url"), "post_id": zugeordnet.get(vid)}
    grenze = (jetzt - timedelta(days=TIKTOK_VIDEOS_TAGE)).isoformat()
    db.setze_einstellung(TIKTOK_VIDEOS, {"videos": {k: x for k, x in alt.items() if x["zeit"] >= grenze[:16]}})


def tiktok_videos() -> list[dict]:
    """Die gemerkten TikTok-Videos (ohne API-Aufruf), aelteste zuerst."""
    v = ((db.lade_einstellung(TIKTOK_VIDEOS, {}) or {}).get("videos")) or {}
    return sorted(({"id": k, **x} for k, x in v.items()), key=lambda x: x["zeit"])


def zahlen_tiktok(seit: datetime) -> list[dict]:
    """TikTok-Videos (video.list) unseren Reels zuordnen und die Zahlen merken."""
    z = tiktok.zugang() or {}
    if not tiktok.zahlen_erlaubt(z):
        return []
    try:
        liste = tiktok.videos(40)
    except tiktok.TikTokFehler as ex:
        if "Recht" in str(ex) or "scope" in str(ex).lower():
            z["zahlen_fehlt"] = True
            db.setze_einstellung(tiktok.SCHLUESSEL, z)
        raise
    _TIKTOK_STAND.update(gefunden=len(liste), am=datetime.now(himmel.WIEN).isoformat(timespec="minutes"))
    zeilen = tiktok.zuordnen(db.lade_gepostete("tiktok", seit, limit=60), liste)
    # selbst hochgeladene Videos (z. B. aus dem Wochenpaket): ueber den Titel den Reels zuordnen
    schon = {z_["post_id"] for z_ in zeilen}
    benutzt = {str(z_.get("url")) for z_ in zeilen}
    reels = [{"post_id": p["id"], "titel": p.get("titel")} for p in db.lade_posts(200, von=seit.date())
             if p.get("art") == "reel" and p["id"] not in schon]
    zeilen += [x for x in tiktok.zuordnen_nach_titel(reels, [v for v in liste if str(v.get("share_url")) not in benutzt])]
    for x in zeilen:
        vid = x.pop("_video", None)
        if vid and vid != "None":
            # selbst gepostet/hochgeladen: ohne fertigen Eintrag gingen die Zahlen verloren
            db.merke_extern_gepostet(x["post_id"], "tiktok", vid, x.get("url"), x.get("gepostet"))
            x["video_id"] = vid
    _merke("tiktok", zeilen)
    merke_tiktok_videos(liste, {x.get("video_id"): x["post_id"] for x in zeilen if x.get("video_id")})
    try:
        k = tiktok.konto()
        if k:
            merke_follower(k.get("follower"), schluessel="tiktok_follower")
    except Exception as ex:  # noqa: BLE001
        print(f"[Posten] TikTok-Follower nicht geholt: {ex}", flush=True)
    return zeilen


# Instagram-Storys verschwinden nach 24 Stunden -- und mit ihnen die Zahlen. Darum werden sie eigens
# gemessen, solange sie noch zu sehen sind: rund 2 und rund 20 Stunden nach dem Posten.
STORY_MESSUNG_H = (2, 20)
STORY_LEBEN = timedelta(hours=24)


def _story_faellig(s: dict, jetzt: datetime) -> bool:
    gepostet = s.get("gepostet")
    if not gepostet or not s.get("extern_id"):
        return False
    alter = jetzt - gepostet
    if alter >= STORY_LEBEN:
        return False
    for h in sorted(STORY_MESSUNG_H, reverse=True):
        if alter >= timedelta(hours=h):
            return not s.get("zahlen_am") or s["zahlen_am"] < gepostet + timedelta(hours=h)
    return False


def miss_storys(jetzt: datetime | None = None) -> int:
    """Zahlen (Reichweite, Aufrufe, Antworten, Teilen) der Instagram-Storys holen, solange sie noch leben.
    Laeuft in jedem Durchlauf mit, fragt Instagram aber nur, wenn eine Story faellig ist."""
    jetzt = jetzt or datetime.now(himmel.WIEN)
    storys = [s for s in db.lade_gemerkte_zahlen("instagram", jetzt - STORY_LEBEN, limit=20)
              if s.get("art") == "story" and _story_faellig(s, jetzt)]
    if not storys or not meta.instagram_zahlen_erlaubt(meta.zugang("instagram")):
        return 0
    r = meta.instagram_zahlen([{**s, "aktualisiert": s["gepostet"]} for s in storys])
    return _merke("instagram", r["beitraege"])


def aktualisiere_zahlen(erzwingen: bool = False) -> int:
    """Reaktionen der Beitraege der letzten 14 Tage holen und merken (fuers Lernen): Facebook, Instagram
    (mit Insights-Recht auch Reichweite, Aufrufe, Speichern, Teilen) und TikTok (video.list).
    Laeuft hoechstens alle 6 Stunden; ohne Verbindung passiert auf der Plattform nichts."""
    if not erzwingen and time.time() - _ZAHLEN["zuletzt"] < ZAHLEN_ALLE_S:
        return 0
    _ZAHLEN["zuletzt"] = time.time()
    seit = datetime.now(himmel.WIEN) - timedelta(days=14)
    v = meta.verbindungen()
    n = 0
    if v["facebook"]["verbunden"]:
        try:
            n += merke_facebook(meta.facebook_reaktionen(db.lade_gepostete("facebook", seit, limit=60)))
        except Exception as ex:  # noqa: BLE001 -- die anderen Plattformen trotzdem holen
            print(f"[Posten] Facebook-Zahlen nicht geholt: {ex}", flush=True)
            merke_abruf("facebook", 0, 1, str(ex))
        facebook_follower_merken()
    if v["instagram"]["verbunden"]:
        try:
            n += sum("fehler" not in z for z in zahlen_instagram(seit)["beitraege"])
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] Instagram-Zahlen nicht geholt: {ex}", flush=True)
    try:
        n += len(zahlen_tiktok(seit))
    except Exception as ex:  # noqa: BLE001
        print(f"[Posten] TikTok-Zahlen nicht geholt: {ex}", flush=True)
    return n


def durchlauf(jetzt: datetime | None = None) -> dict:
    """Ein Durchlauf des Zeitplans (auch fuer Tests)."""
    if not _SPERRE.acquire(blocking=False):
        return {"uebersprungen": True}
    try:
        e = einstellungen()
        try:
            meta.instagram_verlaengern()
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] Instagram-Zugang nicht verlängert: {ex}", flush=True)
        try:
            tiktok.erneuern_wenn_noetig()
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] TikTok-Zugang nicht erneuert: {ex}", flush=True)
        try:
            aktualisiere_zahlen()
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] Reaktionen nicht geholt: {ex}", flush=True)
        try:
            miss_storys(jetzt)
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] Story-Zahlen nicht geholt: {ex}", flush=True)
        if not e["an"]:
            return {"an": False}
        return {"an": True, "geplant": planen(e, jetzt), "ausgefuehrt": fuehre_aus(jetzt, e)}
    finally:
        _SPERRE.release()


def jetzt_posten(post_id: int, plattform: str) -> dict:
    """Knopf "Jetzt posten" (auch zum Testen der Verbindung): sofort, unabhaengig vom Hauptschalter."""
    post = db.lade_post(post_id)
    if not post:
        raise ValueError("Post nicht gefunden.")
    if plattform not in PLATTFORMEN:
        raise ValueError("Unbekannte Plattform.")
    if not passt(plattform, post.get("art") or "post"):
        raise ValueError("Auf TikTok gehen nur Reels (Videos)." if plattform == "tiktok"
                         else "Storys gibt es auf LinkedIn nicht.")
    zid = db.plane_veroeffentlichung(post_id, plattform, datetime.now(himmel.WIEN), zurueckgeben=True)
    db.setze_veroeffentlichung(zid, "laeuft", versuch=True)
    try:
        r = veroeffentliche({"plattform": plattform}, post)
    except Exception as ex:
        db.setze_veroeffentlichung(zid, "fehler", fehler=str(ex)[:400])
        raise
    db.setze_veroeffentlichung(zid, "fertig", extern_id=r.get("id"), url=r.get("url"))
    if db.alle_veroeffentlicht(post_id):
        db.aendere_post(post_id, {"status": "gepostet"})
    return r


def zeitplan_starten(intervall_sekunden: int = 60) -> None:
    def schleife():
        time.sleep(30)
        while True:
            try:
                durchlauf()
            except Exception as ex:  # noqa: BLE001
                print(f"[Posten] Zeitplan-Fehler: {ex}", flush=True)
            time.sleep(intervall_sekunden)
    threading.Thread(target=schleife, name="posten-zeitplan", daemon=True).start()
