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


_SIGNS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]


def sonnen_laenge(d: date) -> float:
    """Ekliptikale Laenge der Sonne (Grad, ca. 0,01 Grad genau) am Mittag UTC -- fuer das Zeichen von Neu-/Vollmond."""
    import math
    n = (date(d.year, d.month, d.day) - date(2000, 1, 1)).days - 0.5 + 0.5      # JD - 2451545.0 (Mittag)
    L = 280.460 + 0.9856474 * n
    g = math.radians(357.528 + 0.9856003 * n)
    return (L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360


def mondereignis_zeichen(d: date, voll: bool) -> str:
    """Sign-Key des Neumonds (Zeichen der Sonne) bzw. Vollmonds (gegenueberliegendes Zeichen)."""
    laenge = (sonnen_laenge(d) + (180 if voll else 0)) % 360
    return _SIGNS[int(laenge // 30)]


def aufbereiten(sky: dict, tag: date, sprache: str) -> dict:
    """Himmel in der gewuenschten Sprache, mit Tagen bis Neu-/Vollmond."""
    mond = sky.get("moon") or {}
    sonne = sky.get("sun") or {}

    def mondereignis(iso, voll=False):
        d = _tag(iso)
        if not d:
            return None
        return {"datum": d.isoformat(), "datum_text": datum_kurz(d, sprache), "in_tagen": (d - tag).days,
                "zeichen": zeichen(mondereignis_zeichen(d, voll), sprache)}

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
        "vollmond": mondereignis(sky.get("next_full_moon"), voll=True),
        "ruecklaeufig": rueck,
        "bald_ruecklaeufig": bald,
        # seit 08.11. (Engine): wo die Planeten stehen, Winkel des Tages, welche Zeichen heute angesprochen sind
        "planeten": [{"planet": planet(x.get("key"), sprache), "zeichen": zeichen(x.get("sign"), sprache),
                      "grad": x.get("degree"), "rueck": bool(x.get("retrograde"))}
                     for x in sky.get("planets") or [] if x.get("key") not in ("Sun", "Moon")],
        "winkel": [{"a": planet(w.get("a"), sprache), "b": planet(w.get("b"), sprache),
                    "art": WINKEL.get(w.get("aspect"), w.get("aspect")), "orb": w.get("orb")}
                   for w in (sky.get("aspects") or [])[:5]],
        "zeichen_heute": [{"idx": _SIGN_KEYS.index(z["sign"]), "name": zeichen(z["sign"], sprache), "punkte": z.get("score", 0),
                           "gruende": [grund_text(g) for g in z.get("reasons") or []]}
                          for z in sky.get("signs_today") or [] if z.get("sign") in _SIGN_KEYS],
    }


_SIGN_KEYS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
WINKEL = {"conjunction": "Konjunktion", "sextile": "Sextil", "square": "Quadrat", "trine": "Trigon", "opposition": "Opposition"}
_GRUND = {"moon_in": "Mond im Zeichen", "moon_opposite": "Mond gegenüber", "moon_square": "Mond im Spannungswinkel (Quadrat)",
          "moon_trine": "Mond im harmonischen Winkel (Trigon)", "sun_in": "Sonne im Zeichen",
          "mercury_in": "Merkur im Zeichen", "venus_in": "Venus im Zeichen", "mars_in": "Mars im Zeichen",
          "new_moon_in": "Neumond im Zeichen", "full_moon_in": "Vollmond im Zeichen",
          "full_moon_opposite": "Vollmond gegenüber"}
_PLANET_DE = {"Sun": "Sonne", "Moon": "Mond", "Mercury": "Merkur", "Venus": "Venus", "Mars": "Mars", "Jupiter": "Jupiter",
              "Saturn": "Saturn", "Uranus": "Uranus", "Neptune": "Neptun", "Pluto": "Pluto"}


def grund_text(g: str) -> str:
    """Grund aus der Engine ("moon_in", "ruler_retro:Venus") als kurzer deutscher Text fuer den Prompt."""
    if g.startswith("ruler_retro:"):
        return f"Herrscher {_PLANET_DE.get(g.split(':', 1)[1], g.split(':', 1)[1])} rückläufig"
    return _GRUND.get(g, g)


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
            im = f" im Zeichen {e['zeichen']}" if e.get("zeichen") else ""
            zeilen.append(f"{name}: {e['datum_text']} ({wann}){im}")
            if e.get("zeichen") and e["in_tagen"] <= 2 and e["zeichen"] != info.get("mond_zeichen"):
                zeilen.append(f"ACHTUNG: Der {name.split()[-1]} steht im Zeichen {e['zeichen']} – heute steht der Mond noch "
                              f"in {info['mond_zeichen']}. Sprichst du vom {name.split()[-1]}, nenne {e['zeichen']}; "
                              f"sprichst du vom Mond heute, nenne {info['mond_zeichen']} – nie vermischen.")
    if info["ruecklaeufig"]:
        zeilen.append("Rückläufig: " + ", ".join(
            f"{r['planet']} (bis {r['bis']})" if r["bis"] else r["planet"] for r in info["ruecklaeufig"]))
    if info.get("planeten"):
        zeilen.append("Planeten: " + ", ".join(
            f"{p['planet']} in {p['zeichen']}" + (" (rückläufig)" if p["rueck"] else "") for p in info["planeten"]))
    if info.get("winkel"):
        zeilen.append("Winkel heute: " + ", ".join(f"{w['a']} {w['art']} {w['b']}" for w in info["winkel"]))
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
