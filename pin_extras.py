"""
Zusaetzliche Pins auf Pinterest (seit 07.11.2026)

Pinterest zeigt Konten mehr, die jeden Tag mehrere frische Pins haben, und wird wie eine Suchmaschine benutzt.
Darum kommen zum Titelbild des Feed-Posts (normaler Termin in posten.py) dazu:
  1. jede Karussell-Folie als eigener Pin (ohne Seitenzahl und "Wischen"), ueber den Nachmittag verteilt,
  2. ein zeitloser Sternzeichen-Pin am Abend (Staerken, Schattenseiten, passende Zeichen, Fragen aus den
     Sternzeichen-Seiten der Landingpage, inhalte/zeichen_pins.json) mit Link auf die passende Zeichen-Seite.
Beide haengen am Feed-Post des Tages (seine Pinterest-Zahlen enthalten sie) und entstehen erst, wenn dessen Pin
erschienen ist. Laufen nur, wenn automatisches Posten und der Pinterest-Haken an sind.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

import db
import himmel
import paket
import pinterest

FOLIEN_ABSTAND_H = (2, 4, 6)       # Stunden nach dem Titel-Pin
ZEICHEN_UHR = (20, 30)             # Sternzeichen-Pin abends (Pinterest wird abends am meisten genutzt)
SPAETESTENS_H = 12                 # spaeter nicht mehr nachholen
MAX_VERSUCHE = 3
ARTEN = ("staerken", "schwaechen", "passt", "faq0", "faq1", "faq2", "faq3")
_INHALTE: dict | None = None

TITEL = {
    "staerken": {"de": "{z}: Stärken des Sternzeichens", "en": "{z} strengths: zodiac sign traits",
                 "hu": "{z}: a csillagjegy erősségei", "it": "{z}: i punti di forza del segno"},
    "schwaechen": {"de": "{z}: Schattenseiten des Sternzeichens", "en": "{z} weaknesses: the shadow side of the sign",
                   "hu": "{z}: a csillagjegy árnyoldalai", "it": "{z}: i lati d'ombra del segno"},
    "passt": {"de": "{z}: diese Sternzeichen passen am besten", "en": "{z} compatibility: best matching signs",
              "hu": "{z}: ezek a csillagjegyek illenek hozzá", "it": "{z}: i segni più affini"},
}
BILD_TITEL = {
    "staerken": {"de": "{z}: Stärken", "en": "{z}: strengths", "hu": "{z}: erősségek", "it": "{z}: punti di forza"},
    "schwaechen": {"de": "{z}: Schattenseiten", "en": "{z}: shadow side", "hu": "{z}: árnyoldalak", "it": "{z}: lati d'ombra"},
    "passt": {"de": "{z}: passt zu", "en": "{z}: best matches", "hu": "{z}: illő jegyek", "it": "{z}: segni affini"},
}


def inhalte() -> dict:
    global _INHALTE
    if _INHALTE is None:
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inhalte", "zeichen_pins.json")
        with open(pfad, encoding="utf-8") as f:
            _INHALTE = json.load(f)
    return _INHALTE


def wahl(tag: date, sprache: str) -> tuple[int, str]:
    """(Sternzeichen 0-11, Art) fuer den Tag: jeden Tag ein anderes Zeichen, alle 12 Tage eine andere Art."""
    n = tag.toordinal() + {"de": 0, "en": 3, "hu": 6, "it": 9}.get(sprache, 0)
    return n % 12, ARTEN[(n // 12) % len(ARTEN)]


def _erster_satz(text: str, max_woerter: int = 30) -> str:
    satz = re.split(r"(?<=[.!?])\s", (text or "").strip(), maxsplit=1)[0]
    woerter = satz.split()
    return satz if len(woerter) <= max_woerter else " ".join(woerter[:max_woerter]).rstrip(",;:") + " …"


def zeichen_pin(tag: date, sprache: str, eltern_id: int = 0) -> dict:
    """Alles fuer den Sternzeichen-Pin: Bild (Post-Ersatz fuer medien), Titel, Beschreibung, Link-Pfad, Zeichen."""
    from sprachen import zeichen as zeichen_name
    import medien
    import posten
    liste = inhalte().get(sprache) or inhalte()["en"]
    sprache = sprache if sprache in inhalte() else "en"
    idx, art = wahl(tag, sprache)
    z = liste[idx]
    if art.startswith("faq") and int(art[3:]) >= len(z.get("faq") or []):
        art = "staerken"
    if art.startswith("faq"):
        f = z["faq"][int(art[3:])]
        titel = f["frage"]
        bild_post = {"id": 900000 + tag.toordinal() % 50000, "art": "post", "sprache": sprache, "titel": titel,
                     "meta": {"thema": "Sternzeichen im Fokus", "folie_zeichen": idx,
                              "folien": [{"titel": titel, "text": _erster_satz(f["antwort"])}]}}
        bild = medien.folie(bild_post, 2, video=True)
        beschreibung = _erster_satz(f["antwort"], 60)
    else:
        if art == "staerken":
            punkte = (z.get("staerken") or [])[:3]
        elif art == "schwaechen":
            punkte = (z.get("schwaechen") or [])[:3]
        else:
            punkte = [zeichen_name(k, sprache) for k in (z.get("passt_gut") or [])[:3]]
        punkte = [p[:1].upper() + p[1:] for p in punkte]
        titel = TITEL[art][sprache].format(z=z["name"])
        bild_post = {"id": 900000 + tag.toordinal() % 50000, "art": "post", "sprache": sprache,
                     "titel": BILD_TITEL[art][sprache].format(z=z["name"]),
                     "meta": {"thema": "Sternzeichen im Fokus", "bild_punkte": punkte, "mond_zeichen": z["name"]}}
        bild = medien.bild(bild_post, "feed")
        beschreibung = z.get("intro") or ""
    aufruf = posten.PIN_AUFRUF.get(sprache, posten.PIN_AUFRUF["en"])
    tags = " ".join(posten.seo_tags({"sprache": sprache, "titel": z["name"], "hashtags": ""}, "pinterest"))
    teile = [_erster_satz(beschreibung, 45), z.get("meta_description") or "", aufruf, tags]
    text = "\n\n".join(t for t in teile if t)
    if len(text) > 500:
        text = "\n\n".join(t for t in (_erster_satz(beschreibung, 45), aufruf, tags) if t)
    pfad, slugs = pinterest.ZEICHEN_SEITEN.get(sprache, pinterest.ZEICHEN_SEITEN["en"])
    return {"bild": medien.als_bytes(bild), "titel": titel[:100], "text": text[:500], "zeichen": idx, "art": art,
            "pfad": f"{pfad}/{slugs[idx]}", "alt": titel, "slug": slugs[idx]}


def planen(e: dict, jetzt: datetime) -> int:
    """Zusatz-Pins fuer heute anlegen, sobald der Titel-Pin eines Feed-Posts erschienen ist."""
    heute = jetzt.astimezone(himmel.WIEN).date()
    neu = 0
    for post in db.pinterest_feed_pins(heute):
        um = post["gepinnt_um"].astimezone(himmel.WIEN)
        n = paket.medien.anzahl_bilder(post)
        for k, nr in enumerate(range(2, n)):              # ohne Titelbild (schon da) und ohne Schlussfolie
            if k >= len(FOLIEN_ABSTAND_H):
                break
            neu += db.plane_pin(post["id"], f"folie{nr}", um + timedelta(hours=FOLIEN_ABSTAND_H[k]))
        abend = datetime(heute.year, heute.month, heute.day, *ZEICHEN_UHR, tzinfo=himmel.WIEN)
        neu += db.plane_pin(post["id"], "zeichen", max(abend, um + timedelta(hours=1)),
                            {"tag": heute.isoformat(), "sprache": post.get("sprache") or "en"})
    return neu


def veroeffentliche(zeile: dict) -> dict:
    import posten
    post = db.lade_post(zeile["post_id"])
    if not post:
        raise ValueError("Post gibt es nicht mehr.")
    sprache = post.get("sprache") or "en"
    if zeile["art"] == "zeichen":
        d = zeile.get("daten") or {}
        tag = date.fromisoformat(d.get("tag")) if d.get("tag") else post["geplant_fuer"]
        pin = zeichen_pin(tag, d.get("sprache") or sprache, post["id"])
        link = f"{posten.link_basis().rstrip('/')}/{pin['pfad']}?q=pin-{pin['slug']}&lang={sprache}"
        return pinterest.poste_pin(pin["bild"], pin["titel"], pin["text"], link, sprache, alt=pin["alt"], zeichen=pin["zeichen"])
    nr = int(zeile["art"][5:])
    folie = (paket.medien.folien_von(post) or [])[nr - 2] if nr - 2 < len(paket.medien.folien_von(post)) else {}
    bild = paket.medien.als_bytes(paket.medien.folie(post, nr, video=True))
    titel = (folie.get("titel") or post.get("titel") or "Soraya").strip()
    stichwort = posten.PIN_STICHWORT.get(sprache, posten.PIN_STICHWORT["en"])
    if len(titel) + 3 + len(stichwort) <= 100:
        titel = f"{titel} – {stichwort}"
    text = "\n\n".join(t for t in [(folie.get("text") or "").strip(), posten.pinterest_text(post)] if t)[:500]
    return pinterest.poste_pin(bild, titel, text, pinterest.ziel_link(post, posten.link_basis()), sprache,
                               alt=folie.get("text") or titel, zeichen=posten.ein_zeichen({**post, "titel": folie.get("titel") or ""}))


def ausfuehren(jetzt: datetime) -> list[dict]:
    ergebnisse = []
    for zeile in db.faellige_pins(jetzt, MAX_VERSUCHE):
        if jetzt - zeile["geplant_um"] > timedelta(hours=SPAETESTENS_H):
            db.setze_pin(zeile["id"], "verpasst", fehler="Mehr als 12 Stunden zu spät – nicht nachgeholt.")
            continue
        if not db.beanspruche_pin(zeile):
            continue
        try:
            r = veroeffentliche(zeile)
            db.setze_pin(zeile["id"], "fertig", extern_id=r.get("id"))
            ergebnisse.append({"id": zeile["id"], "art": zeile["art"], "status": "fertig"})
        except Exception as ex:  # noqa: BLE001
            db.setze_pin(zeile["id"], "fehler", fehler=str(ex)[:400])
            ergebnisse.append({"id": zeile["id"], "art": zeile["art"], "status": "fehler", "fehler": str(ex)[:200]})
            print(f"[Pinterest] Zusatz-Pin {zeile['art']} (Post {zeile['post_id']}): FEHLER {ex}", flush=True)
    return ergebnisse


def durchlauf(e: dict, jetzt: datetime | None = None) -> dict:
    jetzt = jetzt or datetime.now(himmel.WIEN)
    return {"geplant": planen(e, jetzt), "ausgefuehrt": ausfuehren(jetzt)}


def stand(tage: int = 7) -> dict:
    """Fuers Dashboard: Zusatz-Pins der letzten Tage (Anzahl je Status, letzter Fehler, Anzeigen)."""
    zeilen = db.lade_pins(datetime.now(himmel.WIEN) - timedelta(days=tage), limit=300)
    je = {}
    for z in zeilen:
        je[z["status"]] = je.get(z["status"], 0) + 1
    fehler = next((z["fehler"] for z in zeilen if z["status"] == "fehler" and z.get("fehler")), None)
    return {"anzahl": je, "anzeigen": sum(z.get("reichweite") or 0 for z in zeilen), "letzter_fehler": fehler}
