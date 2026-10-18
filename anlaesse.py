"""
Besondere Tage fuer den Tagesplan (ohne Internet, ohne KI-Kosten)

- Beginn einer Sternzeichen-Saison (die Sonne wechselt das Zeichen), dazu Frühlings-,
  Sommer-, Herbst- und Winteranfang
- Namen der Vollmonde (Hunter's Moon, Cold Moon ...), Harvest Moon = Vollmond am naechsten zur
  Herbst-Tagundnachtgleiche
- feste Tage: Neujahr, Valentinstag, Halloween, Silvester

Die Sonnenposition kommt aus einer einfachen astronomischen Naeherung (genau auf etwa 0,01 Grad),
das reicht, um den Tag des Zeichenwechsels zu treffen.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

ZEICHEN = ["Widder", "Stier", "Zwillinge", "Krebs", "Löwe", "Jungfrau",
           "Waage", "Skorpion", "Schütze", "Steinbock", "Wassermann", "Fische"]
JAHRESZEIT = {0: "Frühlingsanfang", 3: "Sommeranfang", 6: "Herbstanfang", 9: "Winteranfang"}

# Traditionelle Vollmond-Namen (Nordhalbkugel) nach Monat; Harvest/Hunter's Moon werden extra bestimmt
VOLLMOND_NAMEN = {1: ("Wolfsmond", "Wolf Moon"), 2: ("Schneemond", "Snow Moon"), 3: ("Wurmmond", "Worm Moon"),
                  4: ("Rosa Mond", "Pink Moon"), 5: ("Blumenmond", "Flower Moon"), 6: ("Erdbeermond", "Strawberry Moon"),
                  7: ("Hirschmond", "Buck Moon"), 8: ("Störmond", "Sturgeon Moon"), 9: ("Erntemond", "Harvest Moon"),
                  10: ("Jägermond", "Hunter's Moon"), 11: ("Bibermond", "Beaver Moon"), 12: ("Kalter Mond", "Cold Moon")}

FESTE_TAGE = {(1, 1): "Neujahr – ein Neubeginn, Vorsätze und was die Sterne fürs neue Jahr andeuten",
              (2, 14): "Valentinstag – Liebe, Nähe und wie gut zwei Sternzeichen zusammenpassen",
              (10, 31): "Halloween (Samhain) – die Nacht, in der der Schleier dünn ist; geheimnisvoll, aber nicht gruselig",
              (12, 31): "Silvester – Rückblick auf das Jahr und Wünsche für das neue"}


def sonnen_laenge(zeitpunkt: datetime) -> float:
    """Ekliptikale Laenge der Sonne in Grad (0 = Widderpunkt)."""
    jd = zeitpunkt.timestamp() / 86400 + 2440587.5
    n = jd - 2451545.0
    mittel = math.radians((357.528 + 0.9856003 * n) % 360)
    laenge = 280.460 + 0.9856474 * n + 1.915 * math.sin(mittel) + 0.020 * math.sin(2 * mittel)
    return laenge % 360


def _zeichen_um(tag: date) -> int:
    return int(sonnen_laenge(datetime(tag.year, tag.month, tag.day, tzinfo=timezone.utc)) // 30)


def zeichenwechsel(tag: date) -> int | None:
    """Index des Zeichens, in das die Sonne an diesem Tag wechselt (sonst None)."""
    heute, morgen = _zeichen_um(tag), _zeichen_um(tag + timedelta(days=1))
    return morgen if morgen != heute else None


def _herbstanfang(jahr: int) -> date:
    t = date(jahr, 9, 18)
    while zeichenwechsel(t) != 6:
        t += timedelta(days=1)
    return t


def vollmond_name(tag: date) -> tuple[str, str]:
    """(deutscher Name, englischer Name) des Vollmonds an diesem Tag."""
    tage = (tag - _herbstanfang(tag.year)).days
    if -15 < tage <= 15:      # naechster Vollmond zur Tagundnachtgleiche (ein Mondmonat = 29,5 Tage)
        return VOLLMOND_NAMEN[9]
    if 15 < tage <= 45:
        return VOLLMOND_NAMEN[10]
    if tag.month == 9:        # Anfang September, wenn der Erntemond erst im Oktober kommt
        return ("Maismond", "Corn Moon")
    return VOLLMOND_NAMEN[tag.month]


def anlaesse(tag: date, info: dict | None = None) -> list[dict]:
    """Besondere Anlaesse heute und morgen: [{"name", "auftrag", "wann"}] (wann: "heute" / "morgen")."""
    info = info or {}
    out = []
    for wann, t in (("heute", tag), ("morgen", tag + timedelta(days=1))):
        idx = zeichenwechsel(t)
        if idx is not None:
            name = f"{ZEICHEN[idx]}-Saison beginnt"
            if idx in JAHRESZEIT:
                name += f" ({JAHRESZEIT[idx]})"
            out.append({"wann": wann, "name": name,
                        "auftrag": f"Die Sonne wechselt in {ZEICHEN[idx]}: Willkommen in der {ZEICHEN[idx]}-Saison. "
                                   f"Was die nächsten vier Wochen für alle bringen, und ein besonderer Gruß an alle "
                                   f"{ZEICHEN[idx]}-Geborenen (Geburtstagssaison)."})
        fest = FESTE_TAGE.get((t.month, t.day))
        if fest:
            out.append({"wann": wann, "name": fest.split(" – ")[0], "auftrag": fest})
    voll = info.get("vollmond")
    try:
        voll_tag = date.fromisoformat(str(voll["datum"])[:10]) if voll and 0 <= int(voll.get("in_tagen", 99)) <= 1 else None
    except (KeyError, TypeError, ValueError):
        voll_tag = None
    if voll_tag:
        de, en = vollmond_name(voll_tag)
        out.append({"wann": "heute" if voll["in_tagen"] <= 0 else "morgen", "name": f"Vollmond „{de}“ ({en})",
                    "auftrag": f"Der Vollmond heißt traditionell „{de}“ (englisch {en}). Nutze den Namen in der "
                               f"üblichen Form der Sprache des Posts und erkläre kurz, woher er kommt.",
                    "vollmond": True})
    return out
