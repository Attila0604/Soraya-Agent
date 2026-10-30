"""
Post-Bilder auf dem Server (Feed 1080x1350, Story 1080x1920)

Zeichnet dasselbe Bild wie das Dashboard (Sternenhimmel, Soraya-Portal, Mond nach
echter Beleuchtung, Ueberschrift, Unterzeile, Story-Frage, "Link in Bio"), aber ohne
Browser: so kann der Agent Bilder fuer das Wochenpaket, die Reels und spaeter das
automatische Posten selbst erzeugen.

Alles wird in doppelter Groesse gezeichnet und dann verkleinert (glatte Kanten).
Schriften liegen im Ordner fonts/ (SIL Open Font License, siehe fonts/OFL-*.txt).
"""

from __future__ import annotations

import io
import math
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCHRIFTEN = Path(__file__).parent / "fonts"
# Knopf unten im Bild: passt fuer Instagram (Link in Bio) und Facebook (Link unter dem Text)
LINK_IN_BIO = {"de": "Dein Horoskop gratis", "en": "Your free horoscope", "hu": "Ingyenes horoszkópod", "it": "Oroscopo gratis"}
SS = 2  # Zeichen-Massstab (Supersampling)


# ---------------------------------------------------------------------------
# Grundlagen: Farben, Verlaeufe, Schriften
# ---------------------------------------------------------------------------
def _rgb(hex_farbe: str) -> tuple[int, int, int]:
    h = hex_farbe.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _stopps(t: np.ndarray, stopps: list[tuple[float, str, float]]) -> np.ndarray:
    """t (0..1) -> RGBA-Feld; stopps = [(position, "#rrggbb", alpha), ...]"""
    t = np.clip(t, 0, 1)
    pos = np.array([s[0] for s in stopps], dtype=np.float32)
    kanaele = [np.array([_rgb(s[1])[i] for s in stopps], dtype=np.float32) for i in range(3)]
    kanaele.append(np.array([s[2] * 255 for s in stopps], dtype=np.float32))
    feld = np.stack([np.interp(t, pos, k) for k in kanaele], axis=-1)
    return np.clip(feld + 0.5, 0, 255).astype(np.uint8)


def radial(breite: int, hoehe: int, x0, y0, r0, x1, y1, r1, stopps) -> Image.Image:
    """Radialer Verlauf zwischen zwei Kreisen -- wie createRadialGradient im Browser."""
    ys, xs = np.mgrid[0:hoehe, 0:breite].astype(np.float32)
    xs += 0.5
    ys += 0.5
    dx, dy, dr = x1 - x0, y1 - y0, r1 - r0
    px, py = xs - x0, ys - y0
    a = dx * dx + dy * dy - dr * dr
    b = px * dx + py * dy + r0 * dr
    c = px * px + py * py - r0 * r0
    # a t^2 - 2 b t + c = 0; gesucht ist die groessere Loesung (wie im Browser)
    wurzel = np.sqrt(np.maximum(b * b - a * c, 0))
    if abs(a) < 1e-6:
        t = c / (2 * b + 1e-9)
    elif a > 0:
        t = (b + wurzel) / a
    else:
        t = (b - wurzel) / a
    return Image.fromarray(_stopps(t, stopps), "RGBA")


def linear(breite: int, hoehe: int, x0, y0, x1, y1, stopps) -> Image.Image:
    ys, xs = np.mgrid[0:hoehe, 0:breite].astype(np.float32)
    dx, dy = x1 - x0, y1 - y0
    t = ((xs + 0.5 - x0) * dx + (ys + 0.5 - y0) * dy) / (dx * dx + dy * dy)
    return Image.fromarray(_stopps(t, stopps), "RGBA")


@lru_cache(maxsize=64)
def schrift(name: str, groesse: float) -> ImageFont.FreeTypeFont:
    datei = {"cormorant": "CormorantGaramond-SemiBold.ttf", "cinzel": "Cinzel-SemiBold.ttf",
             "inter400": "Inter-Regular.ttf", "inter500": "Inter-Medium.ttf", "inter600": "Inter-SemiBold.ttf",
             "zeichen": "NotoSansSymbols-Zodiac.ttf"}[name]
    return ImageFont.truetype(str(SCHRIFTEN / datei), max(1, int(round(groesse))))


def _mit_alpha(bild: Image.Image, faktor: float) -> Image.Image:
    if faktor >= 1:
        return bild
    r, g, b, a = bild.split()
    return Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * faktor))))


def _durch_maske(farbe: Image.Image, maske: Image.Image, alpha: float = 1.0) -> Image.Image:
    """Farbflaeche (RGBA) nur dort, wo die Maske (L) gesetzt ist."""
    a = np.asarray(farbe.getchannel("A"), dtype=np.float32) * (np.asarray(maske, dtype=np.float32) / 255) * alpha
    out = farbe.copy()
    out.putalpha(Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "L"))
    return out


def aufkleben(leinwand: Image.Image, ebene: Image.Image, pos=(0, 0)) -> None:
    """RGBA-Ebene auf die RGB-Leinwand legen (Alpha wird gemischt)."""
    leinwand.paste(ebene, (int(round(pos[0])), int(round(pos[1]))), ebene)


def zufall(seed):
    """Gleiche Zufallsfolge wie im Dashboard (zufall(p.id)), damit die Sterne gleich liegen."""
    try:
        n = float(seed) or 1
    except (TypeError, ValueError):
        n = 1
    n = int(n) if n == int(n) else n
    s = [n * 9301 + 49297]

    def weiter() -> float:
        s[0] = (s[0] * 9301 + 49297) % 233280
        return s[0] / 233280
    return weiter


# ---------------------------------------------------------------------------
# Formen
# ---------------------------------------------------------------------------
def _bogen(cx, cy, r, von_grad, bis_grad, schritte=64):
    return [(cx + r * math.cos(math.radians(von_grad + (bis_grad - von_grad) * i / schritte)),
             cy + r * math.sin(math.radians(von_grad + (bis_grad - von_grad) * i / schritte))) for i in range(schritte + 1)]


def stern_punkte(cx, cy, h):
    """Vierzackiger Funkelstern wie im Logo."""
    w, b = h * 0.2, h * 0.74
    return [(cx, cy - h), (cx + w, cy - w), (cx + b, cy), (cx + w, cy + w), (cx, cy + h),
            (cx - w, cy + w), (cx - b, cy), (cx - w, cy - w)]


def _linie(draw: ImageDraw.ImageDraw, punkte, breite, fuellung=255, rund=False):
    draw.line(punkte, fill=fuellung, width=max(1, int(round(breite))), joint="curve")
    if rund:
        for x, y in (punkte[0], punkte[-1]):
            draw.ellipse([x - breite / 2, y - breite / 2, x + breite / 2, y + breite / 2], fill=fuellung)


