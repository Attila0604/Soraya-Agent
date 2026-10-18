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
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCHRIFTEN = Path(__file__).parent / "fonts"
# Knopf unten im Bild: passt fuer Instagram (Link in Bio) und Facebook (Link unter dem Text)
LINK_IN_BIO = {"de": "Dein Horoskop gratis", "en": "Your free horoscope", "hu": "Ingyenes horoszkóp", "it": "Oroscopo gratis"}
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


# Die grossen dunklen "Meere" der sichtbaren Mondseite (x, y, Breite, Hoehe relativ zum Radius, Tiefe)
MARIA = [(-0.36, -0.36, 0.30, 0.25, 1.0), (0.13, -0.31, 0.18, 0.17, 0.9), (0.27, -0.04, 0.22, 0.18, 0.9),
         (0.63, -0.22, 0.11, 0.10, 0.9), (0.47, 0.22, 0.13, 0.18, 0.7), (-0.15, 0.43, 0.18, 0.13, 0.6),
         (-0.62, 0.02, 0.24, 0.44, 0.8), (0.30, 0.37, 0.09, 0.09, 0.6), (-0.05, -0.64, 0.42, 0.07, 0.6),
         (-0.30, 0.18, 0.16, 0.12, 0.5)]


@lru_cache(maxsize=24)
def _mond_textur(gr: int, r: float) -> np.ndarray:
    """Helligkeit der Mondoberflaeche (etwa 0.6..1.05): Meere, feine Koernung, Krater, Randabdunklung.
    Immer gleich (fester Zufall), damit der Mond in jedem Bild derselbe ist."""
    c = gr / 2
    ys, xs = np.mgrid[0:gr, 0:gr].astype(np.float32)
    x, y = (xs + 0.5 - c) / r, (ys + 0.5 - c) / r
    rr = np.sqrt(x * x + y * y)
    meer = np.zeros_like(x)
    for mx, my, bx, by, tiefe in MARIA:
        d = ((x - mx) / bx) ** 2 + ((y - my) / by) ** 2
        meer = np.maximum(meer, tiefe * np.clip(1 - d, 0, 1) ** 0.45)
    rng = np.random.default_rng(11)
    grob = Image.fromarray((rng.random((12, 12)) * 255).astype(np.uint8), "L").resize((gr, gr), Image.BICUBIC)
    fein = Image.fromarray((rng.random((48, 48)) * 255).astype(np.uint8), "L").resize((gr, gr), Image.BICUBIC)
    rauschen = (np.asarray(grob, np.float32) / 255 - 0.5) * 0.7 + (np.asarray(fein, np.float32) / 255 - 0.5) * 0.3
    meer = np.clip(meer * (0.75 + rauschen * 1.4), 0, 1)
    weich = Image.fromarray((meer * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(r * 0.035))
    meer = np.asarray(weich, np.float32) / 255
    tex = 1 - 0.42 * meer + 0.07 * rauschen
    for _ in range(22):                                      # Krater: flache Mulde, zarter heller Rand
        kx, ky = rng.uniform(-0.85, 0.85, 2)
        if kx * kx + ky * ky > 0.8:
            continue
        kr = rng.uniform(0.015, 0.05)
        d = np.sqrt((x - kx) ** 2 + (y - ky) ** 2) / kr
        tex -= 0.035 * np.clip(1 - d, 0, 1)
        tex += 0.025 * np.clip(1 - np.abs(d - 1.05) * 5, 0, 1)
    d = np.sqrt((x + 0.12) ** 2 + (y - 0.72) ** 2) / 0.035  # Tycho: heller Fleck unten
    tex += 0.18 * np.clip(1 - d, 0, 1)
    tex *= 1 - 0.22 * np.clip(rr, 0, 1) ** 4               # Randabdunklung (wirkt wie eine Kugel)
    return np.clip(tex, 0.45, 1.1)


def _mit_textur(ebene: Image.Image, tex: np.ndarray) -> Image.Image:
    a = np.asarray(ebene, dtype=np.float32)
    a[..., :3] = np.clip(a[..., :3] * tex[..., None], 0, 255)
    return Image.fromarray((a + 0.5).astype(np.uint8), "RGBA")


def mond(r: float, phase_index, beleuchtung) -> Image.Image:
    """Mondscheibe (Licht rechts = zunehmend; Breite nach echter Beleuchtung in %). Mittelpunkt = Bildmitte.
    Mit Oberflaeche (Meere, Krater) und schwachem Erdschein auf der dunklen Seite."""
    rand = max(1.0, r / 40)
    gr = int(math.ceil(2 * r + 2 * rand + 4))
    c = gr / 2
    tex = _mond_textur(gr, round(r, 1))
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    scheibe = Image.new("L", (gr, gr), 0)
    ImageDraw.Draw(scheibe).ellipse([c - r, c - r, c + r, c + r], fill=255)
    dunkel = radial(gr, gr, c - r * 0.2, c - r * 0.3, r * 0.1, c, c, r, [(0, "#3a3354", 1), (1, "#1a1430", 1)])
    bild.alpha_composite(_durch_maske(_mit_textur(dunkel, tex), scheibe))
    ring = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([c - r, c - r, c + r, c + r], outline=(201, 168, 106, 115), width=max(1, int(round(rand))))
    bild.alpha_composite(ring)
    if phase_index is None or phase_index == 0:
        return bild
    phase_index = int(phase_index)
    zunehmend = phase_index < 4
    try:
        b = float(beleuchtung)
        k = min(0.97, max(0.03, b / 100))
        rx, ist_sichel = abs(1 - 2 * k) * r, k < 0.5
    except (TypeError, ValueError):
        e = (phase_index * 45 + 22.5) % 360
        rx = abs(math.cos(math.radians(e))) * r
        ist_sichel = e < 90 if zunehmend else e > 270

    def ellipse(von, bis):
        return [(c + rx * math.cos(math.radians(von + (bis - von) * i / 64)),
                 c + r * math.sin(math.radians(von + (bis - von) * i / 64))) for i in range(65)]
    if phase_index == 4:
        form = _bogen(c, c, r, 0, 360, 128)
    elif zunehmend:   # rechte Haelfte, zurueck ueber die Ellipse (Sichel: rechts herum, sonst links herum)
        form = _bogen(c, c, r, -90, 90, 96) + (ellipse(90, -90) if ist_sichel else ellipse(90, 270))
    else:             # linke Haelfte
        form = _bogen(c, c, r, 270, 90, 96) + (ellipse(90, 270) if ist_sichel else ellipse(90, -90))
    licht = Image.new("L", (gr, gr), 0)
    ImageDraw.Draw(licht).polygon(form, fill=255)
    # weiche Schattengrenze, aussen aber scharf an der Scheibe
    licht = licht.filter(ImageFilter.GaussianBlur(max(0.8, r * 0.07)))
    licht = Image.fromarray(np.minimum(np.asarray(licht), np.asarray(scheibe)), "L")
    hell = radial(gr, gr, c - r * 0.3, c - r * 0.35, r * 0.1, c, c, r * 1.05,
                  [(0, "#fffbe8", 1), (0.45, "#ffe9b0", 1), (1, "#c9a86a", 1)])
    bild.alpha_composite(_durch_maske(_mit_textur(hell, tex), licht))
    return bild


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


def messe_text(text, *, breite, groesse, name, zeilenhoehe=1.12, max_zeilen=4, min_groesse=30, m=1.0):
    """Wie messeText im Dashboard: Schrift wird kleiner, bis der Text in max_zeilen passt."""
    g = groesse
    while True:
        font = schrift(name, g * m)
        zeilen = umbrechen(font, text, breite * m)
        if len(zeilen) <= max_zeilen or g - 4 < min_groesse:
            break
        g -= 4
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
    "wissen": {"de": "Astro-Wissen", "en": "Astro knowledge", "hu": "Asztro-tudás", "it": "Astro-sapere"},
    "ritual": {"de": "Ritual", "en": "Ritual", "hu": "Rituálé", "it": "Rituale"},
    "mitmachen": {"de": "Mitmachen", "en": "Your turn", "hu": "Te jössz", "it": "Tocca a te"},
    "rueckblick": {"de": "Rückblick & Vorschau", "en": "Look back & ahead", "hu": "Vissza és előre", "it": "Bilancio e anteprima"},
    "ereignis": {"de": "Besonderer Himmel", "en": "Special sky", "hu": "Különleges égbolt", "it": "Cielo speciale"},
}
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
    if post.get("art") == "post" and punkte:
        hat_zeichen = sum(zeichen_aus_text(x) is not None for x in punkte) >= 2
        aufbau = "zeichen" if hat_zeichen else "schritte"
    elif post.get("art") == "post" and layout == "liebe":
        aufbau = "liebe"
    else:
        aufbau = "mond"
    sprache = (post.get("sprache") or "de")[:2]
    label = (BESCHRIFTUNG.get(layout) or {}).get(sprache) if layout in BESCHRIFTUNG else None
    return {"layout": layout, "aufbau": aufbau, "palette": palette, "label": label, "punkte": punkte}


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


