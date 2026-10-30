"""
Symbole fuer die Post-Bilder (Feed, Story): goldene Linien-Zeichnungen im Stil des Soraya-Logos.

Claude waehlt je Post ein Symbol aus MOTIVE (Schema im Tagesplan); medien.bild() setzt es statt des grossen
Mondes in die Mitte, mit eigener Farbwelt (MOTIV_PALETTE). Gezeichnet wird auf einem Raster von 512
(wie medien.portal), in Gold mit leichtem Schein.
"""

from __future__ import annotations

import math
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


def _herz(d, P, s, w):
    pkt = []
    for i in range(121):
        t = 2 * math.pi * i / 120
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pkt.append((x, y))
    for f, b in ((10.5, w), (7.2, w * 0.35)):
        d.line([P(256 + x * f, 262 - y * f) for x, y in pkt], fill=255, width=int(b), joint="curve")
    d.polygon([P(x, y) for x, y in medien.stern_punkte(392, 128, 22)], fill=255)
    d.polygon([P(x, y) for x, y in medien.stern_punkte(128, 380, 12)], fill=255)


def _kerze(d, P, s, w):
    d.rounded_rectangle([P(206, 262), P(306, 430)], radius=10 * s, outline=255, width=int(w))
    d.line([P(206, 300), P(232, 300), P(232, 330)], fill=255, width=int(w * 0.5), joint="curve")   # Wachstropfen
    d.line([P(256, 262), P(256, 236)], fill=255, width=int(w * 0.45))
    flamme = [(256 + 34 * math.sin(math.pi * t) * (1 - t) ** 0.4 * (1 if i < 40 else -1), 230 - 120 * t)
              for i, t in enumerate([j / 39 for j in range(40)] + [1 - j / 39 for j in range(40)])]
    d.polygon([P(x, y) for x, y in flamme], fill=255)
    d.line([P(160, 444), P(352, 444)], fill=255, width=int(w * 0.8))


def _kristall(d, P, s, w):
    aussen = [(256, 72), (360, 190), (316, 440), (196, 440), (152, 190)]
    d.line([P(*p) for p in aussen + [aussen[0]]], fill=255, width=int(w), joint="curve")
    for a, b in (((152, 190), (360, 190)), ((256, 72), (210, 190)), ((256, 72), (302, 190)),
                 ((210, 190), (256, 440)), ((302, 190), (256, 440))):
        d.line([P(*a), P(*b)], fill=255, width=int(w * 0.4))
    d.polygon([P(x, y) for x, y in medien.stern_punkte(400, 110, 18)], fill=255)


def _blatt(winkel, laenge, breite, cx=256, cy=400):
    pkt = []
    r = math.radians(winkel)
    ax, ay = math.sin(r), -math.cos(r)
    for i in range(41):
        t = i / 40
        q = breite * math.sin(math.pi * t) ** 0.8
        pkt.append((cx + ax * laenge * t - ay * q, cy + ay * laenge * t + ax * q))
    for i in range(40, -1, -1):
        t = i / 40
        q = breite * math.sin(math.pi * t) ** 0.8
        pkt.append((cx + ax * laenge * t + ay * q, cy + ay * laenge * t - ax * q))
    return pkt


def _lotus(d, P, s, w):
    for winkel, laenge, breite, b in ((-62, 190, 46, 0.55), (62, 190, 46, 0.55), (-32, 230, 52, 0.75),
                                      (32, 230, 52, 0.75), (0, 260, 58, 1.0)):
        d.line([P(x, y) for x, y in _blatt(winkel, laenge, breite)], fill=255, width=int(w * b), joint="curve")
    for i, y in enumerate((426, 450)):
        d.line([P(150 + i * 30, y), P(362 - i * 30, y)], fill=255, width=int(w * (0.7 - i * 0.25)))


def _sonne(d, P, s, w):
    d.ellipse([P(186, 186), P(326, 326)], outline=255, width=int(w))
    d.ellipse([P(216, 216), P(296, 296)], outline=255, width=int(w * 0.35))
    for i in range(16):
        a = 2 * math.pi * i / 16
        r0, r1 = 92, (178 if i % 2 == 0 else 136)
        d.line([P(256 + r0 * math.cos(a), 256 + r0 * math.sin(a)), P(256 + r1 * math.cos(a), 256 + r1 * math.sin(a))],
               fill=255, width=int(w * (0.6 if i % 2 == 0 else 0.4)))


def _sternbild(d, P, s, w):
    punkte = [(120, 330), (182, 238), (250, 270), (318, 180), (392, 214), (360, 330), (268, 392)]
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 2)):
        d.line([P(*punkte[a]), P(*punkte[b])], fill=255, width=int(w * 0.4))
    for i, (x, y) in enumerate(punkte):
        d.polygon([P(px, py) for px, py in medien.stern_punkte(x, y, 26 if i in (1, 3, 5) else 17)], fill=255)