@lru_cache(maxsize=16)
def portal(hoehe: int) -> Image.Image:
    """Das Soraya-Zeichen (Raster 512, Zeichen 91..421 x 112..424) in der gewuenschten Hoehe.
    Rueckgabe: RGBA-Bild, dessen Ursprung dem Rasterpunkt (0, 0) entspricht; Breite = 512 * s."""
    k = 4 if hoehe <= 320 else 2                      # eigenes Supersampling (kleines Zeichen: mehr)
    s = hoehe / 312 * k
    gr = int(math.ceil(512 * s))
    P = lambda x, y: (x * s, y * s)                   # noqa: E731
    q = 4                                             # weiche Verlaeufe in Viertel-Aufloesung rechnen
    glatt = lambda img: img.resize((gr, gr), Image.BICUBIC)   # noqa: E731
    gold = glatt(linear(gr // q, gr // q, 91 * s / q, 112 * s / q, 421 * s / q, 424 * s / q,
                        [(0, "#fff5d1", 1), (0.42, "#ebcb86", 1), (1, "#a47b35", 1)]))
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))

    # Innenflaeche des Bogens
    bogen = [P(160, 392), P(160, 236)] + [P(x, y) for x, y in _bogen(256, 236, 96, 180, 360)] + [P(352, 392)]
    flaeche = Image.new("L", (gr, gr), 0)
    ImageDraw.Draw(flaeche).polygon(bogen, fill=255)
    innen = glatt(linear(gr // q, gr // q, 0, 140 * s / q, 0, 392 * s / q, [(0, "#2b1756", 1), (1, "#120a28", 1)]))
    bild.alpha_composite(_durch_maske(innen, flaeche))

    # Art-deco-Strahlen, nur innerhalb des Bogens
    strahlen = Image.new("L", (gr, gr), 0)
    d = ImageDraw.Draw(strahlen)
    for a in range(18, 163, 12):
        r = math.radians(a)
        _linie(d, [P(256, 392), P(256 + 180 * math.cos(r), 392 - 180 * math.sin(r))], 1.6 * s)
    strahlen = Image.fromarray(np.minimum(np.asarray(strahlen), np.asarray(flaeche)), "L")
    farbe = Image.new("RGBA", (gr, gr), (235, 203, 134, 255))
    bild.alpha_composite(_durch_maske(farbe, strahlen, 0.24))

    def gold_maske(zeichnen, alpha=1.0):
        m = Image.new("L", (gr, gr), 0)
        zeichnen(ImageDraw.Draw(m))
        bild.alpha_composite(_durch_maske(gold, m, alpha))

    innerer = [P(181, 392), P(181, 238)] + [P(x, y) for x, y in _bogen(256, 238, 75, 180, 360)] + [P(331, 392)]
    gold_maske(lambda d: _linie(d, innerer, 3 * s), 0.7)
    gold_maske(lambda d: _linie(d, bogen, 11 * s))
    gold_maske(lambda d: d.polygon([P(256, 126), P(266, 140), P(256, 154), P(246, 140)], fill=255))   # Schlussstein

    schein = glatt(radial(gr // q, gr // q, 256 * s / q, 232 * s / q, 0, 256 * s / q, 232 * s / q, 70 * s / q,
                          [(0, "#ffe9b0", 0.5), (1, "#ffe9b0", 0)]))
    bild.alpha_composite(schein)

    def sichel(d):                                    # Mondsichel: Kreis minus versetzter Kreis
        d.ellipse([P(212, 188), P(300, 276)], fill=255)
        d.ellipse([P(236, 178), P(316, 258)], fill=0)
    gold_maske(sichel)
    gold_maske(lambda d: d.polygon([P(x, y) for x, y in stern_punkte(256, 322, 40)], fill=255))
    gold_maske(lambda d: _linie(d, [P(120, 392), P(392, 392)], 8 * s, rund=True))
    gold_maske(lambda d: _linie(d, [P(150, 412), P(362, 412)], 3.5 * s, rund=True), 0.75)
    hell = ImageDraw.Draw(bild)
    for x, y, h in ((122, 170, 12), (392, 146, 15), (410, 252, 9), (104, 300, 7)):
        hell.polygon([P(px, py) for px, py in stern_punkte(x, y, h)], fill=(255, 245, 209, 255))
    return bild.resize((max(1, gr // k), max(1, gr // k)), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Mond: echte Oberflaeche (Meere, Hochland, Strahlenkrater), Licht nach Phase, Erdschein, Lichthof
# ---------------------------------------------------------------------------
# Alles in selenografischen Koordinaten (Breite, Laenge in Grad; Osten = rechts, Norden = oben, Blick von der
# Nordhalbkugel). Die Oberflaeche wird einmal berechnet (Albedo + Relief, lru_cache) und danach nur noch
# beleuchtet -- das geht schnell, und der Mond ist in jedem Bild derselbe.

# Meere: (Breite, Laenge, Radius in Grad, Gewicht, Streckung Ost-West, Ton: >1 dunkler, <1 heller)
MARIA = [
    (34, -17, 17.0, 1.0, 1.1, 1.00),   # Mare Imbrium
    (40, -2, 7.0, 0.8, 1.2, 1.00),
    (28, 18, 9.5, 1.0, 1.0, 0.86),     # Mare Serenitatis (etwas heller)
    (8, 30, 10.0, 1.0, 1.3, 1.08),     # Mare Tranquillitatis (dunkel)
    (2, 22, 5.0, 0.9, 1.0, 1.05),
    (17, 59, 7.5, 1.1, 1.25, 1.05),    # Mare Crisium
    (-5, 51, 7.0, 0.9, 0.7, 0.95),     # Mare Fecunditatis
    (-14, 54, 5.0, 0.8, 0.8, 0.95),
    (-15, 34, 4.8, 0.9, 1.0, 0.95),    # Mare Nectaris
    (-20, -15, 9.5, 0.9, 1.2, 0.80),   # Mare Nubium
    (-10, -22, 5.5, 0.9, 1.0, 0.92),   # Mare Cognitum
    (-24, -39, 6.0, 1.0, 1.0, 1.00),   # Mare Humorum
    (8, -30, 8.0, 0.8, 1.3, 0.80),     # Mare Insularum
    (13, 4, 3.6, 0.75, 1.4, 0.85),     # Mare Vaporum
    (2, 1, 2.6, 0.65, 1.3, 0.80),      # Sinus Medii
    (45, -31, 4.0, 0.8, 1.6, 1.00),    # Sinus Iridum
    (38, 30, 4.5, 0.7, 1.0, 0.85),     # Lacus Somniorum
    (56, -35, 4.0, 0.8, 2.6, 0.85),    # Mare Frigoris (langes, schmales Band)
    (57, -8, 3.6, 0.8, 2.8, 0.85),
    (58, 18, 3.2, 0.7, 2.6, 0.82),
    (42, -50, 11.0, 0.9, 0.9, 1.00),   # Oceanus Procellarum (aus mehreren Teilen)
    (24, -55, 13.0, 1.0, 0.85, 1.02),
    (8, -52, 12.0, 1.0, 0.8, 1.00),
    (-6, -45, 8.0, 0.9, 1.0, 0.95),
    (14, -68, 8.0, 0.85, 0.7, 0.98),
    (-5, -68, 2.6, 1.1, 1.0, 1.15),    # Grimaldi (sehr dunkler Boden)
    (51.6, -9.3, 1.6, 1.2, 1.0, 1.05), # Plato (dunkler Kraterboden)
    (13, 86, 3.5, 0.7, 0.6, 0.85),     # Mare Marginis
    (-1, 87, 4.0, 0.7, 0.6, 0.85),     # Mare Smythii
    (-46, 86, 5.0, 0.55, 0.6, 0.75),   # Mare Australe
    (57, 82, 3.0, 0.6, 0.7, 0.80),     # Mare Humboldtianum
]
# Grosse Krater: (Breite, Laenge, Radius in Grad, Tiefe)
KRATER = [
    (-43.3, -11.2, 1.45, 1.2), (9.6, -20.1, 1.55, 1.2), (8.1, -38.0, 0.55, 1.1), (23.7, -47.4, 0.65, 1.1),
    (51.6, -9.3, 1.7, 0.35), (-58.4, -14.4, 3.8, 0.6), (-9.3, -1.9, 2.5, 0.35), (-13.4, -3.2, 1.9, 0.55),
    (-18.2, -1.9, 1.6, 0.65), (-11.4, 26.4, 1.65, 1.0), (-13.2, 24.0, 1.6, 0.7), (-18.0, 23.6, 1.7, 0.6),
    (-8.9, 61.0, 2.2, 0.9), (-25.1, 60.4, 2.9, 0.8), (29.7, -4.0, 1.35, 0.45), (14.5, -11.3, 0.95, 1.0),
    (-49.6, -21.7, 2.5, 0.6), (-41.1, 5.8, 2.2, 0.55), (-44.9, 40.3, 3.3, 0.45), (31.8, 29.9, 1.6, 0.4),
    (16.1, 46.8, 0.45, 1.0), (-50.5, -6.2, 3.0, 0.5), (-29.7, -1.0, 1.9, 0.6), (46.7, 39.1, 1.4, 0.7),
    (49.0, 44.4, 1.5, 0.7), (-34.0, -31.0, 2.0, 0.55), (-26.0, 8.0, 1.8, 0.5), (-60.0, 30.0, 2.6, 0.55),
]
# Strahlenkrater: (Breite, Laenge, Zahl der Strahlen, Laenge der Strahlen in Grad, Helligkeit, Hof in Grad)
STRAHLEN = [
    (-43.3, -11.2, 16, 48, 0.42, 1.8),   # Tycho: lange Strahlen ueber den halben Mond
    (9.6, -20.1, 18, 16, 0.32, 2.6),     # Copernicus
    (8.1, -38.0, 12, 9, 0.22, 2.2),      # Kepler
    (23.7, -47.4, 7, 5, 0.18, 1.2),      # Aristarchus (hellster Fleck)
    (16.1, 46.8, 6, 8, 0.16, 1.2),       # Proclus
]
MOND_RASTER = 1024


def _vektor(breite, laenge):
    b, l = math.radians(breite), math.radians(laenge)
    return np.array([math.cos(b) * math.sin(l), math.sin(b), math.cos(b) * math.cos(l)], np.float32)


def _ost_nord(breite, laenge):
    """Ost- und Nordrichtung an einem Punkt der Kugel."""
    c = _vektor(breite, laenge)
    e = np.array([math.cos(math.radians(laenge)), 0, -math.sin(math.radians(laenge))], np.float32)
    return c, e, np.cross(c, e)


def _wertrauschen(u: np.ndarray, v: np.ndarray, zellen: int, seed: int) -> np.ndarray:
    """Glattes Wertrauschen (0..1) an den Stellen u, v (0..1)."""
    g = np.random.default_rng(seed).random((zellen + 2, zellen + 2)).astype(np.float32)
    x, y = u * zellen, v * zellen
    i, j = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    fx, fy = x - i, y - j
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    i, j = np.clip(i, 0, zellen), np.clip(j, 0, zellen)
    a = g[j, i] + (g[j, i + 1] - g[j, i]) * fx
    b = g[j + 1, i] + (g[j + 1, i + 1] - g[j + 1, i]) * fx
    return a + (b - a) * fy


def _fbm(u, v, start: int, oktaven: int, seed: int) -> np.ndarray:
    summe, gewicht, w = np.zeros_like(u), 0.0, 1.0
    for o in range(oktaven):
        summe += w * _wertrauschen(u, v, start * 2 ** o, seed + o * 17)
        gewicht += w
        w *= 0.55
    return summe / gewicht - 0.5          # etwa -0.5..0.5


def _kugel(n: int):
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    x = (xs + 0.5) / n * 2 - 1
    y = 1 - (ys + 0.5) / n * 2                       # Norden oben
    z = np.sqrt(np.clip(1 - x * x - y * y, 0, 1))
    breite = np.arcsin(np.clip(y, -1, 1))
    laenge = np.arctan2(x, np.maximum(z, 1e-4))
    return x, y, z, (laenge / math.pi + 1) / 2, breite / math.pi + 0.5


def _gross(feld: np.ndarray, n: int) -> np.ndarray:
    return np.asarray(Image.fromarray(feld.astype(np.float32), "F").resize((n, n), Image.BICUBIC), np.float32)


def _klein(feld: np.ndarray, n: int) -> np.ndarray:
    return np.asarray(Image.fromarray(feld.astype(np.float32), "F").resize((n, n), Image.LANCZOS), np.float32)


@lru_cache(maxsize=1)
def _mond_flaechen() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Grosse, weiche Strukturen in 384er-Aufloesung: Meer-Feld, Kuestenschaerfe, Ton der Meere, Strahlen."""
    n = 384
    x, y, z, u, v = _kugel(n)
    P = np.stack([x, y, z])
    grad = math.pi / 180
    # Meere: die Einzelflecken werden weich vereinigt und mit verrauschter Schwelle geschnitten -> zusammen-
    # haengende, natuerlich ausgefranste Flaechen wie auf dem echten Mond (keine runden Kleckse)
    feld = np.zeros_like(x)
    summe = np.zeros_like(x)
    ton = np.zeros_like(x)
    for br, la, rad, gew, streck, t in MARIA:
        c, e, nn = _ost_nord(br, la)
        winkel = np.arctan2(np.hypot(np.tensordot(e, P, 1) / streck, np.tensordot(nn, P, 1)),
                            np.tensordot(c, P, 1)) / grad
        f = gew * np.exp(-(winkel / rad) ** 2 * 0.8)
        feld += f ** 3
        summe += f
        ton += f * t
    ton = ton / np.maximum(summe, 1e-4)
    feld = feld ** (1 / 3) * 0.9 + summe * 0.1
    rand = _fbm(u, v, 5, 6, 3) * 0.6 + _fbm(u, v, 40, 3, 31) * 0.25 + _fbm(u, v, 110, 2, 37) * 0.15
    feld = feld + rand * 0.85
    weich = 0.12 + 0.30 * np.clip(_fbm(u, v, 4, 2, 41) + 0.5, 0, 1)      # mal scharfe, mal weiche Kuesten
    ton = (0.84 + 0.6 * _fbm(u, v, 6, 4, 9) + 0.3 * _fbm(u, v, 30, 3, 19)) * ton
    # Strahlen: breite, ausfransende helle Streifen, die nach aussen verblassen
    strahlen = np.zeros_like(x)
    for br, la, zahl, lang, staerke, hof in STRAHLEN:
        c, e, nn = _ost_nord(br, la)
        d = np.arccos(np.clip(np.tensordot(c, P, 1), -1, 1)) / grad
        richtung = np.arctan2(np.tensordot(e, P, 1), np.tensordot(nn, P, 1))
        rng = np.random.default_rng(int(abs(br * 100 + la)))
        s_max = np.zeros_like(x)
        for _ in range(zahl):
            th = rng.uniform(-math.pi, math.pi)
            l_i = lang * rng.uniform(0.3, 1.0)
            breit = rng.uniform(0.8, 2.2)                         # Breite in Grad
            dth = np.angle(np.exp(1j * (richtung - th)))
            quer = np.abs(dth) * np.maximum(d, 1.0) / (1 + d / (l_i * 1.5))   # wird nach aussen etwas breiter
            s = np.exp(-(quer / breit) ** 2) * np.exp(-d / l_i) * np.clip(d / 2.0, 0, 1)
            s_max = np.maximum(s_max, s * rng.uniform(0.5, 1.0))
        flecken = np.clip(0.55 + 1.6 * _fbm(u * 1.0, v, 30, 3, int(abs(la)) + 400), 0, 1.2)
        strahlen += staerke * s_max * flecken + staerke * 1.1 * np.exp(-(d / hof) ** 2)
    return feld.astype(np.float32), weich.astype(np.float32), ton.astype(np.float32), strahlen.astype(np.float32)


@lru_cache(maxsize=4)
def _mond_karte(n: int) -> tuple:
    """Oberflaeche auf einem n x n Raster (der Mond fuellt das Raster): (Albedo, Meer, z, Normale, Kante, Hoehe).
    Fester Zufall: der Mond ist in jedem Bild derselbe."""
    if n != MOND_RASTER:      # kleinere Raster aus dem grossen verkleinern (gleicher Mond in jeder Groesse)
        albedo, meer, _, _, _, hoehe = _mond_karte(MOND_RASTER)
        albedo, meer, hoehe = _klein(albedo, n), _klein(meer, n), _klein(hoehe, n)
    else:
        x, y, z, u, v = _kugel(n)
        feld, weich, ton, strahlen = (_gross(f, n) for f in _mond_flaechen())
        # Kuesten der Meere erst hier schneiden (mit feinem Rauschen): scharf ausgefranst statt verschwommen
        feld = feld + 0.07 * _fbm(u, v, 160, 3, 43)
        meer = np.clip((feld - 0.47) / np.maximum(weich, 0.05) + 0.5, 0, 1)
        meer = np.clip(meer * meer * (3 - 2 * meer) * ton, 0, 1.2)
        # Hochland hell und fein gesprenkelt, Meere dunkel (echte Albedo etwa 0.12 zu 0.07)
        fein = _fbm(u, v, 60, 4, 7)
        hochland = 0.16 * _fbm(u, v, 9, 4, 5) + 0.07 * fein
        meer_fein = 0.05 * _fbm(u, v, 90, 3, 23) * np.clip(meer, 0, 1)
        albedo = 1.0 + hochland * (1 - 0.6 * np.clip(meer, 0, 1)) - 0.42 * meer + meer_fein + strahlen * (1 - 0.3 * meer)
        # Relief: Hochland huegelig (macht die Schattengrenze unruhig wie in echt), Meere tiefer und glatt
        hoehe = (0.011 * _fbm(u, v, 16, 5, 13) + 0.0012 * fein) * (1 - np.clip(meer, 0, 1) * 0.85) \
            - 0.003 * np.clip(meer, 0, 1)
        P = np.stack([x, y, z])
        innen = (x * x + y * y) < 1
        grad = math.pi / 180
        # Krater: Schuessel + Wall, im Hochland viel dichter als in den Meeren
        rng = np.random.default_rng(21)
        liste = [k + (False,) for k in KRATER]
        while len(liste) < 2200:
            br = math.degrees(math.asin(rng.uniform(-1, 1)))
            la = rng.uniform(-90, 90)
            rad = 0.18 * (1 - rng.random()) ** (-1 / 1.9)            # viele kleine, wenige grosse
            if rad > 2.4:
                continue
            cv = _vektor(br, la)
            if cv[2] < 0.05:
                continue
            ix, iy = int((cv[0] + 1) / 2 * (n - 1)), int((1 - cv[1]) / 2 * (n - 1))
            if rng.random() < min(1.0, meer[iy, ix]) * 0.9:
                continue
            liste.append((br, la, rad, rng.uniform(0.5, 1.0), rng.random() < 0.06 and rad < 0.7))
        for br, la, rad, tiefe, frisch in liste:
            cv = _vektor(br, la)
            rp = rad * grad * n / 2                                  # Radius in Rasterpunkten
            if rp < 0.8:
                continue
            cx, cy = (cv[0] + 1) / 2 * n, (1 - cv[1]) / 2 * n
            w = rp * 2.2 + 2
            x0, x1 = max(0, int(cx - w)), min(n, int(cx + w) + 1)
            y0, y1 = max(0, int(cy - w)), min(n, int(cy + w) + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            d = np.arccos(np.clip(np.tensordot(cv, P[:, y0:y1, x0:x1], 1), -1, 1)) / (rad * grad)  # in Kraterradien
            tief = 0.06 * rad * grad * tiefe * (1.4 if rad < 0.8 else 1.0)
            schuessel = np.where(d < 1, d * d - 1, 0) * tief
            if rad > 1.2:   # grosse Krater: flacher Boden mit Zentralberg
                schuessel = np.where(d < 1, np.maximum(d * d - 1, -0.6), 0) * tief \
                    + 0.25 * tief * np.exp(-(d / 0.15) ** 2)
            wall = 0.3 * tief * np.exp(-((d - 1) / 0.35) ** 2) * np.where(d < 1, 1, np.exp(-(d - 1) * 0.8))
            hoehe[y0:y1, x0:x1] += np.where(innen[y0:y1, x0:x1], schuessel + wall, 0)
            albedo[y0:y1, x0:x1] += 0.015 * tiefe * np.exp(-((d - 0.95) / 0.25) ** 2)  # kaum hellerer Wall
            if frisch:   # junge Krater: kleiner heller Fleck mit Hof (bei Vollmond gut sichtbar)
                albedo[y0:y1, x0:x1] += 0.14 * np.exp(-(d / 1.4) ** 2)
        albedo = np.clip(albedo, 0.3, 1.6).astype(np.float32)
        hoehe = hoehe.astype(np.float32)
    x, y, z, _, _ = _kugel(n)
    # Normale aus dem Relief: Gefaelle auf der Kugeloberflaeche (nicht im Bild), sonst wirken Krater am Rand
    # durch die Verkuerzung viel zu steil
    zeile, spalte = np.gradient(hoehe * n / 2)
    hx, hy = spalte, -zeile
    vh = x * hx + y * hy
    cx_, cy_ = hx - x * vh, hy - y * vh
    rand_aus = np.clip((z - 0.06) / 0.25, 0, 1)                 # am Rand Relief ausblenden (keine Kerben)
    cx_, cy_ = cx_ * rand_aus, cy_ * rand_aus
    zs = np.maximum(z, 0.05)
    nx, ny, nz = x - cx_, y - cy_, z + (cx_ * x + cy_ * y) / zs
    laenge_n = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    normale = np.stack([nx / laenge_n, ny / laenge_n, nz / laenge_n]).astype(np.float32)
    kante = np.clip((1 - np.sqrt(x * x + y * y)) * n / 2 + 0.5, 0, 1).astype(np.float32)   # glatte Kante
    return albedo, meer, z, normale, kante, hoehe


def _sonne(phase_index, beleuchtung):
    """(Richtung zur Sonne, beleuchteter Anteil) -- Blick entlang +z, x rechts, y oben; None = Neumond."""
    if phase_index is None:
        return None
    phase_index = int(phase_index) % 8
    try:
        k = min(1.0, max(0.0, float(beleuchtung) / 100))
    except (TypeError, ValueError):
        k = (1 - math.cos(math.radians(phase_index * 45))) / 2
    if phase_index == 0:                                        # Neumond: nur Erdschein
        return None
    if phase_index == 4:
        k = max(k, 0.985)
    e = math.acos(max(-1.0, min(1.0, 1 - 2 * k)))               # Elongation 0..pi
    seite = 1 if phase_index <= 4 else -1                         # zunehmend: Licht von rechts
    return np.array([seite * math.sin(e), 0.0, -math.cos(e)], np.float32), k


@lru_cache(maxsize=24)
def _mond_gerendert(n: int, phase_index, beleuchtung, einfach: bool) -> np.ndarray:
    """RGBA (uint8) des beleuchteten Mondes auf dem n-Raster."""
    albedo, meer, z, normale, kante, _ = _mond_karte(n)
    x, y, _, _, _ = _kugel(n)
    if einfach:   # kleine Monde: ohne feines Relief und Sprenkel, damit es klar und ruhig bleibt
        albedo = _gross(_klein(albedo, n * 2 // 3), n)
        normale = np.stack([x, y, z])
    sonne = _sonne(phase_index, beleuchtung)
    hoch = np.array([1.00, 0.93, 0.80], np.float32)[:, None, None]     # warmes Elfenbein / Champagner
    tief = np.array([0.72, 0.70, 0.72], np.float32)[:, None, None]     # Meere: kuehles Grau mit Hauch Violett
    t = np.clip(meer, 0, 1)[None]
    grundfarbe = (hoch * (1 - t) + tief * t) * albedo[None]
    mu = np.maximum(z, 1e-3)
    k = 0.0
    licht = np.zeros_like(z)
    if sonne is not None:
        s, k = sonne
        mu0 = np.tensordot(s, normale, 1)
        glatt0 = s[0] * x + s[1] * y + s[2] * z
        m0 = np.maximum(mu0, 0)
        # Mond-Lambert: fast flache Vollmondscheibe, leicht dunkler zum Rand, heller Saum an der Sichel
        L = 0.62
        licht = 2 * L * m0 / (m0 + mu) + (1 - L) * m0
        # Schattengrenze: klar, aber nicht hart; Krater werfen nahe der Grenze Schatten
        licht *= np.clip((glatt0 + 0.03) / 0.06, 0, 1)
        licht *= np.clip(mu0 / 0.03 + 0.1, 0, 1) ** 1.3
    rgb = grundfarbe * licht[None] * 0.88
    # Erdschein: sehr leise, blaeulich-violett, am staerksten bei schmaler Sichel
    erd = (0.022 + 0.05 * (1 - k) ** 3) * (1.8 if einfach else 1.0)
    dunkel = np.clip(1 - licht * 4, 0, 1)[None]
    erdfarbe = np.array([0.60, 0.62, 0.95], np.float32)[:, None, None]
    rgb += dunkel * erd * albedo[None] * (0.6 + 0.4 * mu[None]) * erdfarbe
    rgb += dunkel * np.array([0.028, 0.022, 0.052], np.float32)[:, None, None]    # Grundton der Nachtseite
    # zarter silberner Rand auf der Nachtseite, damit auch der Neumond als Scheibe lesbar bleibt
    saum = np.exp(-np.clip(1 - np.sqrt(x * x + y * y), 0, 1) / 0.012) * 0.07 * (1 - k) ** 2
    rgb += dunkel * saum[None] * np.array([0.85, 0.82, 0.95], np.float32)[:, None, None]
    rgb = np.clip((1 - np.exp(-rgb * 1.6)) / (1 - math.exp(-1.6 * 1.25)), 0, 1)     # weiche Lichter, nichts brennt aus
    rgba = np.concatenate([rgb, kante[None]]).transpose(1, 2, 0)
    return np.clip(rgba * 255 + 0.5, 0, 255).astype(np.uint8)


def _beleuchtung_rund(beleuchtung):
    try:
        return round(float(beleuchtung), 0)
    except (TypeError, ValueError):
        return None


def mond(r: float, phase_index, beleuchtung) -> Image.Image:
    """Mondscheibe mit Radius r (Mittelpunkt = Bildmitte), Licht nach echter Beleuchtung in %:
    zunehmend rechts, abnehmend links (Blick von der Nordhalbkugel). Neumond (Index 0): nur Erdschein.
    Kleine Monde (Wochenleiste, Karten) kommen in einer ruhigeren Fassung mit zartem Goldrand."""
    gr = math.ceil(2 * r + 4)
    d = max(1, round(2 * r))
    einfach = d < 150
    n = 256 if einfach else (512 if d <= 440 else MOND_RASTER)
    roh = _mond_gerendert(n, None if phase_index is None else int(phase_index), _beleuchtung_rund(beleuchtung), einfach)
    ebene = Image.fromarray(roh, "RGBA")
    # mit vormultipliziertem Alpha verkleinern, sonst bekommt der Rand einen hellen Saum
    ebene = ebene.convert("RGBa").resize((d, d), Image.LANCZOS).convert("RGBA")
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    bild.paste(ebene, (round(gr / 2 - d / 2), round(gr / 2 - d / 2)))
    if einfach:
        ring = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
        c = gr / 2
        ImageDraw.Draw(ring).ellipse([c - r - 0.5, c - r - 0.5, c + r + 0.5, c + r + 0.5],
                                     outline=(201, 168, 106, 90), width=max(1, round(r / 30)))
        bild.alpha_composite(ring)
    return bild


def mond_schein(r: float, phase_index, beleuchtung, linie: bool = True, staerke: float = 1.0) -> Image.Image:
    """Lichthof um den Mond (Groesse 4r, Mittelpunkt = Bildmitte): weicher Schein, der vom beleuchteten Teil
    ausgeht (innen silbrig, aussen warmes Gold), dazu auf Wunsch eine feine goldene Kreislinie hinter dem Mond."""
    gr = max(8, round(4 * r))
    q = 160                                          # in kleiner Aufloesung rechnen, dann vergroessern
    roh = _mond_gerendert(256, None if phase_index is None else int(phase_index), _beleuchtung_rund(beleuchtung), True)
    hell = roh[..., :3].mean(axis=2) / 255 * (roh[..., 3] / 255)
    lum = Image.fromarray(np.clip(hell * 255, 0, 255).astype(np.uint8), "L").resize((q // 2, q // 2), Image.BILINEAR)
    feld = Image.new("L", (q, q), 0)
    feld.paste(lum, (q // 4, q // 4))
    nah = np.asarray(feld.filter(ImageFilter.GaussianBlur(q * 0.03)), np.float32) / 255
    weit = np.asarray(feld.filter(ImageFilter.GaussianBlur(q * 0.15)), np.float32) / 255
    ys, xs = np.mgrid[0:q, 0:q].astype(np.float32)
    rr = np.hypot(xs + 0.5 - q / 2, ys + 0.5 - q / 2) / (q / 4)    # in Mondradien
    aura = np.exp(-((rr / 1.7) ** 2)) * 0.06                       # ganz leiser Hof (auch beim Neumond)
    a = np.clip((nah * 0.22 + weit * 0.75) * staerke + aura, 0, 1)
    a *= np.clip((1.95 - rr) / 0.7, 0, 1) ** 2                     # zum Rand sicher auf null (kein Kasten)
    silber = np.array([255, 247, 230], np.float32)
    gold = np.array([232, 196, 128], np.float32)
    mix = np.clip(nah * 1.4 / (nah + weit + 1e-3), 0, 1)[..., None]
    rgb = gold + (silber - gold) * mix
    rgba = np.concatenate([rgb + 0.5, (a * 255)[..., None]], axis=2)
    schein = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA").resize((gr, gr), Image.BICUBIC)
    if linie:   # feine Goldlinie: oben kraeftiger, nach unten ausklingend
        ys, xs = np.mgrid[0:gr, 0:gr].astype(np.float32)
        dx, dy = xs + 0.5 - gr / 2, ys + 0.5 - gr / 2
        dist = np.hypot(dx, dy)
        breite = max(1.0, r / 120)
        ring = np.clip(1 - np.abs(dist - r * 1.17) / breite, 0, 1)
        verlauf = 0.2 + 0.8 * (0.5 - 0.5 * dy / np.maximum(dist, 1))
        ebene = np.zeros((gr, gr, 4), np.uint8)
        ebene[..., 0], ebene[..., 1], ebene[..., 2] = 226, 192, 128
        ebene[..., 3] = np.clip(ring * verlauf * 140, 0, 255).astype(np.uint8)
        schein.alpha_composite(Image.fromarray(ebene, "RGBA"))
    return schein


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
# Emojis: die Textschriften haben keine (sonst erscheinen leere Kaestchen). Sie kommen aus einem kleinen
# Auszug von Noto Color Emoji (fonts/NotoColorEmoji-Soraya.ttf, OFL); was dort fehlt, wird weggelassen.
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]"
                    r"[\uFE0F\u200D\U0001F3FB-\U0001F3FF\u20E3]*"
                    r"(?:[\U0001F000-\U0001FAFF\u2600-\u27BF][\uFE0F\U0001F3FB-\U0001F3FF]*)*")
EMOJI_GROESSE = 109        # die Farb-Emojis gibt es nur in dieser Groesse, sie werden danach skaliert
EMOJI_BREITE = 1.18        # Platz je Emoji in Schriftgroessen


@lru_cache(maxsize=1)
def _emoji_schrift():
    try:
        return ImageFont.truetype(str(SCHRIFTEN / "NotoColorEmoji-Soraya.ttf"), EMOJI_GROESSE)
    except OSError:
        return None


@lru_cache(maxsize=256)
def _emoji_bild(zeichen: str) -> Image.Image | None:
    """Ein Emoji als RGBA in Originalgroesse (None, wenn es nicht im Auszug ist)."""
    font = _emoji_schrift()
    basis = zeichen.replace("\uFE0F", "")[:1]
    if not font or not basis or ord(basis) not in _emoji_zeichen():
        return None
    ebene = Image.new("RGBA", (EMOJI_GROESSE * 3 // 2, EMOJI_GROESSE * 3 // 2), (0, 0, 0, 0))
    ImageDraw.Draw(ebene).text((ebene.width / 2, ebene.height / 2), basis, font=font, embedded_color=True, anchor="mm")
    box = ebene.getbbox()
    return ebene.crop(box) if box else None


@lru_cache(maxsize=1)
def _emoji_zeichen() -> frozenset:
    """Welche Zeichen der Auszug kennt (aus der Zeichentabelle der Schrift)."""
    try:
        return frozenset(_cmap(str(SCHRIFTEN / "NotoColorEmoji-Soraya.ttf")) if _emoji_schrift() else ())
    except Exception:  # noqa: BLE001
        return frozenset()


def _cmap(pfad: str) -> list[int]:
    """Zeichen einer TrueType-Datei (nur die Format-12/4-Tabellen, ohne fontTools)."""
    import struct
    with open(pfad, "rb") as f:
        daten = f.read()
    anzahl = struct.unpack(">H", daten[4:6])[0]
    for i in range(anzahl):
        tag, _, off, _ = struct.unpack(">4sIII", daten[12 + 16 * i: 28 + 16 * i])
        if tag == b"cmap":
            break
    else:
        return []
    zeichen = []
    n = struct.unpack(">H", daten[off + 2: off + 4])[0]
    for i in range(n):
        _, _, sub = struct.unpack(">HHI", daten[off + 4 + 8 * i: off + 12 + 8 * i])
        t = off + sub
        if struct.unpack(">H", daten[t:t + 2])[0] == 12:
            gruppen = struct.unpack(">I", daten[t + 12:t + 16])[0]
            for g in range(gruppen):
                a, b, _ = struct.unpack(">III", daten[t + 16 + 12 * g: t + 28 + 12 * g])
                zeichen.extend(range(a, b + 1))
            return zeichen
    return zeichen


def _teile(text: str) -> list[tuple[str, bool]]:
    """Text in Stuecke zerlegen: (Text, False) und (Emoji, True); unbekannte Emojis fallen weg."""
    teile, pos = [], 0
    text = re.sub(r"[\uFE0F\u20E3\u200D]", "", text) if not _EMOJI.search(text) else text
    for m in _EMOJI.finditer(text):
        if m.start() > pos:
            teile.append((re.sub(r"[\uFE0F\u20E3\u200D]", "", text[pos:m.start()]), False))
        if _emoji_bild(m.group(0)) is not None:
            teile.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        teile.append((re.sub(r"[\uFE0F\u20E3\u200D]", "", text[pos:]), False))
    return teile


def ohne_emojis(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", str(text or ""))).strip()


def laenge(font: ImageFont.FreeTypeFont, text: str) -> float:
    """Breite eines Textes mit Emojis (fuer den Zeilenumbruch)."""
    if not _EMOJI.search(text) and not re.search(r"[\uFE0F\u20E3]", text):
        return font.getlength(text)
    return sum(font.size * EMOJI_BREITE if emoji else font.getlength(t) for t, emoji in _teile(text))


def text_mit_emojis(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, anchor="ms") -> None:
    """Wie draw.text (Anker "ms" oder "ls"), aber Emojis erscheinen als Farb-Emojis."""
    if not _EMOJI.search(text) and not re.search(r"[\uFE0F\u20E3]", text):
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        return
    x, y = xy
    if anchor[0] == "m":
        x -= laenge(font, text) / 2
    bild = getattr(draw, "_image", None)
    for t, emoji in _teile(text):
        if not emoji:
            draw.text((x, y), t, font=font, fill=fill, anchor="ls")
            x += font.getlength(t)
            continue
        e = _emoji_bild(t)
        h = font.size * 0.92
        e = e.resize((max(1, int(e.width * h / e.height)), max(1, int(h))), Image.LANCZOS)
        if len(fill) == 4 and fill[3] < 255:
            e = _mit_alpha(e, fill[3] / 255)
        if bild is not None:
            px, py = int(x + (font.size * EMOJI_BREITE - e.width) / 2), int(y - font.size * 0.78)
            if bild.mode == "RGBA":
                bild.alpha_composite(e, (max(0, px), max(0, py)))
            else:
                bild.paste(e, (px, py), e)
        x += font.size * EMOJI_BREITE


def umbrechen(font: ImageFont.FreeTypeFont, text: str, breite: float) -> list[str]:
    zeilen, z = [], ""
    for w in str(text or "").split():
        t = f"{z} {w}" if z else w
        if laenge(font, t) > breite and z:
            zeilen.append(z)
            z = w
        else:
            z = t
    if z:
        zeilen.append(z)
    return zeilen


def ausgleichen(font: ImageFont.FreeTypeFont, text: str, breite: float) -> list[str]:
    """Zeilen gleich lang machen (kein einzelnes Wort allein in der letzten Zeile): die schmalste Breite
    suchen, bei der die Zeilenzahl gleich bleibt -- wie text-wrap: balance im Browser."""
    zeilen = umbrechen(font, text, breite)
    if len(zeilen) < 2:
        return zeilen
    lo, hi = breite * 0.5, breite
    for _ in range(12):
        mitte = (lo + hi) / 2
        if len(umbrechen(font, text, mitte)) <= len(zeilen):
            hi = mitte
        else:
            lo = mitte
    return umbrechen(font, text, hi + 1)


def messe_text(text, *, breite, groesse, name, zeilenhoehe=1.12, max_zeilen=4, min_groesse=30, m=1.0, ausgleich=True):
    """Wie messeText im Dashboard: Schrift wird kleiner, bis der Text in max_zeilen passt.
    Mit ausgleich werden die Zeilen gleich lang umbrochen (ruhigeres Schriftbild, keine Waisen)."""
    g = groesse
    while True:
        font = schrift(name, g * m)
        zeilen = umbrechen(font, text, breite * m)
        if len(zeilen) <= max_zeilen or g - 4 < min_groesse:
            break
        g -= 4
    if ausgleich and 1 < len(zeilen) <= max_zeilen:
        zeilen = ausgleichen(font, text, breite * m)
    if len(zeilen) > max_zeilen:
        zeilen = zeilen[:max_zeilen]
        z = zeilen[-1]
        while z and laenge(font, z + " …") > breite * m:
            z = z.rsplit(" ", 1)[0] if " " in z else ""
        zeilen[-1] = z + " …"
    return {"zeilen": zeilen, "g": g, "name": name, "zh": zeilenhoehe,
            "hoehe": (len(zeilen) - 1) * g * zeilenhoehe + g}


def zeichne_text(draw, block, x, oben, farbe, m=1.0, alpha=255):
    font = schrift(block["name"], block["g"] * m)
    for i, z in enumerate(block["zeilen"]):
        y = oben + block["g"] * 0.8 + i * block["g"] * block["zh"]
        text_mit_emojis(draw, (x * m, y * m), z, font, _rgb(farbe) + (alpha,), anchor="ms")


def gesperrt(draw, text, cx, grundlinie, font, abstand, farbe):
    """Text mit Buchstabenabstand, mittig."""
    breiten = [font.getlength(ch) for ch in text]
    x = cx - (sum(breiten) + abstand * (len(text) - 1)) / 2
    for ch, b in zip(text, breiten):
        draw.text((x, grundlinie), ch, font=font, fill=farbe, anchor="ls")
        x += b + abstand


# ---------------------------------------------------------------------------
# Das Post-Bild
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Formate: Farbwelt, Beschriftung, Aufbau (je Wochenformat ein eigener Look)
# ---------------------------------------------------------------------------
PALETTEN = {   # Verlauf oben -> Mitte -> unten, Akzent fuer Ringe/Karten
    "nacht":  {"verlauf": ("#2a1650", "#120a26", "#07040f"), "akzent": (233, 207, 156)},
    "liebe":  {"verlauf": ("#47163f", "#1f0a22", "#0a0410"), "akzent": (236, 180, 160)},
    "wissen": {"verlauf": ("#172a5c", "#0b1433", "#04060f"), "akzent": (233, 207, 156)},
    "ritual": {"verlauf": ("#123f45", "#091f26", "#03090c"), "akzent": (233, 207, 156)},
    "zeichen": {"verlauf": ("#26206a", "#100c33", "#05040f"), "akzent": (233, 207, 156)},
    "mitmachen": {"verlauf": ("#3d1866", "#170a2c", "#07040f"), "akzent": (233, 207, 156)},
    # fuer die Symbole (symbole.MOTIV_PALETTE): Rose/Pflaume, warmes Bernstein, Amethyst
    "rose": {"verlauf": ("#5a1d46", "#260c26", "#0b0410"), "akzent": (240, 196, 176)},
    "amber": {"verlauf": ("#4b2c14", "#1d1009", "#070403"), "akzent": (240, 208, 150)},
    "amethyst": {"verlauf": ("#3b1b70", "#170b35", "#06040f"), "akzent": (226, 206, 240)},
}
THEMEN = {   # Wochenformat (redaktion.py) -> (Layout-Schluessel, Farbwelt)
    "Deine Woche": ("woche", "nacht"), "Sternzeichen im Fokus": ("zeichen", "zeichen"),
    "Liebe & Beziehung": ("liebe", "liebe"), "Astro-Wissen": ("wissen", "wissen"), "Ritual": ("ritual", "ritual"),
    "Mitmachen": ("mitmachen", "mitmachen"), "Rückblick & Vorschau": ("rueckblick", "nacht"),
}
BESCHRIFTUNG = {
    "woche": {"de": "Deine Woche", "en": "Your week", "hu": "A heted", "it": "La tua settimana"},
    "zeichen": {"de": "Sternzeichen im Fokus", "en": "Signs in focus", "hu": "Csillagjegyek fókuszban", "it": "Segni in primo piano"},
    "liebe": {"de": "Liebe & Beziehung", "en": "Love & connection", "hu": "Szerelem és kapcsolat", "it": "Amore e relazioni"},
    "wissen": {"de": "Astro-Wissen", "en": "Astro knowledge", "hu": "Asztrológia röviden", "it": "Astro-sapere"},
    "ritual": {"de": "Ritual", "en": "Ritual", "hu": "Rituálé", "it": "Rituale"},
    "mitmachen": {"de": "Mitmachen", "en": "Your turn", "hu": "Te jössz", "it": "Tocca a te"},
    "rueckblick": {"de": "Rückblick & Vorschau", "en": "Look back & ahead", "hu": "Visszatekintő", "it": "Bilancio e anteprima"},
    "ereignis": {"de": "Besonderer Himmel", "en": "Special sky", "hu": "Különleges égbolt", "it": "Cielo speciale"},
}
FOLGE = {"de": "Folge {n}", "en": "No. {n}", "hu": "{n}. rész", "it": "N. {n}"}
WISCHEN = {"de": "Wischen", "en": "Swipe", "hu": "Lapozz", "it": "Scorri"}
# Schlussfolie des Karussells: Einladung in die App (je Handlungsaufforderung)
EINLADUNG = {
    "mondzeichen": {"de": "Dein Sonnen- & Mondzeichen in Sekunden", "en": "Your Sun & Moon sign in seconds",
                    "hu": "A Nap- és Hold-jegyed másodpercek alatt", "it": "Il tuo segno di Sole e Luna in pochi secondi"},
    "partner": {"de": "Wie gut passt ihr zusammen?", "en": "How well do you match?",
                "hu": "Mennyire illetek össze?", "it": "Quanto siete compatibili?"},
    "horoskop": {"de": "Dein Horoskop aus deinem Geburtshoroskop", "en": "Your horoscope from your own birth chart",
                 "hu": "Horoszkóp a saját születési képletedből", "it": "Il tuo oroscopo dal tuo tema natale"},
    "chat": {"de": "Stell Soraya deine Frage", "en": "Ask Soraya your question",
             "hu": "Tedd fel a kérdésed Sorayának", "it": "Fai la tua domanda a Soraya"},
}
GRATIS = {"de": "Kostenlos · ohne Konto testen", "en": "Free · try it without an account",
          "hu": "Ingyenes · regisztráció nélkül kipróbálható", "it": "Gratis · provalo senza account"}
ZEICHEN_GLYPHE = "♈♉♊♋♌♍♎♏♐♑♒♓"
ZEICHEN_NAMEN = [  # gleiche Reihenfolge wie die Glyphen
    ("widder", "aries", "kos", "ariete"), ("stier", "taurus", "bika", "toro"),
    ("zwillinge", "gemini", "ikrek", "gemelli"), ("krebs", "cancer", "rák", "cancro"),
    ("löwe", "leo", "oroszlán", "leone"), ("jungfrau", "virgo", "szűz", "vergine"),
    ("waage", "libra", "mérleg", "bilancia"), ("skorpion", "scorpio", "skorpió", "scorpione"),
    ("schütze", "sagittarius", "nyilas", "sagittario"), ("steinbock", "capricorn", "bak", "capricorno"),
    ("wassermann", "aquarius", "vízöntő", "acquario"), ("fische", "pisces", "halak", "pesci"),
]


def zeichen_aus_text(text: str) -> int | None:
    """Index (0-11) des Sternzeichens, mit dem ein Text beginnt ("Scorpio: ..." / "Skorpió – ..."), sonst None."""
    kopf = str(text or "").strip().lower()
    for i, namen in enumerate(ZEICHEN_NAMEN):
        for n in sorted(namen, key=len, reverse=True):
            if kopf.startswith(n) and (len(kopf) == len(n) or not kopf[len(n)].isalpha()):
                return i
    return None


def stil(post: dict) -> dict:
    """Layout, Farbwelt und Beschriftung eines Posts."""
    meta = post.get("meta") or {}
    thema = meta.get("thema") or ""
    layout, palette = THEMEN.get(thema, ("ereignis", "nacht") if thema.startswith("Großes Ereignis") else ("mond", "nacht"))
    punkte = [str(x).strip() for x in (meta.get("bild_punkte") or []) if str(x).strip()][:3]
    ereignis_zeichen = zeichen_aus_text(thema.split(": ", 1)[-1]) if layout == "ereignis" else None
    if post.get("art") == "story":
        aufbau = "glyphe" if ereignis_zeichen is not None else "mond"
    elif post.get("art") == "post" and punkte and layout == "mitmachen":
        aufbau = "umfrage"                       # Antwortmoeglichkeiten A/B/C wie eine Umfrage
    elif post.get("art") == "post" and punkte:
        hat_zeichen = sum(zeichen_aus_text(x) is not None for x in punkte) >= 2
        aufbau = "zeichen" if hat_zeichen else "schritte"
    elif post.get("art") == "post" and layout == "liebe":
        aufbau = "liebe"
    elif post.get("art") == "post" and layout == "woche":
        aufbau = "woche"                         # Mondphasen der ganzen Woche als Leiste
    elif post.get("art") == "post" and layout == "rueckblick":
        aufbau = "zitat"
    elif ereignis_zeichen is not None:
        aufbau = "glyphe"                        # Saisonbeginn: grosses Sternzeichen statt Mond
    else:
        aufbau = "mond"
    # Symbol (Herz, Kerze, Kristall ...) statt des grossen Mondes -- mit eigener Farbwelt
    from symbole import MOTIVE, MOTIV_PALETTE
    symbol = meta.get("motiv") if meta.get("motiv") in MOTIVE else None
    if symbol and aufbau in ("mond", "liebe"):
        aufbau, palette = "symbol", MOTIV_PALETTE.get(symbol, palette)
    else:
        symbol = None
    sprache = (post.get("sprache") or "de")[:2]
    label = (BESCHRIFTUNG.get(layout) or {}).get(sprache) if layout in BESCHRIFTUNG else None
    if label and meta.get("folge") and layout != "ereignis":     # Serie: "Ritual · Folge 12"
        label = f"{label} · {FOLGE.get(sprache, FOLGE['en']).format(n=int(meta['folge']))}"
    return {"layout": layout, "aufbau": aufbau, "palette": palette, "label": label, "punkte": punkte,
            "zeichen": ereignis_zeichen, "symbol": symbol}


# Mondphasen ohne Internet (fuer die Wochenleiste): Alter seit einem bekannten Neumond
_NEUMOND = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODISCH = 29.530588853
WOCHENTAG_KURZ = {"de": "MDMDFSS", "en": "MTWTFSS", "hu": "HKSCPSV", "it": "LMMGVSD"}


def mond_am(tag) -> tuple[int, float]:
    """(phase_index 0..7, Beleuchtung in %) mittags (UTC) an einem Tag."""
    alter = ((datetime(tag.year, tag.month, tag.day, 12, tzinfo=timezone.utc) - _NEUMOND).total_seconds()
             / 86400) % SYNODISCH
    return int(alter / SYNODISCH * 8 + 0.5) % 8, round((1 - math.cos(2 * math.pi * alter / SYNODISCH)) / 2 * 100, 1)


def _post_tag(post: dict):
    t = post.get("geplant_fuer")
    if isinstance(t, str):
        try:
            return date.fromisoformat(t[:10])
        except ValueError:
            t = None
    return t if isinstance(t, date) else date.today()


def _wochenleiste(leinwand, d, post, y, W, m, akzent):
    """Sieben kleine Monde (Montag bis Sonntag) mit Wochentag, der heutige Tag golden umrandet."""
    tag = _post_tag(post)
    start = tag - timedelta(days=tag.weekday())
    kurz = WOCHENTAG_KURZ.get((post.get("sprache") or "de")[:2], WOCHENTAG_KURZ["en"])
    r, abstand = 30, 118
    x0 = W / 2 - 3 * abstand
    font = schrift("inter600", 28 * m)
    for i in range(7):
        t = start + timedelta(days=i)
        cx, cy = x0 + i * abstand, y + r + 6
        idx, licht = mond_am(t)
        if t == tag:
            d.ellipse([(cx - r - 12) * m, (cy - r - 12) * m, (cx + r + 12) * m, (cy + r + 12) * m],
                      outline=akzent + (230,), width=max(1, int(2 * m)))
        mb = mond(r * m, idx, licht)
        aufkleben(leinwand, mb, (cx * m - mb.width / 2, cy * m - mb.height / 2))
        d.text((cx * m, (cy + r + 40) * m), kurz[i], font=font, fill=akzent + (255 if t == tag else 150,), anchor="ms")
    return 2 * r + 6 + 52


@lru_cache(maxsize=16)
def _verlauf_hintergrund(W: int, H: int, palette: str = "nacht") -> Image.Image:
    """Der weiche Verlauf reicht in Viertel-Aufloesung (spart Rechenzeit)."""
    q = 4
    a, b, c = PALETTEN.get(palette, PALETTEN["nacht"])["verlauf"]
    grund = radial(W // q, H // q, W / 2 / q, 0, 40 / q, W / 2 / q, H * 0.25 / q, H / q,
                   [(0, a, 1), (0.45, b, 1), (1, c, 1)]).convert("RGB")
    return _nebel(grund).resize((W, H), Image.BICUBIC)


def _nebel(grund: Image.Image) -> Image.Image:
    """Zarter Sternennebel als schraeges Band (Milchstrasse): bringt Tiefe, bleibt hinter dem Text ruhig."""
    w, h = grund.size
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # Band von links unten nach rechts oben, leicht gewellt
    nx, ny = 0.55, 1.0
    abstand = ((xs - w * 0.5) * nx + (ys - h * 0.55) * ny) / math.hypot(nx, ny)
    abstand += np.sin(xs / w * 5.0) * h * 0.03
    band = np.exp(-(abstand / (h * 0.16)) ** 2)
    rng = np.random.default_rng(5)
    wolken = sum((np.asarray(Image.fromarray((rng.random((g, g)) * 255).astype(np.uint8), "L")
                             .resize((w, h), Image.BICUBIC), np.float32) / 255) * f
                 for g, f in ((5, 0.55), (11, 0.3), (23, 0.15)))
    dichte = np.clip(band * (wolken - 0.25) * 1.6, 0, 1)[..., None]
    violett = np.array([122, 92, 190], np.float32)
    rose = np.array([196, 120, 170], np.float32)
    farbe = violett + (rose - violett) * np.clip(wolken[..., None] - 0.35, 0, 1)
    a = np.asarray(grund, np.float32)
    return Image.fromarray(np.clip(a + (farbe - a) * dichte * 0.24, 0, 255).astype(np.uint8), "RGB")


def rahmen(d: ImageDraw.ImageDraw, W: int, H: int, m: float, akzent) -> None:
    """Feiner goldener Doppelrahmen (Art-déco, wie das Logo)."""
    for abstand, alpha, breite in ((30, 110, 1.6), (40, 45, 1.0)):
        d.rounded_rectangle([abstand * m, abstand * m, (W - abstand) * m, (H - abstand) * m], radius=(30 - abstand / 4) * m,
                            outline=akzent + (alpha,), width=max(1, int(breite * m)))


def hintergrund(W: int, H: int, seed, story: bool, m: float = 1.0, palette: str = "nacht") -> Image.Image:
    bg = _verlauf_hintergrund(W, H, palette).resize((int(W * m), int(H * m)), Image.BICUBIC)
    sterne(bg, W, H, seed, story, m)
    return bg


def stern_liste(W, H, seed, story):
    rnd = zufall(seed)
    liste = []
    for _ in range(190 if story else 140):
        gold = rnd() < 0.12
        a = (0.5 + rnd() * 0.45) if gold else (0.2 + rnd() * 0.45)
        x, y = rnd() * W, rnd() * H
        r = 0.6 + rnd() * (2.4 if gold else 1.6)
        liste.append((x, y, r, (233, 207, 156) if gold else (188, 178, 214), a))
    return liste


def sterne(bild: Image.Image, W, H, seed, story, m=1.0, helligkeit=None):
    """helligkeit(i) -> Faktor 0..1 (fuer das Funkeln im Video)"""
    d = ImageDraw.Draw(bild, "RGBA")
    for i, (x, y, r, farbe, a) in enumerate(stern_liste(W, H, seed, story)):
        f = helligkeit(i) if helligkeit else 1.0
        d.ellipse([(x - r) * m, (y - r) * m, (x + r) * m, (y + r) * m], fill=farbe + (int(a * f * 255),))


def _cta(draw, bild, W, unten, story, sprache, m, art="link", text: str | None = None):
    """Knopf unten: "link" (Rand, Text + Stern), "voll" (goldene Flaeche: die eine Hauptaufforderung,
    z. B. auf der Schlussfolie) oder "wischen" (Titelbild des Karussells: Text + Pfeil)."""
    voll = art == "voll"
    text = text or (WISCHEN.get(sprache or "de", WISCHEN["en"]).upper() if art == "wischen"
                    else LINK_IN_BIO.get(sprache or "de", LINK_IN_BIO["de"]))
    font = schrift("inter600", (34 if story else 30) * m)
    stern_h = (13 if story else 12) * m
    lueck = 16 * m
    if art == "wischen":
        breiten = [font.getlength(ch) for ch in text]
        tb = sum(breiten) + 3 * m * (len(text) - 1)
        zeichen_b = 40 * m
    else:
        tb = font.getlength(text)
        zeichen_b = 2 * stern_h * 0.74
    bw = tb + lueck + zeichen_b + 76 * m
    bh, by = (78 if story else 68) * m, (unten + (100 if story else 72)) * m
    x0 = W * m / 2 - bw / 2
    tinte = (26, 18, 8, 255) if voll else (243, 231, 201, 255)
    if voll:
        verlauf = linear(int(bw), int(bh), 0, 0, 0, bh, [(0, "#efd9a4", 1), (1, "#cfae62", 1)])
        maske = Image.new("L", verlauf.size, 0)
        ImageDraw.Draw(maske).rounded_rectangle([0, 0, verlauf.width - 1, verlauf.height - 1], radius=bh / 2, fill=255)
        bild.paste(verlauf, (int(x0), int(by)), maske)
    else:
        draw.rounded_rectangle([x0, by, x0 + bw, by + bh], radius=bh / 2, fill=(230, 207, 156, 18),
                               outline=(230, 207, 156, 200), width=max(1, int(2 * m)))
    tx = W * m / 2 - (tb + lueck + zeichen_b) / 2
    mitte = by + bh / 2 + m
    if art == "wischen":
        gesperrt(draw, text, tx + tb / 2, mitte + font.size * 0.36, font, 3 * m, tinte)
        x1 = tx + tb + lueck + zeichen_b
        draw.line([(x1 - zeichen_b, mitte), (x1, mitte)], fill=tinte, width=max(1, int(2.4 * m)))
        draw.polygon([(x1 + 2 * m, mitte), (x1 - 10 * m, mitte - 8 * m), (x1 - 10 * m, mitte + 8 * m)], fill=tinte)
        return
    draw.text((tx, mitte), text, font=font, fill=tinte, anchor="lm")
    sx = tx + tb + lueck + stern_h * 0.74
    draw.polygon(stern_punkte(sx, mitte, stern_h), fill=tinte)


def marke(bild: Image.Image, W: int, H: int, story: bool, sprache: str, m: float = 1.0, knopf: str = "link") -> None:
    """Fuss des Bildes: Wortmarke SORAYA und darunter der Knopf (siehe _cta). Im Feed ohne die winzige
    Zeile "Luxury Astro Guide" (am Handy unlesbar) -- in der Story ist Platz und sie bleibt."""
    d = ImageDraw.Draw(bild, "RGBA")
    unten = H - 300 if story else H - 192
    gesperrt(d, "SORAYA", W * m / 2, (unten + (0 if story else 26)) * m, schrift("cinzel", (50 if story else 40) * m),
             14 * m, (230, 207, 156, 255))
    if story:
        gesperrt(d, "LUXURY ASTRO GUIDE", W * m / 2, (unten + 50) * m, schrift("inter500", 25 * m), 8 * m,
                 (160, 148, 190, 255))
    if knopf:
        _cta(d, bild, W, unten, story, sprache, m, knopf)


def kopf(d, W, m, story, akzent, label=None, datum=None, y=None):
    """Kopfzeilen unter dem Logo: Format (gold, Versalien) und darunter Datum · Mondphase (ruhig, normal
    geschrieben). Ersetzt die fruehere Kapsel + Versal-Datumszeile: weniger Rahmen, klarere Reihenfolge.
    Rueckgabe: y unter dem Kopf (Beginn des Inhalts)."""
    y = y if y is not None else (282 if story else 196)
    if label:
        gesperrt(d, label.upper(), W * m / 2, y * m, schrift("inter600", (28 if story else 25) * m), 4 * m, akzent + (255,))
        y += 46 if story else 40
    if datum:
        d.text((W * m / 2, y * m), datum, font=schrift("inter400", (31 if story else 28) * m), fill=(196, 186, 220, 255),
               anchor="ms")
        y += 46 if story else 40
    return y + (28 if story else 18)


_ANLEITUNG = re.compile(r"^(antworte|antwort|reply|answer|respond|válaszolj|valaszolj|rispondi|scrivi|schreib)\b", re.IGNORECASE)


def ohne_antwort_anleitung(text: str) -> str:
    """Story mit Antwort-Knoepfen: Saetze wie "Antworte mit 🌙 oder ☀️" weglassen -- die Knoepfe im Bild
    zeigen die Antworten schon (weniger Text im Bild)."""
    saetze = re.split(r"(?<=[.!?…])\s+", str(text or "").strip())
    rest = [s for s in saetze if not _ANLEITUNG.match(s.strip())]
    return " ".join(rest).strip() or str(text or "").strip()


def datumszeile(meta: dict) -> str | None:
    """'20. Okt · Zunehmende Sichel' (Mondphase gross geschrieben, wie geliefert)."""
    teile = [str(x).strip() for x in (meta.get("datum_kurz"), meta.get("mond_phase")) if x and str(x).strip()]
    return "  ·  ".join(teile) or None


def _etikett(d, text, cx, y, m, farbe):
    """Kleine Beschriftung in einer Kapsel (z. B. "ASTRO KNOWLEDGE")."""
    font = schrift("inter600", 21 * m)
    text = text.upper()
    breiten = [font.getlength(ch) for ch in text]
    tb = sum(breiten) + 3 * m * (len(text) - 1)
    bw, bh = tb + 44 * m, 44 * m
    d.rounded_rectangle([cx * m - bw / 2, y * m, cx * m + bw / 2, y * m + bh], radius=bh / 2,
                        fill=farbe + (28,), outline=farbe + (150,), width=max(1, int(1.5 * m)))
    gesperrt(d, text, cx * m, y * m + bh / 2 + 8 * m, font, 3 * m, farbe + (255,))
    return 44 + 26


def _medaillon(d, cx, cy, r, m, akzent, glyphe=None, zahl=None):
    d.ellipse([(cx - r) * m, (cy - r) * m, (cx + r) * m, (cy + r) * m], fill=akzent + (22,),
              outline=akzent + (210,), width=max(1, int(2.2 * m)))
    if glyphe:
        d.text((cx * m, cy * m + r * 0.04 * m), glyphe, font=schrift("zeichen", r * 1.15 * m), fill=akzent + (255,), anchor="mm")
    elif zahl is not None:
        d.text((cx * m, cy * m + r * 0.06 * m), str(zahl), font=schrift("cinzel", r * 1.0 * m), fill=akzent + (255,), anchor="mm")


def _karten(d, punkte, y, W, story, m, akzent, zeichen: bool, buchstaben: bool = False):
    """Drei Karten untereinander: Medaillon (Sternzeichen-Symbol, Nummer oder A/B/C) + Text."""
    r = 56 if story else 48
    pad = 28 if story else 24
    x0, x1 = 90, W - 90
    for i, p in enumerate(punkte):
        idx = zeichen_aus_text(p) if zeichen else None
        name, rest = "", p
        if idx is not None:
            teile = re.split(r"\s*[:–—-]\s*", p, maxsplit=1)
            name, rest = teile[0], (teile[1] if len(teile) > 1 else "")
            rest = rest[:1].upper() + rest[1:]
        text_x = x0 + pad + 2 * r + 28
        breite = x1 - pad - text_x
        tb = messe_text(rest or p, breite=breite, groesse=44 if story else 38, name="inter500",
                        zeilenhoehe=1.25, max_zeilen=2, min_groesse=28)
        nh = (32 if story else 27) if name else 0
        inhalt = nh + (10 if name else 0) + tb["hoehe"]
        hoehe = max(2 * r, inhalt) + 2 * pad
        d.rounded_rectangle([x0 * m, y * m, x1 * m, (y + hoehe) * m], radius=26 * m,
                            fill=(255, 255, 255, 12), outline=akzent + (70,), width=max(1, int(1.5 * m)))
        _medaillon(d, x0 + pad + r, y + hoehe / 2, r, m, akzent,
                   glyphe=ZEICHEN_GLYPHE[idx] if idx is not None else None,
                   zahl=None if idx is not None else ("ABC"[i] if buchstaben else i + 1))
        ty = y + (hoehe - inhalt) / 2
        if name:
            font = schrift("cinzel", nh * m)
            d.text((text_x * m, (ty + nh * 0.82) * m), name.upper(), font=font, fill=akzent + (255,), anchor="ls")
            ty += nh + 12
        font = schrift(tb["name"], tb["g"] * m)
        for j, z in enumerate(tb["zeilen"]):
            d.text((text_x * m, (ty + tb["g"] * 0.8 + j * tb["g"] * tb["zh"]) * m), z, font=font,
                   fill=(239, 232, 248, 255), anchor="ls")
        y += hoehe + (22 if story else 16)
    return y


def _karten_hoehe(punkte, W, story, zeichen: bool):
    r, pad, h = (56 if story else 48), (28 if story else 24), 0
    for p in punkte:
        idx = zeichen_aus_text(p) if zeichen else None
        rest = re.split(r"\s*[:–—-]\s*", p, maxsplit=1)[-1] if idx is not None else p
        breite = (W - 90) - pad - (90 + pad + 2 * r + 28)
        tb = messe_text(rest, breite=breite, groesse=44 if story else 38, name="inter500", zeilenhoehe=1.25,
                        max_zeilen=2, min_groesse=28)
        inhalt = ((32 if story else 27) + 10 if idx is not None else 0) + tb["hoehe"]
        h += max(2 * r, inhalt) + 2 * pad + (22 if story else 16)
    return h


def _liebe_ringe(d, cx, cy, r, m, akzent):
    """Zwei verschlungene Ringe hinter dem Mond (Partner-Motiv)."""
    for dx in (-0.5 * r, 0.5 * r):
        rr = r * 1.32
        d.ellipse([(cx + dx - rr) * m, (cy - rr) * m, (cx + dx + rr) * m, (cy + rr) * m],
                  outline=akzent + (120,), width=max(1, int(2.4 * m)))


def _symbol_held(leinwand, d, name, cx, cy, r, m, akzent):
    """Symbol in der Mitte: weicher Lichthof, zwei feine Ringe (wie ein Siegel), darin das goldene Motiv."""
    from symbole import motiv
    schein = radial(int(4 * r * m), int(4 * r * m), 2 * r * m, 2 * r * m, r * 0.3 * m, 2 * r * m, 2 * r * m,
                    2 * r * m, [(0, "#ffe2b0", 0.22), (0.55, "#ffe2b0", 0.06), (1, "#ffe2b0", 0)])
    aufkleben(leinwand, schein, (cx * m - schein.width / 2, cy * m - schein.height / 2))
    d.ellipse([(cx - r) * m, (cy - r) * m, (cx + r) * m, (cy + r) * m], fill=akzent + (14,),
              outline=akzent + (150,), width=max(1, int(2 * m)))
    ri = r * 0.9
    d.ellipse([(cx - ri) * m, (cy - ri) * m, (cx + ri) * m, (cy + ri) * m], outline=akzent + (60,), width=max(1, int(1.2 * m)))
    for w in range(0, 360, 45):          # kleine Punkte auf dem Ring
        a = math.radians(w)
        px, py = cx + r * math.cos(a), cy + r * math.sin(a)
        d.ellipse([(px - 3.2) * m, (py - 3.2) * m, (px + 3.2) * m, (py + 3.2) * m], fill=akzent + (220,))
    gr = int(r * 1.35 * m)
    b = motiv(name, gr)
    aufkleben(leinwand, b, (cx * m - gr / 2, cy * m - gr / 2))


def bild(post: dict, format: str = "feed", video: bool = False) -> Image.Image:
    """Das fertige Post-Bild als RGB (1080x1350 oder 1080x1920), Look je nach Wochenformat."""
    story = format == "story"
    W, H = 1080, (1920 if story else 1350)
    m = SS
    st = stil(post)
    akzent = PALETTEN[st["palette"]]["akzent"]
    leinwand = hintergrund(W, H, post.get("id") or 1, story, m, st["palette"])
    d = ImageDraw.Draw(leinwand, "RGBA")
    rahmen(d, W, H, m, akzent)
    meta = post.get("meta") or {}
    mit_mond = meta.get("phase_index") is not None

    # Wasserzeichen: Symbol des Mondzeichens, gross und kaum sichtbar
    idx_mond = st["zeichen"] if st.get("zeichen") is not None else zeichen_aus_text(meta.get("mond_zeichen") or "")
    wasser = ZEICHEN_GLYPHE[idx_mond] if idx_mond is not None and st["layout"] in ("wissen", "zeichen", "ereignis") \
        else ("?" if st["layout"] == "mitmachen" else None)
    if wasser:
        ebene = Image.new("RGBA", leinwand.size, (0, 0, 0, 0))
        font = schrift("zeichen" if wasser != "?" else "cormorant", (760 if story else 640) * m)
        ImageDraw.Draw(ebene).text((W * m / 2, H * m * 0.56), wasser, font=font, fill=akzent + (255,), anchor="mm")
        # hinter Karten noch leiser: das Zeichen soll Tiefe geben, nicht mit dem Text konkurrieren
        aufkleben(leinwand, _mit_alpha(ebene, 0.03 if st["aufbau"] in ("zeichen", "schritte", "umfrage") else 0.045))

    zeichen_h = 124 if story else 100
    z = portal(int(zeichen_h * m))
    s = zeichen_h * m / 312
    aufkleben(leinwand, z, (W * m / 2 - 256 * s, (118 if story else 62) * m - 112 * s))
    # Kopf so knapp wie moeglich: nur das Format (gold); das Datum nur, wenn es kein Format gibt
    datum = datumszeile(meta) if mit_mond and not st["label"] else None
    unten = H - 300 if story else H - 192
    oben = kopf(d, W, m, story, akzent, st["label"], datum)
    platz = (unten - (150 if story else 72)) - oben

    titel = messe_text(post.get("titel") or post.get("text") or "", breite=W - 180, groesse=108 if story else 92,
                       name="cormorant", max_zeilen=4 if story else 3, min_groesse=56)
    # Unterzeile nur noch bei Posts ohne Format (Studio); im Tagesplan reicht die Ueberschrift
    unter = messe_text(post["untertitel"], breite=W - 220, groesse=42 if story else 36, name="inter400",
                       zeilenhoehe=1.35, max_zeilen=2, min_groesse=28) \
        if post.get("untertitel") and not st["label"] and post.get("art") != "story" else None
    frage_text = post.get("text") if post.get("art") == "story" and post.get("text") and post.get("text") != post.get("titel") else ""
    antworten = st["punkte"][:2] if story and post.get("art") == "story" and len(st["punkte"]) >= 2 else []
    if antworten and frage_text:
        frage_text = ohne_antwort_anleitung(frage_text)
    pad = 44 if story else 34
    frage = messe_text(frage_text, breite=W - 220 - 2 * pad, groesse=46 if story else 36, name="inter500",
                       zeilenhoehe=1.38, max_zeilen=6 if story else 4, min_groesse=28) if frage_text else None
    ab_mond, ab_unter, ab_frage = (110, 36, 70) if story else (70, 26, 44)

    karten = st["aufbau"] in ("zeichen", "schritte", "umfrage")
    if karten:   # Karten-Aufbau: kleiner Mond oben rechts, Titel, Karten
        unter = None if not story else unter
        kh = _karten_hoehe(st["punkte"], W, story, st["aufbau"] == "zeichen")
        rest = titel["hoehe"] + (ab_unter + unter["hoehe"] if unter else 0) + ab_frage * 0.8 + kh
        y = oben + max(0, (platz - rest) / 2)
        zeichne_text(d, titel, W / 2, y, "#F6E3B4", m)
        y += titel["hoehe"]
        if unter:
            y += ab_unter
            zeichne_text(d, unter, W / 2, y, "#C3B7DA", m)
            y += unter["hoehe"]
        _karten(d, st["punkte"], y + ab_frage * 0.8, W, story, m, akzent, st["aufbau"] == "zeichen",
                buchstaben=st["aufbau"] == "umfrage")
        if mit_mond:
            mr = 46 if story else 38
            mb = mond(mr * m, meta.get("phase_index"), meta.get("beleuchtung"))
            aufkleben(leinwand, mb, ((W - 110) * m - mb.width / 2, (story and 180 or 120) * m - mb.height / 2))
    else:
        rest = titel["hoehe"] + (ab_unter + unter["hoehe"] if unter else 0) + (ab_frage + frage["hoehe"] + 2 * pad if frage else 0) \
            + (40 + 96 if antworten else 0)
        held = st["aufbau"] if st["aufbau"] in ("woche", "zitat", "glyphe", "symbol") else None
        held_h = {"woche": 118, "zitat": 130, "glyphe": 2 * (150 if story else 120),
                  "symbol": 2 * (175 if story else 150)}.get(held, 0)
        if held == "symbol":      # Platz sparen, wenn Titel und Frage viel brauchen
            held_h = max(2 * 92, min(held_h, platz - rest - ab_mond * 0.8))
        symbol_mond = mit_mond and held == "symbol"
        mit_mond = mit_mond and not held
        r = (150 if story else 105) if mit_mond else 0
        if mit_mond:
            r = max(60, min(r, (platz - rest - ab_mond) / 2))
        gesamt = rest + (2 * r + ab_mond if mit_mond else 0) + (held_h + ab_mond * 0.8 if held else 0)
        y = oben + max(0, (platz - gesamt) / 2)
        if held == "woche":
            y += _wochenleiste(leinwand, d, post, y, W, m, akzent) + ab_mond * 0.8
        elif held == "zitat":
            d.text((W * m / 2, (y + 150) * m), "\u201C", font=schrift("cormorant", 260 * m), fill=akzent + (230,), anchor="ms")
            y += held_h + ab_mond * 0.8
        elif held == "glyphe":
            gr = held_h / 2
            schein = radial(int(4 * gr * m), int(4 * gr * m), 2 * gr * m, 2 * gr * m, gr * 0.5 * m, 2 * gr * m, 2 * gr * m,
                            2 * gr * m, [(0, "#ffe9b0", 0.14), (1, "#ffe9b0", 0)])
            aufkleben(leinwand, schein, (W * m / 2 - schein.width / 2, (y + gr) * m - schein.height / 2))
            _medaillon(d, W / 2, y + gr, gr, m, akzent, glyphe=ZEICHEN_GLYPHE[st["zeichen"]])
            y += held_h + ab_mond * 0.8
        elif held == "symbol":
            _symbol_held(leinwand, d, st["symbol"], W / 2, y + held_h / 2, held_h / 2, m, akzent)
            y += held_h + ab_mond * 0.8
        if symbol_mond:           # der Mond des Tages bleibt dabei: klein oben rechts
            mr = 46 if story else 38
            mb = mond(mr * m, meta.get("phase_index"), meta.get("beleuchtung"))
            aufkleben(leinwand, mb, ((W - 110) * m - mb.width / 2, (story and 180 or 120) * m - mb.height / 2))
        if mit_mond:
            if st["aufbau"] == "liebe":
                _liebe_ringe(d, W / 2, y + r, r, m, akzent)
            # Lichthof vom beleuchteten Teil, dazu eine feine Goldlinie (nicht bei den Liebes-Ringen)
            schein = mond_schein(r * m, meta.get("phase_index"), meta.get("beleuchtung"), linie=st["aufbau"] != "liebe")
            aufkleben(leinwand, schein, (W * m / 2 - schein.width / 2, (y + r) * m - schein.height / 2))
            mb = mond(r * m, meta.get("phase_index"), meta.get("beleuchtung"))
            aufkleben(leinwand, mb, (W * m / 2 - mb.width / 2, (y + r) * m - mb.height / 2))
            y += 2 * r + ab_mond
        zeichne_text(d, titel, W / 2, y, "#F6E3B4", m)
        y += titel["hoehe"]
        if unter:
            y += ab_unter
            zeichne_text(d, unter, W / 2, y, "#C3B7DA", m)
            y += unter["hoehe"]
        if frage:
            y += ab_frage
            d.rounded_rectangle([110 * m, y * m, (W - 110) * m, (y + frage["hoehe"] + 2 * pad) * m], radius=28 * m,
                                fill=(255, 255, 255, 13), outline=akzent + (89,), width=int(2 * m))
            zeichne_text(d, frage, W / 2, y + pad, "#EFE8F8", m)
            y += frage["hoehe"] + 2 * pad
        if antworten:      # zwei Antwort-Knoepfe wie ein Umfrage-Sticker (Antwort per Nachricht)
            y += 40
            font = schrift("inter600", 38 * m)
            breite, luecke = (W - 220 - 30) / 2, 30
            for i, a in enumerate(antworten):
                x0 = 110 + i * (breite + luecke)
                d.rounded_rectangle([x0 * m, y * m, (x0 + breite) * m, (y + 96) * m], radius=48 * m,
                                    fill=akzent + (40 if i == 0 else 18,), outline=akzent + (200,), width=max(1, int(2 * m)))
                text = a if laenge(font, a) <= (breite - 40) * m else ohne_emojis(a)
                text_mit_emojis(d, ((x0 + breite / 2) * m, (y + 96 / 2 + 13) * m), text, font, (246, 227, 180, 255))
    if not story and not karten and st["layout"] in ("wissen", "ritual") and post.get("art") == "post":
        _merken_zeichen(d, W, m, akzent, post.get("sprache") or "de")
    # Karussell: das Titelbild laedt zum Wischen ein (die Einladung in die App kommt auf der Schlussfolie)
    knopf = "wischen" if not story and folien_von(post) and not video else "link"   # im Video: kein "Wischen"
    marke(leinwand, W, H, story, post.get("sprache") or "de", m, knopf)
    return leinwand.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Karussell: Titelbild (bild) + eine Folie je Gedanke + Schlussfolie mit Einladung
# ---------------------------------------------------------------------------
def folien_von(post: dict) -> list[dict]:
    if (post.get("art") or "post") != "post":
        return []
    return [f for f in ((post.get("meta") or {}).get("folien") or []) if f.get("titel") or f.get("text")][:4]


def anzahl_bilder(post: dict) -> int:
    """1 ohne Karussell, sonst Titelbild + Folien + Schlussfolie."""
    f = folien_von(post)
    return len(f) + 2 if f else 1


MERKEN = {"de": "Zum Speichern", "en": "Save this", "hu": "Mentsd el", "it": "Da salvare"}


def _merken_zeichen(d, W, m, akzent, sprache):
    """Lesezeichen oben rechts: Wissen und Rituale sind zum Speichern gedacht (das belohnen die Plattformen)."""
    # nur das Zeichen (wie bei Instagram) -- die fruehere 17-px-Beschriftung war am Handy unlesbar
    x, y, b, h = W - 118, 84, 32, 42
    d.polygon([(x * m, y * m), ((x + b) * m, y * m), ((x + b) * m, (y + h) * m), ((x + b / 2) * m, (y + h - 11) * m),
               (x * m, (y + h) * m)], outline=akzent + (230,), width=max(1, int(2.4 * m)))


def _wisch_hinweis(d, W, H, m, akzent, sprache):
    """Kleiner Hinweis unten rechts: es geht weiter (Karussell)."""
    font = schrift("inter600", 25 * m)
    text = WISCHEN.get(sprache, WISCHEN["en"]).upper()
    x1, y = (W - 70) * m, (H - 112) * m
    breite = sum(font.getlength(ch) for ch in text) + 2.5 * m * (len(text) - 1)
    gesperrt(d, text, x1 - 46 * m - breite / 2, y + 8 * m, font, 2.5 * m, akzent + (210,))
    d.line([(x1 - 34 * m, y), (x1, y)], fill=akzent + (230,), width=max(1, int(2 * m)))
    d.polygon([(x1 + 2 * m, y), (x1 - 9 * m, y - 7 * m), (x1 - 9 * m, y + 7 * m)], fill=akzent + (230,))


def _seitenzahl(d, W, m, akzent, nr, gesamt):
    """Punkte oben (wie bei Instagram), aktuelle Seite gold."""
    abstand, r = 26, 6
    x0 = W / 2 - (gesamt - 1) * abstand / 2
    for i in range(gesamt):
        cx, cy = (x0 + i * abstand) * m, 60 * m
        farbe = akzent + (255,) if i == nr - 1 else akzent + (70,)
        d.ellipse([cx - r * m, cy - r * m, cx + r * m, cy + r * m], fill=farbe)


def folie(post: dict, nr: int, video: bool = False) -> Image.Image:
    """Bild nr (2 .. anzahl_bilder) des Karussells, 1080x1350. nr 1 ist das normale Titelbild."""
    folien = folien_von(post)
    gesamt = anzahl_bilder(post)
    if nr <= 1 or not folien or nr > gesamt:
        return bild(post, "feed")
    W, H, m = 1080, 1350, SS
    st = stil(post)
    akzent = PALETTEN[st["palette"]]["akzent"]
    sprache = (post.get("sprache") or "de")[:2]
    leinwand = hintergrund(W, H, (post.get("id") or 1) * 7 + nr, False, m, st["palette"])
    d = ImageDraw.Draw(leinwand, "RGBA")
    rahmen(d, W, H, m, akzent)
    if not video:
        _seitenzahl(d, W, m, akzent, nr, gesamt)
    oben, unten = 110, H - 200                         # freier Bereich zwischen Seitenpunkten und Marke
    if nr == gesamt:                                   # Schlussfolie: Einladung in die App
        schluessel = (post.get("meta") or {}).get("aufforderung") or "mondzeichen"
        einladung = (EINLADUNG.get(schluessel) or EINLADUNG["mondzeichen"]).get(sprache, EINLADUNG["mondzeichen"]["en"])
        t = messe_text(einladung, breite=W - 200, groesse=84, name="cormorant", max_zeilen=3, min_groesse=52)
        u = messe_text(GRATIS.get(sprache, GRATIS["en"]), breite=W - 240, groesse=36, name="inter400",
                       zeilenhoehe=1.35, max_zeilen=2, min_groesse=26)
        zh = 260
        y = oben + max(0, (unten - oben - (zh + 70 + t["hoehe"] + 30 + u["hoehe"])) / 2)
        z = portal(int(zh * m))
        s = zh * m / 312
        aufkleben(leinwand, z, (W * m / 2 - 256 * s, y * m - 112 * s))
        y += zh + 70
        zeichne_text(d, t, W / 2, y, "#F6E3B4", m)
        zeichne_text(d, u, W / 2, y + t["hoehe"] + 30, "#C3B7DA", m)
        marke(leinwand, W, H, False, sprache, m, "voll")
        return leinwand.resize((W, H), Image.LANCZOS)
    f = folien[nr - 2]
    titel, text = (f.get("titel") or "").strip(), (f.get("text") or "").strip()
    idx = zeichen_aus_text(titel)
    if idx is not None:          # grosses, kaum sichtbares Zeichen im Hintergrund (wie auf dem Titelbild)
        ebene = Image.new("RGBA", leinwand.size, (0, 0, 0, 0))
        ImageDraw.Draw(ebene).text((W * m / 2, H * m * 0.55), ZEICHEN_GLYPHE[idx], font=schrift("zeichen", 640 * m),
                                   fill=akzent + (255,), anchor="mm")
        aufkleben(leinwand, _mit_alpha(ebene, 0.06))
        d = ImageDraw.Draw(leinwand, "RGBA")
    r = 92
    tt = messe_text(titel, breite=W - 200, groesse=88, name="cormorant", max_zeilen=2, min_groesse=56)
    tx = messe_text(text, breite=W - 240, groesse=52, name="inter400", zeilenhoehe=1.4, max_zeilen=5, min_groesse=34)
    hoehe = 2 * r + 70 + tt["hoehe"] + 46 + 44 + tx["hoehe"]
    cy = oben + max(0, (unten - oben - hoehe) / 2) + r
    _medaillon(d, W / 2, cy, r, m, akzent, glyphe=ZEICHEN_GLYPHE[idx] if idx is not None else None,
               zahl=None if idx is not None else nr - 1)
    zeichne_text(d, tt, W / 2, cy + r + 70, "#F6E3B4", m)
    y = cy + r + 70 + tt["hoehe"] + 46
    d.line([((W / 2 - 40) * m, y * m), ((W / 2 + 40) * m, y * m)], fill=akzent + (160,), width=max(1, int(2 * m)))
    zeichne_text(d, tx, W / 2, y + 44, "#EFE8F8", m)
    gesperrt(d, "SORAYA", W * m / 2, (H - 120) * m, schrift("cinzel", 34 * m), 12 * m, akzent + (200,))
    if not video:
        _wisch_hinweis(d, W, H, m, akzent, sprache)
    return leinwand.resize((W, H), Image.LANCZOS)


def als_bytes(img: Image.Image, typ: str = "jpeg") -> bytes:
    puffer = io.BytesIO()
    if typ == "png":
        img.save(puffer, "PNG", optimize=True)
    else:
        img.save(puffer, "JPEG", quality=94, subsampling=0, optimize=True, progressive=True)
    return puffer.getvalue()


def standard_format(post: dict) -> str:
    return "feed" if (post.get("art") or "post") == "post" else "story"
