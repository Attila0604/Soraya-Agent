"""
Himmel heute: holt die echten Himmelsdaten aus der Soraya-astro-engine (/sky,
oeffentlich, reine Berechnung) und bereitet sie je Sprache auf.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from sprachen import datum_kurz, datum_lang, mondphase, planet, zeichen

WIEN = ZoneInfo("Europe/Vienna")


def engine_url() -> str:
    return (os.environ.get("ENGINE_URL") or "https://astro-engine-production-7b18.up.railway.app").rstrip("/")


def heute() -> date:
    return datetime.now(WIEN).date()


def stunde_jetzt() -> int:
    return datetime.now(WIEN).hour


def hole_himmel(tag: date | None = None) -> dict:
    """Himmelsdaten von heute oder (zum Vorplanen) von einem bestimmten Tag."""
    params = {"datum": tag.isoformat()} if tag and tag != heute() else None
    try:
        antwort = requests.get(engine_url() + "/sky", params=params, timeout=30)
        antwort.raise_for_status()
        daten = antwort.json()
    except Exception as e:
        raise RuntimeError(f"Himmelsdaten nicht erreichbar: {e}")
    if not daten.get("ok") or not daten.get("data"):
        raise RuntimeError("Himmelsdaten nicht erreichbar: " + str(daten.get("error") or "keine Daten"))
    return daten["data"]


def _tag(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(WIEN).date()
    except ValueError:
        try:
            return date.fromisoformat(iso[:10])
        except ValueError:
            return None


def aufbereiten(sky: dict, tag: date, sprache: str) -> dict:
    """Himmel in der gewuenschten Sprache, mit Tagen bis Neu-/Vollmond."""
    mond = sky.get("moon") or {}
    sonne = sky.get("sun") or {}

    def mondereignis(iso):
        d = _tag(iso)
        if not d:
            return None
        return {"datum": d.isoformat(), "datum_text": datum_kurz(d, sprache), "in_tagen": (d - tag).days}

    rueck = []
    for r in sky.get("retrograde") or []:
        bis = _tag(r.get("until"))
        rueck.append({"planet": planet(r.get("key") or r.get("planet"), sprache),
                      "bis": datum_kurz(bis, sprache) if bis else ""})
    bald = []
    for r in sky.get("retrograde_soon") or []:
        ab = _tag(r.get("from"))
        bald.append({"planet": planet(r.get("key") or r.get("planet"), sprache),
                     "ab": datum_kurz(ab, sprache) if ab else ""})

    return {
        "datum": tag.isoformat(),
        "datum_text": datum_lang(tag, sprache),
        "datum_kurz": datum_kurz(tag, sprache),
        "phase_index": mond.get("phase_index"),
        "mond_phase": mondphase(mond.get("phase_index"), sprache),
        "beleuchtung": mond.get("illumination"),
        "mond_zeichen": zeichen(mond.get("sign"), sprache),
        "sonne_zeichen": zeichen(sonne.get("sign"), sprache),
        "neumond": mondereignis(sky.get("next_new_moon")),
        "vollmond": mondereignis(sky.get("next_full_moon")),
        "ruecklaeufig": rueck,
        "bald_ruecklaeufig": bald,
    }


def als_text(info: dict) -> str:
    """Kompakte Beschreibung fuer den Prompt."""
    zeilen = [
        f"Datum: {info['datum_text']}",
        f"Mond: {info['mond_phase']}, {info['beleuchtung']} % beleuchtet, im Zeichen {info['mond_zeichen']}",
        f"Sonne im Zeichen {info['sonne_zeichen']}",
    ]
    for name, schluessel in (("Nächster Neumond", "neumond"), ("Nächster Vollmond", "vollmond")):
        e = info.get(schluessel)
        if e:
            wann = "heute" if e["in_tagen"] <= 0 else ("morgen" if e["in_tagen"] == 1 else f"in {e['in_tagen']} Tagen")
            zeilen.append(f"{name}: {e['datum_text']} ({wann})")
    if info["ruecklaeufig"]:
        zeilen.append("Rückläufig: " + ", ".join(
            f"{r['planet']} (bis {r['bis']})" if r["bis"] else r["planet"] for r in info["ruecklaeufig"]))
    if info["bald_ruecklaeufig"]:
        zeilen.append("Wird bald rückläufig: " + ", ".join(
            f"{r['planet']} (ab {r['ab']})" if r["ab"] else r["planet"] for r in info["bald_ruecklaeufig"]))
    return "\n".join(zeilen)


def bild_meta(info: dict) -> dict:
    """Was das Post-Bild im Dashboard braucht (Mond zeichnen, Datumszeile)."""
    return {
        "phase_index": info.get("phase_index"),
        "beleuchtung": info.get("beleuchtung"),
        "mond_zeichen": info.get("mond_zeichen"),
        "mond_phase": info.get("mond_phase"),
        "datum_kurz": info.get("datum_kurz"),
    }
