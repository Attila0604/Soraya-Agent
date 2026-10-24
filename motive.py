"""
Hauptmotive fuer die Reels (statt immer nur dem Mond): je Format ein eigenes, bewegtes Bild in der Mitte.

- mond    : der echte Mond (Phase) -- Deine Woche, Rueckblick, Voll-/Neumond
- rad     : Tierkreis-Rad dreht sich langsam, in der Mitte das grosse Sternzeichen -- Sternzeichen im Fokus, Saisonbeginn
- planet  : goldener Ringplanet, schwebt leicht -- Astro-Wissen
- venus   : rosegoldener Planet mit Schein (zwei Lichter kreisen) -- Liebe & Beziehung
- kerze   : Kerze mit flackernder Flamme -- Ritual
- karten  : drei Karten drehen sich nacheinander um (A/B/C) -- Mitmachen

Das zweite Reel des Tages (meta.reel_nr = 2) bekommt ein anderes Motiv als das erste, damit es nicht gleich aussieht.
Alles wird einmal vorbereitet und je Bild nur noch verschoben, gedreht oder ueberblendet (schnell genug fuer 30 Bilder/s).
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import medien

GLYPHE = medien.ZEICHEN_GLYPHE


def waehle(post: dict, st: dict) -> str:
    meta = post.get("meta") or {}
    thema = meta.get("thema") or ""
    if thema.startswith("Großes Ereignis"):
        motiv = "rad" if st.get("zeichen") is not None else (
            "mond" if any(w in thema for w in ("mond", "Mond")) else "planet")
    else:
        motiv = {"Sternzeichen im Fokus": "rad", "Astro-Wissen": "planet", "Liebe & Beziehung": "venus",
                 "Ritual": "kerze", "Mitmachen": "karten"}.get(thema, "mond")
    if meta.get("reel_nr") == 2:                     # zweites Reel des Tages: anderes Motiv
        motiv = {"mond": "rad", "rad": "mond", "planet": "mond", "venus": "mond", "kerze": "mond", "karten": "rad"}[motiv]
    if motiv == "mond" and meta.get("phase_index") is None:
        motiv = "planet"                             # ohne Mondphase kein echter Mond
    return motiv


def _weich(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _alpha(ebene: Image.Image, f: float) -> Image.Image:
    if f >= 0.999:
        return ebene
    e = ebene.copy()
    e.putalpha(e.getchannel("A").point(lambda v: int(v * max(0.0, f))))
    return e


def _glut(breite: int, hoehe: int, farbe, staerke: float = 90) -> Image.Image:
    yy, xx = np.mgrid[0:hoehe, 0:breite]
    r = np.sqrt(((xx - breite / 2) / (breite / 2)) ** 2 + ((yy - hoehe / 2) / (hoehe / 2)) ** 2)
    a = (np.clip(1 - r, 0, 1) ** 2 * staerke).astype(np.uint8)
    g = Image.new("RGBA", (breite, hoehe), tuple(farbe) + (0,))
    g.putalpha(Image.fromarray(a, "L"))
    return g


def _kleben(bild: Image.Image, ebene: Image.Image, cx: float, cy: float) -> None:
    medien.aufkleben(bild, ebene, (cx - ebene.width / 2, cy - ebene.height / 2))


class Motiv:
    """Grundform: zeichne(bild, t, sichtbar) -- sichtbar 0..1 (blendet vor der Endkarte aus)."""
    mit_bahn = False          # Umlaufbahn mit Lichtpunkt(en) um das Motiv
    mit_sternbild = True

    def zeichne(self, bild: Image.Image, t: float, sichtbar: float) -> None:  # pragma: no cover - Schnittstelle
        raise NotImplementedError


class Rad(Motiv):
    mit_sternbild = False

    def __init__(self, cx, cy, zeichen, akzent, r=290):
        self.cx, self.cy, self.akzent = cx, cy, tuple(akzent)
        m = 2
        D = int((r + 40) * 2 * m)
        ring = Image.new("RGBA", (D, D), (0, 0, 0, 0))
        d = ImageDraw.Draw(ring)
        c = D / 2
        for rr, w, a in ((r, 3, 200), (r * 0.80, 2, 150), (r * 0.98, 1, 90)):
            d.ellipse([c - rr * m, c - rr * m, c + rr * m, c + rr * m], outline=self.akzent + (a,), width=w * m)
        schrift = medien.schrift("zeichen", r * 0.13 * m)
        for i in range(12):
            w = math.radians(i * 30 - 90)
            for k in range(3):                       # kleine Striche zwischen den Zeichen
                ww = w + math.radians(15 + (k - 1) * 4)
                r1, r2 = r * 0.80 * m, (r * (0.84 if k == 1 else 0.82)) * m
                d.line([(c + r1 * math.cos(ww), c + r1 * math.sin(ww)), (c + r2 * math.cos(ww), c + r2 * math.sin(ww))],
                       fill=self.akzent + (110,), width=m)
            gx, gy = c + r * 0.90 * m * math.cos(w), c + r * 0.90 * m * math.sin(w)
            hell = 255 if i == zeichen else 150
            d.text((gx, gy), GLYPHE[i], font=schrift, fill=self.akzent + (hell,), anchor="mm")
        self.ring = ring.resize((D // m, D // m), Image.LANCZOS)
        self.schein = _glut(int(r * 1.5), int(r * 1.5), self.akzent, 70)
        self.mitte = None
        if zeichen is not None:
            g = Image.new("RGBA", (int(r * 1.2 * m), int(r * 1.2 * m)), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((g.width / 2, g.height / 2), GLYPHE[zeichen], font=medien.schrift("zeichen", r * 0.78 * m),
                                   fill=(246, 227, 180, 255), anchor="mm")
            g = g.resize((g.width // m, g.height // m), Image.LANCZOS)
            weich = g.filter(ImageFilter.GaussianBlur(14))
            self.mitte = Image.new("RGBA", g.size, (0, 0, 0, 0))
            self.mitte.alpha_composite(_alpha(weich, 0.9))
            self.mitte.alpha_composite(g)
        else:
            self.mitte = medien.portal(int(r * 0.9))

    def zeichne(self, bild, t, sichtbar):
        auf = _weich(t / 0.9) * sichtbar
        if auf <= 0:
            return
        _kleben(bild, _alpha(self.schein, (0.7 + 0.3 * math.sin(t * 1.3)) * auf), self.cx, self.cy)
        ring = self.ring.rotate(-t * 5.5, resample=Image.BICUBIC)     # dreht sich langsam im Uhrzeigersinn
        _kleben(bild, _alpha(ring, auf), self.cx, self.cy)
        s = 0.86 + 0.14 * _weich(t / 1.1) + 0.02 * math.sin(t * 1.6)
        m = self.mitte.resize((int(self.mitte.width * s), int(self.mitte.height * s)), Image.BILINEAR)
        _kleben(bild, _alpha(m, auf), self.cx, self.cy)


def _kugel(r: int, hell, dunkel, baender: bool, seed: int) -> Image.Image:
    """Beleuchtete Kugel (Licht von oben links), optional mit weichen Wolkenbaendern."""
    n = 2 * r
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    x, y = (xx - r + 0.5) / r, (yy - r + 0.5) / r
    rr = x * x + y * y
    z = np.sqrt(np.clip(1 - rr, 0, 1))
    licht = np.clip(-0.55 * x - 0.6 * y + 0.58 * z, 0, 1) ** 0.9
    farbe = np.array(dunkel, np.float32) + (np.array(hell, np.float32) - np.array(dunkel, np.float32)) * licht[..., None]
    if baender:
        rnd = np.random.default_rng(seed)
        phase = rnd.uniform(0, 6.28, 3)
        streifen = (0.5 + 0.5 * np.sin(y * 9 + phase[0] + 0.6 * np.sin(x * 3 + phase[1]))) * 0.16 \
            + (0.5 + 0.5 * np.sin(y * 23 + phase[2])) * 0.06
        farbe *= (1 - streifen)[..., None]
    rand = np.clip((rr - 0.82) / 0.18, 0, 1)                    # heller Saum am Rand (Atmosphaere)
    farbe = farbe + (np.array(hell, np.float32) * 0.35 - farbe) * (rand ** 2)[..., None] * 0.5
    alpha = np.clip((1 - rr) * r * 0.9, 0, 1) * 255
    rgba = np.dstack([np.clip(farbe, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


class Planet(Motiv):
    def __init__(self, cx, cy, akzent, seed, venus=False, r=170):
        self.cx, self.cy, self.venus = cx, cy, venus
        self.mit_bahn = venus
        if venus:
            self.kugel = _kugel(r, (247, 205, 190), (92, 38, 66), False, seed)
            self.schein = _glut(int(r * 4.2), int(r * 4.2), (255, 186, 170), 110)
            self.hinten = self.vorne = None
        else:
            self.kugel = _kugel(r, (244, 222, 170), (58, 44, 92), True, seed)
            self.schein = _glut(int(r * 3.4), int(r * 3.4), tuple(akzent), 80)
            # Ring: flache Ellipse, hintere und vordere Haelfte getrennt (der Planet liegt dazwischen)
            m = 2
            rw, rh = int(r * 2.25), int(r * 0.52)
            ring = Image.new("RGBA", (rw * 2 * m, rh * 2 * m + 8 * m), (0, 0, 0, 0))
            d = ImageDraw.Draw(ring)
            c = (ring.width / 2, ring.height / 2)
            for k in range(14):
                f = k / 13
                ax, ay = (rw * (0.62 + 0.38 * f)) * m, (rh * (0.62 + 0.38 * f)) * m
                a = int(150 * (0.45 + 0.55 * math.sin(math.pi * f)) * (0.55 if 5 <= k <= 6 else 1))
                d.ellipse([c[0] - ax, c[1] - ay, c[0] + ax, c[1] + ay], outline=tuple(akzent) + (a,), width=m)
            ring = ring.resize((ring.width // m, ring.height // m), Image.LANCZOS)
            oben = ring.copy()
            oben.paste((0, 0, 0, 0), (0, ring.height // 2, ring.width, ring.height))
            unten = ring.copy()
            unten.paste((0, 0, 0, 0), (0, 0, ring.width, ring.height // 2))
            self.hinten = oben.rotate(16, resample=Image.BICUBIC, expand=True)
            self.vorne = unten.rotate(16, resample=Image.BICUBIC, expand=True)

    def zeichne(self, bild, t, sichtbar):
        auf = _weich(t / 0.9) * sichtbar
        if auf <= 0:
            return
        y = self.cy + 8 * math.sin(t * 0.9)                        # schwebt leicht
        _kleben(bild, _alpha(self.schein, (0.75 + 0.25 * math.sin(t * 1.2)) * auf), self.cx, y)
        if self.hinten is not None:
            _kleben(bild, _alpha(self.hinten, auf), self.cx, y)
        s = 0.95 + 0.05 * _weich(t / 4)
        k = self.kugel.resize((int(self.kugel.width * s), int(self.kugel.height * s)), Image.BILINEAR)
        _kleben(bild, _alpha(k, auf), self.cx, y)
        if self.vorne is not None:
            _kleben(bild, _alpha(self.vorne, auf), self.cx, y)


class Kerze(Motiv):
    def __init__(self, cx, cy):
        self.cx, self.cy = cx, cy + 60
        m = 2
        bw, bh = 150, 300
        koerper = Image.new("RGBA", (bw * m, bh * m), (0, 0, 0, 0))
        verlauf = np.zeros((bh * m, bw * m, 4), np.float32)
        xx = np.linspace(-1, 1, bw * m)[None, :]
        yy = np.linspace(0, 1, bh * m)[:, None]
        hell = 0.55 + 0.45 * np.clip(1 - np.abs(xx + 0.25) * 0.9, 0, 1) - 0.25 * yy
        verlauf[..., 0], verlauf[..., 1], verlauf[..., 2] = 246 * hell, 232 * hell, 205 * hell
        verlauf[..., 3] = 255
        maske = Image.new("L", koerper.size, 0)
        ImageDraw.Draw(maske).rounded_rectangle([0, 18 * m, bw * m - 1, bh * m - 1], radius=16 * m, fill=255)
        ImageDraw.Draw(maske).ellipse([0, 0, bw * m - 1, 36 * m], fill=255)
        koerper = Image.fromarray(np.clip(verlauf, 0, 255).astype(np.uint8), "RGBA")
        koerper.putalpha(maske)
        d = ImageDraw.Draw(koerper)
        d.ellipse([10 * m, 4 * m, bw * m - 10 * m, 32 * m], fill=(255, 244, 222, 255))          # Wachsspiegel
        d.line([(bw * m / 2, 18 * m), (bw * m / 2, -2)], fill=(60, 40, 30, 255), width=3 * m)    # Docht
        self.koerper = koerper.resize((bw, bh), Image.LANCZOS)
        self.bh = bh
        # Flamme: Tropfenform mit hellem Kern, weich gezeichnet
        fw, fh = 90, 170
        fl = Image.new("RGBA", (fw * m, fh * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(fl)
        for farbe, s in (((255, 150, 60, 150), 1.0), ((255, 200, 110, 220), 0.72), ((255, 248, 220, 255), 0.42)):
            w, h = fw * m * 0.5 * s, fh * m * 0.92 * s
            cxx, unten = fw * m / 2, fh * m * 0.96
            pts = []
            for i in range(41):
                u = i / 40                                     # 0 = Spitze, 1 = unten
                breite = w * math.sin(math.pi * u ** 0.75) * (0.55 + 0.45 * u)
                pts.append((cxx + breite, unten - h * (1 - u)))
            for i in range(40, -1, -1):
                u = i / 40
                breite = w * math.sin(math.pi * u ** 0.75) * (0.55 + 0.45 * u)
                pts.append((cxx - breite, unten - h * (1 - u)))
            d.polygon(pts, fill=farbe)
        fl = fl.filter(ImageFilter.GaussianBlur(5 * m))
        self.flamme = fl.resize((fw, fh), Image.LANCZOS)
        self.schein = _glut(760, 760, (255, 176, 92), 130)

    def zeichne(self, bild, t, sichtbar):
        auf = _weich(t / 0.8) * sichtbar
        if auf <= 0:
            return
        flacker = 0.82 + 0.1 * math.sin(t * 7.3) + 0.08 * math.sin(t * 12.9 + 1)
        top = self.cy - self.bh / 2
        _kleben(bild, _alpha(self.schein, flacker * auf), self.cx, top - 30)
        _kleben(bild, _alpha(self.koerper, auf), self.cx, self.cy)
        sy = 0.9 + 0.12 * (0.5 + 0.5 * math.sin(t * 6.1)) + 0.05 * math.sin(t * 13.7)
        f = self.flamme.resize((int(self.flamme.width * (1.02 - 0.04 * math.sin(t * 9))), int(self.flamme.height * sy)), Image.BILINEAR)
        medien.aufkleben(bild, _alpha(f, auf), (self.cx - f.width / 2 + 3 * math.sin(t * 2.3), top - f.height + 10))


class Karten(Motiv):
    mit_sternbild = False

    def __init__(self, cx, cy, akzent, beschriftung=("A", "B", "C")):
        self.cx, self.cy, self.akzent = cx, cy, tuple(akzent)
        m = 2
        kw, kh = 210, 330
        self.karten = []
        for zeichen in beschriftung:
            k = Image.new("RGBA", (kw * m, kh * m), (0, 0, 0, 0))
            d = ImageDraw.Draw(k)
            d.rounded_rectangle([0, 0, kw * m - 1, kh * m - 1], radius=20 * m, fill=(28, 16, 54, 245),
                                outline=self.akzent + (230,), width=3 * m)
            d.rounded_rectangle([12 * m, 12 * m, kw * m - 13 * m, kh * m - 13 * m], radius=13 * m,
                                outline=self.akzent + (110,), width=m)
            d.text((kw * m / 2, kh * m * 0.52), zeichen, font=medien.schrift("cinzel", 120 * m), fill=(246, 227, 180, 255), anchor="mm")
            for sx, sy in ((kw * m / 2, 46 * m), (kw * m / 2, kh * m - 46 * m)):
                d.polygon(medien.stern_punkte(sx, sy, 16 * m), fill=self.akzent + (220,))
            self.karten.append(k.resize((kw, kh), Image.LANCZOS))
        self.schein = _glut(900, 620, self.akzent, 60)
        self.kw = kw

    def zeichne(self, bild, t, sichtbar):
        if sichtbar <= 0:
            return
        _kleben(bild, _alpha(self.schein, (0.6 + 0.4 * math.sin(t * 1.4)) * sichtbar * _weich(t / 1.2)), self.cx, self.cy)
        abstand = self.kw + 34
        for i, k in enumerate(self.karten):
            dreh = _weich((t - 0.25 - 0.35 * i) / 0.55)          # Karte dreht sich auf (Breite 0 -> voll)
            if dreh <= 0:
                continue
            mitte = i == 1
            s = 1.08 if mitte else 1.0
            w = max(2, int(k.width * s * dreh))
            kk = k.resize((w, int(k.height * s)), Image.BILINEAR)
            schweben = 10 * math.sin(t * 1.1 + i * 1.9) - (16 if mitte else 0)
            _kleben(bild, _alpha(kk, sichtbar), self.cx + (i - 1) * abstand, self.cy + schweben)


def baue(motiv: str, cx: float, cy: float, *, zeichen, akzent, seed: int, post: dict) -> Motiv | None:
    """None = der echte Mond (zeichnet reel.py selbst)."""
    if motiv == "rad":
        return Rad(cx, cy, zeichen, akzent)
    if motiv == "planet":
        return Planet(cx, cy, akzent, seed)
    if motiv == "venus":
        return Planet(cx, cy, akzent, seed, venus=True)
    if motiv == "kerze":
        return Kerze(cx, cy)
    if motiv == "karten":
        return Karten(cx, cy, akzent)
    return None
