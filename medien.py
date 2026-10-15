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
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCHRIFTEN = Path(__file__).parent / "fonts"
LINK_IN_BIO = {"de": "Link in Bio", "en": "Link in bio", "hu": "Link a bióban", "it": "Link in bio"}
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
             "inter400": "Inter-Regular.ttf", "inter500": "Inter-Medium.ttf", "inter600": "Inter-SemiBold.ttf"}[name]
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


def mond(r: float, phase_index, beleuchtung) -> Image.Image:
    """Mondscheibe (Licht rechts = zunehmend; Breite nach echter Beleuchtung in %). Mittelpunkt = Bildmitte."""
    rand = max(1.0, r / 40)
    gr = int(math.ceil(2 * r + 2 * rand + 4))
    c = gr / 2
    bild = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    scheibe = Image.new("L", (gr, gr), 0)
    ImageDraw.Draw(scheibe).ellipse([c - r, c - r, c + r, c + r], fill=255)
    dunkel = radial(gr, gr, c - r * 0.2, c - r * 0.3, r * 0.1, c, c, r, [(0, "#2a2044", 1), (1, "#120c22", 1)])
    bild.alpha_composite(_durch_maske(dunkel, scheibe))
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
    hell = radial(gr, gr, c - r * 0.3, c - r * 0.35, r * 0.1, c, c, r * 1.05,
                  [(0, "#fffbe8", 1), (0.45, "#ffe9b0", 1), (1, "#c9a86a", 1)])
    bild.alpha_composite(_durch_maske(hell, licht))
    return bild


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
def umbrechen(font: ImageFont.FreeTypeFont, text: str, breite: float) -> list[str]:
    zeilen, z = [], ""
    for w in str(text or "").split():
        t = f"{z} {w}" if z else w
        if font.getlength(t) > breite and z:
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
        while z and font.getlength(z + " …") > breite * m:
            z = z.rsplit(" ", 1)[0] if " " in z else ""
        zeilen[-1] = z + " …"
    return {"zeilen": zeilen, "g": g, "name": name, "zh": zeilenhoehe,
            "hoehe": (len(zeilen) - 1) * g * zeilenhoehe + g}


def zeichne_text(draw, block, x, oben, farbe, m=1.0, alpha=255):
    font = schrift(block["name"], block["g"] * m)
    for i, z in enumerate(block["zeilen"]):
        y = oben + block["g"] * 0.8 + i * block["g"] * block["zh"]
        draw.text((x * m, y * m), z, font=font, fill=_rgb(farbe) + (alpha,), anchor="ms")


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
@lru_cache(maxsize=4)
def _verlauf_hintergrund(W: int, H: int) -> Image.Image:
    """Der weiche Verlauf reicht in Viertel-Aufloesung (spart Rechenzeit)."""
    q = 4
    return radial(W // q, H // q, W / 2 / q, 0, 40 / q, W / 2 / q, H * 0.25 / q, H / q,
                  [(0, "#2a1650", 1), (0.45, "#120a26", 1), (1, "#07040f", 1)]).convert("RGB").resize((W, H), Image.BICUBIC)


def hintergrund(W: int, H: int, seed, story: bool, m: float = 1.0) -> Image.Image:
    bg = _verlauf_hintergrund(W, H).resize((int(W * m), int(H * m)), Image.BICUBIC)
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
    text = LINK_IN_BIO.get(sprache or "de", "Link in Bio")
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
    unten = H - 300 if story else H - 175
    gesperrt(d, "SORAYA", W * m / 2, unten * m, schrift("cinzel", (50 if story else 42) * m), 14 * m, (230, 207, 156, 255))
    gesperrt(d, "LUXURY ASTRO GUIDE", W * m / 2, (unten + (50 if story else 42)) * m,
             schrift("inter500", (22 if story else 19) * m), 8 * m, (143, 131, 173, 255))
    _cta(d, bild, W, unten, story, sprache, m)


def bild(post: dict, format: str = "feed") -> Image.Image:
    """Das fertige Post-Bild als RGB (1080x1350 oder 1080x1920)."""
    story = format == "story"
    W, H = 1080, (1920 if story else 1350)
    m = SS
    leinwand = hintergrund(W, H, post.get("id") or 1, story, m)
    d = ImageDraw.Draw(leinwand, "RGBA")
    meta = post.get("meta") or {}
    mit_mond = meta.get("phase_index") is not None

    zeichen_h = 124 if story else 100
    z = portal(int(zeichen_h * m))
    s = zeichen_h * m / 312
    aufkleben(leinwand, z, (W * m / 2 - 256 * s, (118 if story else 62) * m - 112 * s))

    eyebrow = "  ·  ".join(x for x in (meta.get("datum_kurz"), meta.get("mond_phase")) if x) if mit_mond else "SORAYA"
    gesperrt(d, eyebrow.upper(), W * m / 2, (285 if story else 200) * m,
             schrift("inter500", (30 if story else 26) * m), 4 * m, (201, 168, 106, 255))

    unten = H - 300 if story else H - 175
    oben = 350 if story else 245
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
    # Liste fuers Bild (z. B. drei Sternzeichen): goldener Stern vor jedem Punkt
    punkte = [str(x).strip() for x in (meta.get("bild_punkte") or []) if str(x).strip()][:3]
    pg = (44 if story else 38)
    punkt_bloecke = [messe_text(x, breite=W - 300, groesse=pg, name="inter500", max_zeilen=1, min_groesse=26) for x in punkte]
    punkte_h = sum(b["g"] * 1.65 for b in punkt_bloecke)
    rest = titel["hoehe"] + (ab_unter + unter["hoehe"] if unter else 0) + (ab_frage + frage["hoehe"] + 2 * pad if frage else 0) \
        + (ab_frage + punkte_h if punkte else 0)
    r = (150 if story else 105) if mit_mond else 0
    if mit_mond:
        r = max(60, min(r, (platz - rest - ab_mond) / 2))
    gesamt = rest + (2 * r + ab_mond if mit_mond else 0)
    y = oben + max(0, (platz - gesamt) / 2)
    if mit_mond:
        mb = mond(r * m, meta.get("phase_index"), meta.get("beleuchtung"))
        aufkleben(leinwand, mb, (W * m / 2 - mb.width / 2, (y + r) * m - mb.height / 2))
        y += 2 * r + ab_mond
    zeichne_text(d, titel, W / 2, y, "#F6E3B4", m)
    y += titel["hoehe"]
    if unter:
        y += ab_unter
        zeichne_text(d, unter, W / 2, y, "#C3B7DA", m)
        y += unter["hoehe"]
    if punkte:
        y += ab_frage
        for b in punkt_bloecke:
            font = schrift(b["name"], b["g"] * m)
            tb = font.getlength(b["zeilen"][0])
            sh = b["g"] * 0.36
            x0 = W / 2 - (tb / m + sh * 2.4) / 2
            d.polygon([(px * m, py * m) for px, py in stern_punkte(x0 + sh * 0.74, y + b["g"] * 0.5, sh)],
                      fill=(233, 207, 156, 255))
            d.text(((x0 + sh * 2.4) * m, (y + b["g"] * 0.8) * m), b["zeilen"][0], font=font,
                   fill=(239, 232, 248, 255), anchor="ls")
            y += b["g"] * 1.65
    if frage:
        y += ab_frage
        d.rounded_rectangle([110 * m, y * m, (W - 110) * m, (y + frage["hoehe"] + 2 * pad) * m], radius=28 * m,
                            fill=(255, 255, 255, 13), outline=(230, 207, 156, 89), width=int(2 * m))
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