def _cta(draw, bild, W, unten, story, sprache, m):
    text = LINK_IN_BIO.get(sprache or "de", LINK_IN_BIO["de"])
    font = schrift("inter600", (32 if story else 28) * m)
    stern_h = (13 if story else 11.5) * m
    lueck = 16 * m
    tb = font.getlength(text)
    bw = tb + lueck + 2 * stern_h * 0.74 + 70 * m
    bh, by = (74 if story else 64) * m, (unten + (100 if story else 78)) * m
    x0 = W * m / 2 - bw / 2
    draw.rounded_rectangle([x0, by, x0 + bw, by + bh], radius=bh / 2, outline=(230, 207, 156, 191), width=max(1, int(2 * m)))
    tx = W * m / 2 - (tb + lueck + 2 * stern_h * 0.74) / 2
    draw.text((tx, by + bh / 2 + m), text, font=font, fill=(243, 231, 201, 255), anchor="lm")
    sx = tx + tb + lueck + stern_h * 0.74
    draw.polygon(stern_punkte(sx, by + bh / 2 + m, stern_h), fill=(243, 231, 201, 255))


def marke(bild: Image.Image, W: int, H: int, story: bool, sprache: str, m: float = 1.0) -> None:
    """SORAYA, LUXURY ASTRO GUIDE und der 'Link in Bio'-Knopf unten."""
    d = ImageDraw.Draw(bild, "RGBA")
    unten = H - 300 if story else H - 192
    gesperrt(d, "SORAYA", W * m / 2, unten * m, schrift("cinzel", (50 if story else 42) * m), 14 * m, (230, 207, 156, 255))
    gesperrt(d, "LUXURY ASTRO GUIDE", W * m / 2, (unten + (50 if story else 42)) * m,
             schrift("inter500", (22 if story else 19) * m), 8 * m, (143, 131, 173, 255))
    _cta(d, bild, W, unten, story, sprache, m)


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