def _schluessel(d, P, s, w):
    d.ellipse([P(186, 70), P(326, 210)], outline=255, width=int(w))
    d.polygon([P(x, y) for x, y in medien.stern_punkte(256, 140, 30)], fill=255)
    d.line([P(256, 210), P(256, 440)], fill=255, width=int(w))
    for y, l in ((370, 56), (414, 40)):
        d.line([P(256, y), P(256 + l, y)], fill=255, width=int(w * 0.9))
    d.line([P(226, 236), P(286, 236)], fill=255, width=int(w * 0.45))


def _sanduhr(d, P, s, w):
    for y in (82, 430):
        d.line([P(150, y), P(362, y)], fill=255, width=int(w))
    links = [(176, 96), (176, 140), (246, 256), (176, 372), (176, 416)]
    d.line([P(*p) for p in links], fill=255, width=int(w * 0.7), joint="curve")
    d.line([P(512 - x, y) for x, y in links], fill=255, width=int(w * 0.7), joint="curve")
    d.polygon([P(256, 330), P(318, 404), P(194, 404)], fill=255)          # Sand unten
    d.polygon([P(212, 150), P(300, 150), P(256, 206)], fill=255)          # Sand oben
    d.line([P(256, 256), P(256, 330)], fill=255, width=int(w * 0.25))


def _auge(d, P, s, w):
    oben = [(150 + 212 * i / 40, 256 - 96 * math.sin(math.pi * i / 40)) for i in range(41)]
    unten = [(150 + 212 * i / 40, 256 + 96 * math.sin(math.pi * i / 40)) for i in range(41)]
    d.line([P(*p) for p in oben], fill=255, width=int(w), joint="curve")
    d.line([P(*p) for p in unten], fill=255, width=int(w), joint="curve")
    d.ellipse([P(206, 206), P(306, 306)], outline=255, width=int(w * 0.7))
    d.ellipse([P(236, 236), P(276, 276)], fill=255)
    for i in range(7):
        a = math.radians(-150 + i * 20)
        d.line([P(256 + 140 * math.cos(a), 236 + 140 * math.sin(a)), P(256 + 182 * math.cos(a), 236 + 182 * math.sin(a))],
               fill=255, width=int(w * 0.4))


def _venus(d, P, s, w):
    d.ellipse([P(166, 76), P(346, 256)], outline=255, width=int(w))
    d.ellipse([P(196, 106), P(316, 226)], outline=255, width=int(w * 0.3))
    d.line([P(256, 256), P(256, 440)], fill=255, width=int(w))
    d.line([P(190, 352), P(322, 352)], fill=255, width=int(w))
    d.polygon([P(x, y) for x, y in medien.stern_punkte(380, 92, 18)], fill=255)


def _karten(d, P, s, w):
    for winkel, b in ((-16, 0.6), (16, 0.6), (0, 1.0)):
        r = math.radians(winkel)
        ecken = []
        for x, y in ((-70, -112), (70, -112), (70, 112), (-70, 112)):
            ecken.append((256 + 30 * math.sin(r) * 3 + x * math.cos(r) - y * math.sin(r),
                          290 + x * math.sin(r) + y * math.cos(r)))
        d.polygon([P(*e) for e in ecken], fill=0)
        d.line([P(*e) for e in ecken + [ecken[0]]], fill=255, width=int(w * b), joint="curve")
    d.ellipse([P(222, 230), P(290, 298)], fill=255)
    d.ellipse([P(240, 220), P(304, 284)], fill=0)
    d.polygon([P(x, y) for x, y in medien.stern_punkte(256, 340, 26)], fill=255)


_ZEICHNER = {"herz": _herz, "kerze": _kerze, "kristall": _kristall, "lotus": _lotus, "sonne": _sonne,
             "sternbild": _sternbild, "schluessel": _schluessel, "sanduhr": _sanduhr, "auge": _auge,
             "venus": _venus, "karten": _karten}


@lru_cache(maxsize=32)
def motiv(name: str, groesse: int) -> Image.Image:
    """Das Motiv als RGBA (groesse x groesse): Gold-Verlauf mit weichem Schein."""
    k = 2
    gr = groesse * k
    s = gr / 512
    P = lambda x, y: (x * s, y * s)                     # noqa: E731
    maske = Image.new("L", (gr, gr), 0)
    _ZEICHNER.get(name, _sonne)(ImageDraw.Draw(maske), P, s, 11 * s)
    gold = medien.linear(gr, gr, 120 * s, 60 * s, 400 * s, 460 * s,
                         [(0, "#fff5d1", 1), (0.45, "#ebcb86", 1), (1, "#b08a42", 1)])
    schein = maske.filter(ImageFilter.GaussianBlur(14 * s))
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    bild.alpha_composite(medien._durch_maske(Image.new("RGBA", (gr, gr), (255, 225, 160, 255)), schein, 0.55))
    bild.alpha_composite(medien._durch_maske(gold, maske))
    return bild.resize((groesse, groesse), Image.LANCZOS)
