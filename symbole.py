"""
Symbole fuer die Post-Bilder (Feed, Story): goldene Linien-Zeichnungen im Stil des Soraya-Logos.

Claude waehlt je Post ein Symbol aus MOTIVE (Schema im Tagesplan); medien.bild() setzt es statt des grossen
Mondes in die Mitte, mit eigener Farbwelt (MOTIV_PALETTE). Gezeichnet wird auf einem Raster von 512
(wie medien.portal), in Gold mit leichtem Schein.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

import medien

MOTIVE = ("herz", "kerze", "kristall", "lotus", "sonne", "sternbild", "schluessel", "sanduhr", "auge", "venus", "karten")
# Farbwelt je Motiv (Schluessel aus medien.PALETTEN)
MOTIV_PALETTE = {"herz": "rose", "venus": "rose", "kerze": "amber", "sonne": "amber", "sanduhr": "amber",
                 "kristall": "amethyst", "karten": "amethyst", "lotus": "ritual", "auge": "wissen",
                 "sternbild": "wissen", "schluessel": "zeichen"}
# wofuer ein Motiv passt (fuer Claude und fuer die Auswahl ohne Claude)
BEDEUTUNG = {
    "herz": "Liebe, Gefühle, Nähe", "venus": "Venus, Anziehung, Weiblichkeit, Selbstwert",
    "kerze": "Ritual, Ruhe, Abend, Loslassen", "sonne": "Energie, Neuanfang, Sonne im Zeichen",
    "sanduhr": "Timing, Geduld, Rückläufigkeit", "kristall": "Energie, Klarheit, Schutz",
    "karten": "Mitmachen, Wahl, Orakel", "lotus": "Selbstfürsorge, innere Ruhe, Heilung",
    "auge": "Intuition, Wissen, Wahrheit", "sternbild": "Sternzeichen, Astro-Wissen",
    "schluessel": "Geheimnis, Antwort, Neues entdecken",
}
# ohne passende Wahl von Claude: nach Wochenformat (mehrere -> je Tag ein anderes)
NACH_THEMA = {"Liebe & Beziehung": ("herz", "venus"), "Ritual": ("kerze", "lotus", "kristall"),
              "Astro-Wissen": ("auge", "sternbild", "sanduhr"), "Mitmachen": ("karten", "schluessel"),
              "Deine Woche": ("sonne", "sanduhr", "kristall"), "Sternzeichen im Fokus": ("sternbild", "schluessel"),
              "Rückblick & Vorschau": ("sanduhr", "lotus")}


def waehle(vorschlag: str | None, thema: str, tag_nr: int, art: str, nr: int = 0) -> str | None:
    """Claudes Wahl, wenn gueltig; sonst ein Motiv passend zum Format (je Tag und Post ein anderes)."""
    if vorschlag in MOTIVE:
        return vorschlag
    reihe = NACH_THEMA.get(thema) or MOTIVE
    return reihe[(tag_nr + nr) % len(reihe)]


def _stern(d, P, x, y, h):
    d.polygon([P(px, py) for px, py in medien.stern_punkte(x, y, h)], fill=255)


def _herz_punkte(f, cx=256, cy=262):
    pkt = []
    for i in range(161):
        t = 2 * math.pi * i / 160
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pkt.append((cx + x * f, cy - y * f))
    return pkt


# Jede Zeichnung bekommt zwei Masken: L = goldene Linien, F = zarte Farbflaeche (Tiefe, Licht)
def _herz(L, F, P, s, w):
    F.polygon([P(*p) for p in _herz_punkte(10.5)], fill=150)
    F.polygon([P(*p) for p in _herz_punkte(6.4, 250, 250)], fill=255)          # Licht innen, leicht versetzt
    L.line([P(*p) for p in _herz_punkte(10.5)], fill=255, width=int(w), joint="curve")
    L.line([P(*p) for p in _herz_punkte(7.6)], fill=255, width=int(w * 0.3), joint="curve")
    for x, y in _herz_punkte(9.0)[::8]:                                          # Perlenkette
        L.ellipse([P(x - 3.2, y - 3.2), P(x + 3.2, y + 3.2)], fill=255)
    L.line([P(206, 150), P(176, 196)], fill=255, width=int(w * 0.35))            # Glanzlicht
    _stern(L, P, 400, 112, 26); _stern(L, P, 112, 392, 14); _stern(L, P, 420, 330, 10)


def _kerze(L, F, P, s, w):
    F.rounded_rectangle([P(206, 262), P(306, 430)], radius=10 * s, fill=110)
    F.ellipse([P(196, 120), P(316, 250)], fill=255)                               # Lichtkegel der Flamme
    L.rounded_rectangle([P(206, 262), P(306, 430)], radius=10 * s, outline=255, width=int(w))
    tropfen = [(206 + i * 2.5, 292 + 10 * math.sin(i / 40 * 3 * math.pi) ** 2 + (24 if 14 <= i <= 20 else 0)) for i in range(41)]
    L.line([P(*p) for p in tropfen], fill=255, width=int(w * 0.45), joint="curve")
    L.line([P(256, 262), P(256, 238)], fill=255, width=int(w * 0.45))
    aussen = [(256 + 36 * math.sin(math.pi * t) * (1 - t) ** 0.45, 234 - 124 * t) for t in [j / 40 for j in range(41)]]
    L.polygon([P(*p) for p in aussen + [(512 - x, y) for x, y in reversed(aussen)]], fill=255)
    kern = [(256 + 14 * math.sin(math.pi * t) * (1 - t) ** 0.45, 228 - 58 * t) for t in [j / 30 for j in range(31)]]
    L.polygon([P(*p) for p in kern + [(512 - x, y) for x, y in reversed(kern)]], fill=0)   # dunkler Kern
    for a in range(-60, 61, 30):                                                  # Lichtstrahlen
        r = math.radians(a - 90)
        L.line([P(256 + 84 * math.cos(r), 176 + 84 * math.sin(r)), P(256 + 112 * math.cos(r), 176 + 112 * math.sin(r))],
               fill=255, width=int(w * 0.3))
    L.line([P(150, 444), P(362, 444)], fill=255, width=int(w * 0.8))
    L.line([P(184, 462), P(328, 462)], fill=255, width=int(w * 0.35))


def _kristall(L, F, P, s, w):
    aussen = [(256, 64), (366, 188), (318, 448), (194, 448), (146, 188)]
    flaechen = [([(256, 64), (366, 188), (302, 188)], 230), ([(256, 64), (210, 188), (146, 188)], 120),
                ([(210, 188), (302, 188), (256, 448)], 200), ([(302, 188), (366, 188), (318, 448), (256, 448)], 90),
                ([(146, 188), (210, 188), (256, 448), (194, 448)], 150)]
    for poly, a in flaechen:                                                      # Facetten unterschiedlich hell
        F.polygon([P(*p) for p in poly], fill=a)
    L.line([P(*p) for p in aussen + [aussen[0]]], fill=255, width=int(w), joint="curve")
    for a, b in (((146, 188), (366, 188)), ((256, 64), (210, 188)), ((256, 64), (302, 188)),
                 ((210, 188), (256, 448)), ((302, 188), (256, 448))):
        L.line([P(*a), P(*b)], fill=255, width=int(w * 0.4))
    _stern(L, P, 404, 104, 24); _stern(L, P, 118, 300, 12); _stern(L, P, 300, 128, 9)


def _blatt(winkel, laenge, breite, cx=256, cy=400):
    pkt = []
    r = math.radians(winkel)
    ax, ay = math.sin(r), -math.cos(r)
    for vz in (1, -1):
        reihe = range(41) if vz == 1 else range(40, -1, -1)
        for i in reihe:
            t = i / 40
            q = breite * math.sin(math.pi * t) ** 0.8 * vz
            pkt.append((cx + ax * laenge * t - ay * q, cy + ay * laenge * t + ax * q))
    return pkt


def _lotus(L, F, P, s, w):
    blaetter = ((-74, 150, 40, 0.45, 90), (74, 150, 40, 0.45, 90), (-48, 200, 48, 0.6, 130),
                (48, 200, 48, 0.6, 130), (-22, 236, 54, 0.8, 180), (22, 236, 54, 0.8, 180), (0, 266, 60, 1.0, 255))
    for winkel, laenge, breite, b, a in blaetter:
        F.polygon([P(*p) for p in _blatt(winkel, laenge, breite)], fill=a)
    for winkel, laenge, breite, b, a in blaetter:
        L.line([P(*p) for p in _blatt(winkel, laenge, breite)], fill=255, width=int(w * b), joint="curve")
        r = math.radians(winkel)                                                  # Blattader
        L.line([P(256, 400), P(256 + math.sin(r) * laenge * 0.72, 400 - math.cos(r) * laenge * 0.72)],
               fill=255, width=int(w * 0.2))
    L.ellipse([P(250, 106), P(262, 118)], fill=255)                               # Tautropfen
    for i, y in enumerate((424, 446, 466)):
        L.line([P(140 + i * 34, y), P(372 - i * 34, y)], fill=255, width=int(w * (0.7 - i * 0.2)))


def _sonne(L, F, P, s, w):
    F.ellipse([P(176, 176), P(336, 336)], fill=255)
    L.ellipse([P(186, 186), P(326, 326)], outline=255, width=int(w))
    L.ellipse([P(212, 212), P(300, 300)], outline=255, width=int(w * 0.3))
    for i in range(12):                                                           # Ornament im Inneren
        a = 2 * math.pi * i / 12
        L.line([P(256 + 18 * math.cos(a), 256 + 18 * math.sin(a)), P(256 + 40 * math.cos(a), 256 + 40 * math.sin(a))],
               fill=255, width=int(w * 0.25))
    for i in range(24):
        a = 2 * math.pi * i / 24
        lang = (190, 150, 120)[i % 3]
        if i % 3 == 0:                                                             # lange Strahlen als Flamme
            q = 2 * math.pi / 120
            L.polygon([P(256 + 92 * math.cos(a - q), 256 + 92 * math.sin(a - q)), P(256 + lang * math.cos(a), 256 + lang * math.sin(a)),
                       P(256 + 92 * math.cos(a + q), 256 + 92 * math.sin(a + q))], fill=255)
        else:
            L.line([P(256 + 96 * math.cos(a), 256 + 96 * math.sin(a)), P(256 + lang * math.cos(a), 256 + lang * math.sin(a))],
                   fill=255, width=int(w * 0.3))


def _sternbild(L, F, P, s, w):
    punkte = [(96, 344), (170, 236), (250, 272), (322, 160), (414, 204), (376, 346), (266, 404)]
    F.polygon([P(*punkte[i]) for i in (2, 3, 4, 5, 6)], fill=70)
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 2)):
        L.line([P(*punkte[a]), P(*punkte[b])], fill=255, width=int(w * 0.35))
    for i, (x, y) in enumerate(punkte):
        h = 34 if i in (1, 3, 5) else 22
        L.ellipse([P(x - h * 0.75, y - h * 0.75), P(x + h * 0.75, y + h * 0.75)], outline=255, width=int(w * 0.18))
        F.ellipse([P(x - h, y - h), P(x + h, y + h)], fill=255)
        _stern(L, P, x, y, h)
    for x, y in ((140, 140), (420, 420), (330, 470), (70, 220)):
        _stern(L, P, x, y, 8)


def _schluessel(L, F, P, s, w):
    F.ellipse([P(176, 60), P(336, 220)], fill=200)
    L.ellipse([P(176, 60), P(336, 220)], outline=255, width=int(w))
    L.ellipse([P(200, 84), P(312, 196)], outline=255, width=int(w * 0.3))
    for i in range(8):                                                            # Ornament-Bogen
        a = 2 * math.pi * i / 8
        L.ellipse([P(256 + 80 * math.cos(a) - 6, 140 + 80 * math.sin(a) - 6), P(256 + 80 * math.cos(a) + 6, 140 + 80 * math.sin(a) + 6)], fill=255)
    _stern(L, P, 256, 140, 34)
    L.line([P(256, 220), P(256, 446)], fill=255, width=int(w))
    for y in (250, 268):
        L.line([P(232, y), P(280, y)], fill=255, width=int(w * 0.4))
    L.rectangle([P(256, 370), P(318, 388)], fill=255)
    L.rectangle([P(256, 414), P(300, 432)], fill=255)
    L.rectangle([P(290, 388), P(306, 400)], fill=255)


def _sanduhr(L, F, P, s, w):
    links = [(176, 96), (176, 140), (246, 256), (176, 372), (176, 416)]
    rechts = [(512 - x, y) for x, y in links]
    F.polygon([P(*p) for p in links + list(reversed(rechts))], fill=60)
    F.polygon([P(256, 316), P(326, 404), P(186, 404)], fill=255)
    for y in (82, 430):
        L.rounded_rectangle([P(140, y - 9), P(372, y + 9)], radius=6 * s, outline=255, width=int(w * 0.6))
    for x in (150, 362):                                                          # Saeulen
        L.line([P(x, 92), P(x, 420)], fill=255, width=int(w * 0.35))
    L.line([P(*p) for p in links], fill=255, width=int(w * 0.75), joint="curve")
    L.line([P(*p) for p in rechts], fill=255, width=int(w * 0.75), joint="curve")
    L.polygon([P(256, 330), P(318, 404), P(194, 404)], fill=255)
    L.polygon([P(212, 150), P(300, 150), P(256, 206)], fill=255)
    for y in range(262, 326, 14):                                                 # rieselnder Sand
        L.ellipse([P(253, y), P(259, y + 6)], fill=255)


def _auge(L, F, P, s, w):
    oben = [(140 + 232 * i / 40, 256 - 104 * math.sin(math.pi * i / 40)) for i in range(41)]
    unten = [(140 + 232 * i / 40, 256 + 104 * math.sin(math.pi * i / 40)) for i in range(41)]
    F.polygon([P(*p) for p in oben + list(reversed(unten))], fill=90)
    F.ellipse([P(200, 200), P(312, 312)], fill=255)
    L.line([P(*p) for p in oben], fill=255, width=int(w), joint="curve")
    L.line([P(*p) for p in unten], fill=255, width=int(w), joint="curve")
    L.ellipse([P(200, 200), P(312, 312)], outline=255, width=int(w * 0.7))
    for i in range(16):                                                           # Iris-Struktur
        a = 2 * math.pi * i / 16
        L.line([P(256 + 26 * math.cos(a), 256 + 26 * math.sin(a)), P(256 + 50 * math.cos(a), 256 + 50 * math.sin(a))],
               fill=255, width=int(w * 0.18))
    L.ellipse([P(236, 236), P(276, 276)], fill=255)
    L.ellipse([P(262, 240), P(272, 250)], fill=0)                                 # Lichtpunkt
    for i in range(9):
        a = math.radians(-160 + i * 17.5)
        L.line([P(256 + 132 * math.cos(a), 250 + 132 * math.sin(a)), P(256 + (172 if i % 2 == 0 else 156) * math.cos(a), 250 + (172 if i % 2 == 0 else 156) * math.sin(a))],
               fill=255, width=int(w * 0.35))
    _stern(L, P, 256, 400, 20)


def _venus(L, F, P, s, w):
    F.ellipse([P(166, 66), P(346, 246)], fill=180)
    L.ellipse([P(166, 66), P(346, 246)], outline=255, width=int(w))
    L.ellipse([P(190, 90), P(322, 222)], outline=255, width=int(w * 0.3))
    L.ellipse([P(222, 120), P(298, 196)], fill=255)                               # Mondsichel im Kreis
    L.ellipse([P(240, 112), P(310, 182)], fill=0)
    L.line([P(256, 246), P(256, 446)], fill=255, width=int(w))
    L.line([P(186, 350), P(326, 350)], fill=255, width=int(w))
    for x in (186, 326):
        L.ellipse([P(x - 9, 341), P(x + 9, 359)], fill=255)
    _stern(L, P, 392, 84, 24); _stern(L, P, 120, 300, 12)


def _karten(L, F, P, s, w):
    for winkel, b, a in ((-18, 0.6, 80), (18, 0.6, 80), (0, 1.0, 170)):
        r = math.radians(winkel)
        ecken = [(256 + 40 * math.sin(r) * 2 + x * math.cos(r) - y * math.sin(r), 292 + x * math.sin(r) + y * math.cos(r))
                 for x, y in ((-72, -116), (72, -116), (72, 116), (-72, 116))]
        F.polygon([P(*e) for e in ecken], fill=a)
        L.polygon([P(*e) for e in ecken], fill=0)
        L.line([P(*e) for e in ecken + [ecken[0]]], fill=255, width=int(w * b), joint="curve")
        innen = [(256 + 40 * math.sin(r) * 2 + x * math.cos(r) - y * math.sin(r), 292 + x * math.sin(r) + y * math.cos(r))
                 for x, y in ((-58, -102), (58, -102), (58, 102), (-58, 102))]
        L.line([P(*e) for e in innen + [innen[0]]], fill=255, width=int(w * 0.18), joint="curve")
    L.ellipse([P(222, 214), P(290, 282)], fill=255)
    L.ellipse([P(240, 204), P(304, 268)], fill=0)
    _stern(L, P, 256, 336, 30)
    for x, y in ((226, 380), (286, 380)):
        _stern(L, P, x, y, 8)


_ZEICHNER = {"herz": _herz, "kerze": _kerze, "kristall": _kristall, "lotus": _lotus, "sonne": _sonne,
             "sternbild": _sternbild, "schluessel": _schluessel, "sanduhr": _sanduhr, "auge": _auge,
             "venus": _venus, "karten": _karten}


@lru_cache(maxsize=32)
def motiv(name: str, groesse: int) -> Image.Image:
    """Das Motiv als RGBA (groesse x groesse): zarte Farbflaeche mit Licht, Schein, Gold-Linien, Funkeln."""
    k = 2
    gr = groesse * k
    s = gr / 512
    P = lambda x, y: (x * s, y * s)                     # noqa: E731
    linien, flaeche = Image.new("L", (gr, gr), 0), Image.new("L", (gr, gr), 0)
    _ZEICHNER.get(name, _sonne)(ImageDraw.Draw(linien), ImageDraw.Draw(flaeche), P, s, 11 * s)
    # Funkeln drumherum: kleine Sterne und Goldstaub auf einer leichten Umlaufbahn (je Motiv immer gleich)
    zz = random.Random(name)
    staub = ImageDraw.Draw(linien)
    for _ in range(16):
        a, r = zz.uniform(0, 2 * math.pi), zz.uniform(200, 246)
        x, y = 256 + r * math.cos(a), 256 + r * math.sin(a)
        if zz.random() < 0.35:
            _stern(staub, P, x, y, zz.uniform(5, 10))
        else:
            q = zz.uniform(1.6, 3.2)
            staub.ellipse([P(x - q, y - q), P(x + q, y + q)], fill=int(zz.uniform(120, 255)))
    gold = medien.linear(gr, gr, 120 * s, 60 * s, 400 * s, 460 * s,
                         [(0, "#fff7dc", 1), (0.45, "#ecca82", 1), (1, "#b08640", 1)])
    farbe = medien.radial(gr, gr, 256 * s, 200 * s, 0, 256 * s, 256 * s, 300 * s,
                          [(0, "#fff3dc", 1), (0.45, "#ffc98f", 1), (1, "#f08f78", 1)])
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    bild.alpha_composite(medien._durch_maske(farbe, flaeche.filter(ImageFilter.GaussianBlur(3 * s)), 0.42))
    schein = linien.filter(ImageFilter.GaussianBlur(16 * s))
    bild.alpha_composite(medien._durch_maske(Image.new("RGBA", (gr, gr), (255, 222, 160, 255)), schein, 0.6))
    bild.alpha_composite(medien._durch_maske(gold, linien))
    return bild.resize((groesse, groesse), Image.LANCZOS)