def _karten(d, punkte, y, W, story, m, akzent, zeichen: bool):
    """Drei Karten untereinander: Medaillon (Sternzeichen-Symbol oder Nummer) + Text."""
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
                   glyphe=ZEICHEN_GLYPHE[idx] if idx is not None else None, zahl=None if idx is not None else i + 1)
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


def bild(post: dict, format: str = "feed") -> Image.Image:
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
    idx_mond = zeichen_aus_text(meta.get("mond_zeichen") or "")
    wasser = ZEICHEN_GLYPHE[idx_mond] if idx_mond is not None and st["layout"] in ("wissen", "zeichen", "ereignis") \
        else ("?" if st["layout"] == "mitmachen" else None)
    if wasser:
        ebene = Image.new("RGBA", leinwand.size, (0, 0, 0, 0))
        font = schrift("zeichen" if wasser != "?" else "cormorant", (760 if story else 640) * m)
        ImageDraw.Draw(ebene).text((W * m / 2, H * m * 0.56), wasser, font=font, fill=akzent + (255,), anchor="mm")
        aufkleben(leinwand, _mit_alpha(ebene, 0.07))

    zeichen_h = 124 if story else 100
    z = portal(int(zeichen_h * m))
    s = zeichen_h * m / 312
    aufkleben(leinwand, z, (W * m / 2 - 256 * s, (118 if story else 62) * m - 112 * s))
    eyebrow = "  ·  ".join(x for x in (meta.get("datum_kurz"), meta.get("mond_phase")) if x) if mit_mond else "SORAYA"
    gesperrt(d, eyebrow.upper(), W * m / 2, (285 if story else 200) * m,
             schrift("inter500", (30 if story else 26) * m), 4 * m, (201, 168, 106, 255))

    unten = H - 300 if story else H - 192
    oben = 350 if story else 245
    if st["label"]:
        oben += _etikett(d, st["label"], W / 2, oben - (10 if story else 18), m, akzent) - (0 if story else 14)
    platz = (unten - (150 if story else 110)) - oben

    titel = messe_text(post.get("titel") or post.get("text") or "", breite=W - 180, groesse=108 if story else 92,
                       name="cormorant", max_zeilen=4 if story else 3, min_groesse=56)
    unter = messe_text(post["untertitel"], breite=W - 220, groesse=42 if story else 36, name="inter400",
                       zeilenhoehe=1.35, max_zeilen=3, min_groesse=28) if post.get("untertitel") else None
    frage_text = post.get("text") if post.get("art") == "story" and post.get("text") and post.get("text") != post.get("titel") else ""
    pad = 44 if story else 34
    frage = messe_text(frage_text, breite=W - 220 - 2 * pad, groesse=46 if story else 36, name="inter500",
                       zeilenhoehe=1.38, max_zeilen=6 if story else 4, min_groesse=28) if frage_text else None
    ab_mond, ab_unter, ab_frage = (110, 36, 70) if story else (70, 26, 44)

    karten = st["aufbau"] in ("zeichen", "schritte")
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
        _karten(d, st["punkte"], y + ab_frage * 0.8, W, story, m, akzent, st["aufbau"] == "zeichen")
        if mit_mond:
            mr = 46 if story else 38
            mb = mond(mr * m, meta.get("phase_index"), meta.get("beleuchtung"))
            aufkleben(leinwand, mb, ((W - 110) * m - mb.width / 2, (story and 180 or 120) * m - mb.height / 2))
    else:
        rest = titel["hoehe"] + (ab_unter + unter["hoehe"] if unter else 0) + (ab_frage + frage["hoehe"] + 2 * pad if frage else 0)
        r = (150 if story else 105) if mit_mond else 0
        if mit_mond:
            r = max(60, min(r, (platz - rest - ab_mond) / 2))
        gesamt = rest + (2 * r + ab_mond if mit_mond else 0)
        y = oben + max(0, (platz - gesamt) / 2)
        if mit_mond:
            if st["aufbau"] == "liebe":
                _liebe_ringe(d, W / 2, y + r, r, m, akzent)
            schein = radial(int(4 * r * m), int(4 * r * m), 2 * r * m, 2 * r * m, r * 0.5 * m, 2 * r * m, 2 * r * m, 2 * r * m,
                            [(0, "#ffe9b0", 0.16), (1, "#ffe9b0", 0)])
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
    marke(leinwand, W, H, story, post.get("sprache") or "de", m)
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
