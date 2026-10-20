"""
Automatisch posten (Facebook-Seite, Instagram)

Ablauf jede Minute, wenn der Hauptschalter an ist:
1. Planen: Posts von heute und morgen in der Posting-Sprache bekommen pro Plattform
   einen Termin (Story, Feed-Post, Reel zu festen Uhrzeiten, Wiener Zeit).
2. Faellige Termine ausfuehren: Bild/Video erzeugen, posten, Ergebnis merken.
   Fehler werden bis zu 3x wiederholt (alle 15 Minuten), danach bleibt der Fehler stehen.

Freigabe:
- "auto": geht raus, ausser du setzt den Post auf "Nicht posten" (gestoppt)
- "freigabe": geht nur raus, wenn der Post "Freigegeben" ist
Nach mehr als 12 Stunden Verspaetung wird ein Termin nicht mehr nachgeholt.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime, timedelta

import db
import himmel
import meta
import paket
import redaktion
import tiktok
from wirkung import link_basis

STANDARD = {"an": False, "sprache": "en", "modus": "auto", "tiktok_modus": "entwurf",
            "zeiten": {"story": "09:00", "post": "12:30", "reel": "19:00"},
            "plattformen": {"facebook": True, "instagram": True, "tiktok": False}}
PLATTFORMEN = ("facebook", "instagram", "tiktok")
# TikTok nimmt nur Videos: dort gehen nur die Reels hin
NUR_REELS = {"tiktok"}
# "alle": jeder der drei Posts eines Tages in einer anderen Sprache, die Reihenfolge rotiert taeglich --
# so kommt jede Sprache gleich oft dran (in 4 Tagen je dreimal) und jede Art in jeder Sprache.
ROTATION = ("en", "de", "hu", "it")
ARTEN = ("story", "post", "reel")


def sprache_fuer(tag: date, art: str, e: dict) -> str:
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
    """Facebook, Instagram und TikTok zusammen (fuers Dashboard und den Zeitplan)."""
    return {**meta.verbindungen(), "tiktok": tiktok.verbindung()}


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
        zeit = e["zeiten"].get(post.get("art") or "post")
        if not zeit or post.get("status") == "gestoppt":
            continue
        if post.get("sprache") != sprache_fuer(post["geplant_fuer"], post.get("art") or "post", e):
            continue
        for p in plattformen:
            if p in NUR_REELS and post.get("art") != "reel":
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


def _luftig(text: str) -> str:
    """Hook allein in der ersten Zeile, Absaetze mit genau einer Leerzeile dazwischen."""
    text = re.sub(r"\n{3,}", "\n\n", text.replace("\r", "").strip())
    zeilen = text.split("\n")
    if len(zeilen) > 1 and zeilen[1].strip():
        zeilen.insert(1, "")
    return "\n".join(zeilen)


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
        hat_bio = re.search(r"\bbio\b|bióban", text, flags=re.IGNORECASE)
        zeile = "" if hat_bio else IG_HINWEIS.get(sprache, IG_HINWEIS["en"])
        if name:
            zeile = f"{zeile} 👉 @{name}".strip()
        if zeile:
            zeilen.append(zeile)
    # Die Adresse der Landingpage zum Abtippen (im Instagram-Text nicht klickbar)
    adresse = re.sub(r"^https?://(www\.)?", "", link_basis()).rstrip("/")
    if adresse.lower() not in text.lower():
        zeilen.append(f"🌐 {adresse}")
    return f"{text}\n\n" + "\n".join(zeilen) if zeilen else text


def text_fuer(post: dict, plattform: str) -> str:
    teile = [_luftig(post.get("text") or "")]
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
        # Auf Facebook wirken viele Hashtags wie Werbung -- dort nur die ersten drei
        teile.append(" ".join(tags[:3] if plattform == "facebook" else tags))
    return "\n\n".join(t for t in teile if t)


def medien_url(post: dict, nr: int = 1) -> str:
    """Oeffentliche, signierte Adresse, von der Instagram Bild oder Video holt (nr > 1: Karussell-Folie)."""
    art = "reel" if post.get("art") == "reel" else (f"folie{nr}" if nr > 1 else paket.medien.standard_format(post))
    fp = paket._fingerabdruck(post, art)
    endung = "mp4" if art == "reel" else "jpg"
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
    if not post or not (art in ("feed", "story", "reel") or re.fullmatch(r"folie([2-9]|10)", art)):
        return None
    fp = paket._fingerabdruck(post, art)
    if sig != meta.signiere(f"{post['id']}:{art}:{fp}"):
        return None
    if art == "reel":
        return paket._rendere_video(post), "video/mp4"
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
    text = text_fuer(post, p)
    if p == "tiktok":
        if art != "reel":
            raise ValueError("Auf TikTok gehen nur Reels (Videos).")
        return tiktok.poste_video(paket._rendere_video(post), text, (e or einstellungen()).get("tiktok_modus", "entwurf"))
    if p == "facebook":
        if art == "reel":
            return meta.poste_facebook("reel", text, video=paket._rendere_video(post))
        if art == "post" and paket.medien.anzahl_bilder(post) > 1:
            return meta.poste_facebook(art, text, bilder=paket.hole_karussell(post))
        return meta.poste_facebook(art, text, bild=paket.hole_bild(post))
    if art == "reel":
        paket._rendere_video(post)       # vorher erzeugen, damit Instagram es sofort holen kann
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


def aktualisiere_zahlen(erzwingen: bool = False) -> int:
    """Reaktionen der Facebook-Beitraege der letzten 14 Tage holen und merken (fuers Lernen).
    Laeuft hoechstens alle 6 Stunden; ohne Facebook-Verbindung passiert nichts."""
    if not erzwingen and time.time() - _ZAHLEN["zuletzt"] < ZAHLEN_ALLE_S:
        return 0
    _ZAHLEN["zuletzt"] = time.time()
    if not meta.verbindungen()["facebook"]["verbunden"]:
        return 0
    eintraege = db.lade_gepostete("facebook", datetime.now(himmel.WIEN) - timedelta(days=14), limit=60)
    n = 0
    for z in meta.facebook_reaktionen(eintraege):
        if "fehler" not in z:
            db.speichere_zahlen(z["post_id"], "facebook", z["reaktionen"], z["kommentare"], z["geteilt"],
                                z.get("reichweite"))
            n += 1
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
            aktualisiere_zahlen()
        except Exception as ex:  # noqa: BLE001
            print(f"[Posten] Reaktionen nicht geholt: {ex}", flush=True)
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
    if plattform in NUR_REELS and post.get("art") != "reel":
        raise ValueError("Auf TikTok gehen nur Reels (Videos).")
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
