"""
Reel-Video auf dem Server (1080x1920, 30 Bilder/s, etwa 15 Sekunden, MP4/H.264)

Ablauf: Sternenhimmel blendet auf, der Mond (echte Phase) leuchtet, die Texte des
Reels erscheinen nacheinander (Hook, Einblendungen), am Ende das Soraya-Zeichen mit
Schlusssatz und "Link in Bio". Die Texte stehen in der "sicheren Zone" (Instagram und
TikTok legen unten Beschriftung und Knoepfe ueber das Video).

Ton: eine stille Tonspur (manche Plattformen erwarten eine). Musik fuegst du beim
Posten in Instagram/TikTok hinzu -- Trend-Sounds bringen dort mehr Reichweite.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw

import medien

W, H, FPS = 1080, 1920, 30
VERSION = "reel-3"
EINBLENDEN, AUSBLENDEN = 0.45, 0.4


def ffmpeg_pfad() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pfad = shutil.which("ffmpeg")
        if not pfad:
            raise RuntimeError("ffmpeg fehlt (pip install imageio-ffmpeg).")
        return pfad


def _weich(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def texte(post: dict) -> tuple[list[str], str]:
    """(Zeilen nacheinander, Schlusssatz) aus Skript und Post."""
    sk = post.get("skript") or {}
    zeilen = []
    for t in [sk.get("hook")] + list(sk.get("einblendungen") or []):
        t = (t or "").strip()
        if t and t not in zeilen:
            zeilen.append(t)
    if len(zeilen) < 2:   # aeltere Reels ohne Einblendungen: Ueberschrift und Unterzeile
        for t in (post.get("titel"), post.get("untertitel")):
            t = (t or "").strip()
            if t and t not in zeilen:
                zeilen.append(t)
    if not zeilen:
        zeilen = [(post.get("text") or "Soraya").strip()[:120]]
    return zeilen[:5], (sk.get("schluss") or "").strip()


def _textkarte(text: str, *, breite: int, groesse: int, name: str, farbe: str, zeilenhoehe=1.15, max_zeilen=4,
               akzent=(233, 207, 156)):
    """Text als RGBA-Ebene (doppelt gross gezeichnet, dann verkleinert) und die Wort-Kaestchen fuers
    Wort-fuer-Wort-Einblenden. Beginnt der Text mit einem Sternzeichen ("Scorpio: ..."), steht darueber
    ein Medaillon mit dem Symbol und dem Namen."""
    m = 2
    idx = medien.zeichen_aus_text(text)
    kopf_h, name_txt = 0, ""
    if idx is not None:
        teile = re.split(r"\s*[:–—-]\s*", text, maxsplit=1)
        if len(teile) > 1 and teile[1].strip():
            name_txt, text = teile[0], teile[1][:1].upper() + teile[1][1:]
        kopf_h = 190
    b = medien.messe_text(text, breite=breite, groesse=groesse, name=name, zeilenhoehe=zeilenhoehe,
                          max_zeilen=max_zeilen, min_groesse=max(28, groesse // 2))
    hoehe = int(kopf_h + b["hoehe"] + b["g"] * 0.6)
    bw = breite + 40
    ebene = Image.new("RGBA", (bw * m, hoehe * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(ebene)
    kaesten = []
    if idx is not None:
        medien._medaillon(d, bw / 2, 62, 58, m, akzent, glyphe=medien.ZEICHEN_GLYPHE[idx])
        if name_txt:
            medien.gesperrt(d, name_txt.upper(), bw / 2 * m, 170 * m, medien.schrift("cinzel", 34 * m), 6 * m, akzent + (255,))
        kaesten.append((0, 0, bw, kopf_h))        # Kopf erscheint als erstes "Wort"
    font = medien.schrift(b["name"], b["g"] * m)
    for i, zeile in enumerate(b["zeilen"]):
        grund = kopf_h + b["g"] * 0.8 + i * b["g"] * b["zh"]
        d.text((bw / 2 * m, grund * m), zeile, font=font, fill=medien._rgb(farbe) + (255,), anchor="ms")
        breite_z = font.getlength(zeile) / m
        x = bw / 2 - breite_z / 2
        for w in zeile.split(" "):
            wb = font.getlength(w) / m
            kaesten.append((x - 4, grund - b["g"] * 0.95, x + wb + 4, grund + b["g"] * 0.35))
            x += wb + font.getlength(" ") / m
    return ebene.resize((ebene.width // m, ebene.height // m), Image.LANCZOS), kaesten


def _wort_fuer_wort(karte: Image.Image, kaesten: list, fortschritt: float) -> Image.Image:
    """fortschritt 0..1: Woerter erscheinen nacheinander (jedes blendet kurz weich ein)."""
    if fortschritt >= 1 or not kaesten:
        return karte
    maske = Image.new("L", karte.size, 0)
    md = ImageDraw.Draw(maske)
    n = len(kaesten)
    for i, (x0, y0, x1, y1) in enumerate(kaesten):
        a = _weich((fortschritt * (n + 1.5) - i) / 1.5)
        if a > 0:
            md.rectangle([x0, y0, x1, y1], fill=int(255 * a))
    alpha = np.asarray(karte.getchannel("A"), dtype=np.uint16) * np.asarray(maske, dtype=np.uint16) // 255
    out = karte.copy()
    out.putalpha(Image.fromarray(alpha.astype(np.uint8), "L"))
    return out


def _mit_alpha(ebene: Image.Image, faktor: float) -> Image.Image:
    if faktor >= 0.999:
        return ebene
    a = (np.asarray(ebene.getchannel("A"), dtype=np.float32) * faktor).astype(np.uint8)
    out = ebene.copy()
    out.putalpha(Image.fromarray(a, "L"))
    return out


def _zuschneiden(ebene: Image.Image, x0=0, y0=0):
    """Nur den sichtbaren Teil einer Ebene behalten (spart pro Bild viel Rechenzeit)."""
    box = ebene.getbbox()
    if not box:
        return ebene.crop((0, 0, 1, 1)), (x0, y0)
    return ebene.crop(box), (x0 + box[0], y0 + box[1])


def _endkarte(post: dict) -> Image.Image:
    """Schlussbild: grosses Soraya-Zeichen, Marke, Schlusssatz, Link-Knopf (als Ebene)."""
    m = 2
    ebene = Image.new("RGBA", (W * m, H * m), (0, 0, 0, 0))
    z = medien.portal(300 * m)
    s = 300 * m / 312
    ebene.alpha_composite(z, (int(W * m / 2 - 256 * s), int(470 * m - 112 * s)))
    d = ImageDraw.Draw(ebene)
    medien.gesperrt(d, "SORAYA", W * m / 2, 930 * m, medien.schrift("cinzel", 64 * m), 18 * m, (230, 207, 156, 255))
    medien.gesperrt(d, "LUXURY ASTRO GUIDE", W * m / 2, 990 * m, medien.schrift("inter500", 26 * m), 9 * m, (143, 131, 173, 255))
    _, schluss = texte(post)
    y = 1080
    if schluss:
        b = medien.messe_text(schluss, breite=W - 240, groesse=44, name="inter400", zeilenhoehe=1.35, max_zeilen=3, min_groesse=30)
        medien.zeichne_text(d, b, W / 2, y, "#E4DCF2", m)
        y += b["hoehe"] + 60
    else:
        y += 20
    # "Link in Bio"-Knopf, gleiche Form wie auf den Bildern
    medien._cta(d, ebene, W, y - 100, True, post.get("sprache") or "de", m)
    return ebene.resize((W, H), Image.LANCZOS)


def zeitplan(zeilen: list[str]) -> tuple[list[tuple[float, float]], float, float]:
    """Start/Ende je Zeile, Beginn der Endkarte, Gesamtdauer (Sekunden)."""
    t, plan = 0.0, []                     # Hook ab dem ersten Bild (Vorschaubild, erste Sekunde)
    for i, z in enumerate(zeilen):
        dauer = max(2.4, min(4.2, 1.1 + 0.32 * len(z.split())))
        if i == 0:
            dauer += 0.4
        plan.append((t, t + dauer))
        t += dauer + 0.15
    ende = t + 0.1
    return plan, ende, ende + 3.2


def erstelle(post: dict, ziel: str) -> dict:
    """Rendert das Reel nach `ziel` (MP4). Rueckgabe: {"sekunden", "bilder"}."""
    meta = post.get("meta") or {}
    seed = post.get("id") or 1
    zeilen, _ = texte(post)
    plan, end_start, dauer = zeitplan(zeilen)
    n = int(round(dauer * FPS))

    # --- feste Ebenen einmal vorbereiten
    # leichtes, festes Rauschen gegen Farbstufen im Verlauf (H.264 macht sonst sichtbare Ringe)
    st = medien.stil(post)
    akzent = medien.PALETTEN[st["palette"]]["akzent"]
    roh = np.asarray(medien._verlauf_hintergrund(W, H, st["palette"]), dtype=np.float32)
    rauschen = np.random.default_rng(7).uniform(-1.6, 1.6, roh.shape[:2])[..., None]
    grund = Image.fromarray(np.clip(roh + rauschen, 0, 255).astype(np.uint8), "RGB")
    sterne = medien.stern_liste(W, H, seed, True)
    ruhig = [st for st in sterne if st[3] != (233, 207, 156)]
    funkelnd = [st for st in sterne if st[3] == (233, 207, 156)]
    d = ImageDraw.Draw(grund, "RGBA")
    for x, y, r, farbe, a in ruhig:
        d.ellipse([x - r, y - r, x + r, y + r], fill=farbe + (int(a * 255),))
    oben = Image.new("RGBA", (W, H), (0, 0, 0, 0))                 # kleines Zeichen + Datumszeile
    z = medien.portal(2 * 110)
    s = 2 * 110 / 312
    gross = Image.new("RGBA", (W * 2, 520), (0, 0, 0, 0))
    gross.alpha_composite(z, (int(W - 256 * s), int(20 - 112 * s)))
    eyebrow = "  ·  ".join(x for x in (meta.get("datum_kurz"), meta.get("mond_phase")) if x) or "SORAYA"
    medien.gesperrt(ImageDraw.Draw(gross), eyebrow.upper(), W, 2 * 170, medien.schrift("inter500", 2 * 30), 2 * 4, (201, 168, 106, 255))
    if st["label"]:
        medien._etikett(ImageDraw.Draw(gross, "RGBA"), st["label"], W / 2, 196, 2, akzent)
    gross = gross.resize((W, 260), Image.LANCZOS)
    oben.alpha_composite(gross, (0, 230))
    oben, oben_pos = _zuschneiden(oben)
    mit_mond = meta.get("phase_index") is not None
    r = 200
    mond = medien.mond(r * 2, meta.get("phase_index"), meta.get("beleuchtung")) if mit_mond else None
    if mond is not None:
        mond = mond.resize((mond.width // 2, mond.height // 2), Image.LANCZOS)
    schein = medien.radial(2 * r + 300, 2 * r + 300, r + 150, r + 150, r * 0.6, r + 150, r + 150, r + 150,
                           [(0, "#ffe9b0", 0.22), (1, "#ffe9b0", 0)])
    mond_y = 760
    karten = [_textkarte(z_, breite=W - 160, groesse=92 if i == 0 else 78, name="cormorant", farbe="#F6E3B4",
                         max_zeilen=4, akzent=akzent) for i, z_ in enumerate(zeilen)]
    text_mitte = 1270
    endkarte, end_pos = _zuschneiden(_endkarte(post))

    ffmpeg = ffmpeg_pfad()
    befehl = [ffmpeg, "-y", "-loglevel", "error",
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
              "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
              "-shortest", "-map", "0:v", "-map", "1:a",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
              "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", ziel]
    proz = subprocess.Popen(befehl, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / FPS
            bild = grund.copy()
            dd = ImageDraw.Draw(bild, "RGBA")
            for k, (x, y, rr, farbe, a) in enumerate(funkelnd):      # goldene Sterne funkeln
                f = 0.55 + 0.45 * math.sin(t * (1.3 + (k % 5) * 0.37) + k * 1.7)
                dd.ellipse([x - rr, y - rr, x + rr, y + rr], fill=farbe + (int(a * f * 255),))
            sichtbar_ende = 1 - _weich((t - end_start) / 0.8)      # Mond und Texte gehen vor der Endkarte
            if sichtbar_ende > 0:
                medien.aufkleben(bild, _mit_alpha(oben, sichtbar_ende), oben_pos)
            if mond is not None and sichtbar_ende > 0:
                auf = 1.0
                puls = 0.75 + 0.25 * math.sin(t * 1.4)
                medien.aufkleben(bild, _mit_alpha(schein, auf * puls * sichtbar_ende),
                                 (W / 2 - schein.width / 2, mond_y - schein.height / 2))
                skala = 0.94 + 0.08 * min(1.0, t / max(end_start, 1))   # langsamer Zoom (Bewegung)
                mb = mond if abs(skala - 1) < 0.002 else mond.resize((int(mond.width * skala), int(mond.height * skala)), Image.BILINEAR)
                medien.aufkleben(bild, _mit_alpha(mb, auf * sichtbar_ende), (W / 2 - mb.width / 2, mond_y - mb.height / 2))
            for (start, stopp), (karte, kaesten) in zip(plan, karten):
                if start - 0.01 <= t <= stopp + AUSBLENDEN:
                    # Hook steht ab dem ersten Bild ganz da, alle weiteren Texte erscheinen Wort fuer Wort
                    fortschritt = 1.0 if start <= 0 else min(1.0, (t - start) / min(1.1, 0.16 * len(kaesten) + 0.3))
                    raus = 1 - _weich((t - stopp) / AUSBLENDEN)
                    if raus > 0.003:
                        k = _wort_fuer_wort(karte, kaesten, fortschritt)
                        medien.aufkleben(bild, _mit_alpha(k, raus),
                                         (W / 2 - karte.width / 2, text_mitte - karte.height / 2))
            if t >= end_start:
                medien.aufkleben(bild, _mit_alpha(endkarte, _weich((t - end_start - 0.3) / 0.9)), end_pos)
            schwarz = 1.0          # keine Schwarzblende: das erste Bild zeigt gleich den Hook
            daten = np.asarray(bild, dtype=np.uint8)
            if schwarz < 0.999:
                daten = (daten.astype(np.float32) * schwarz).astype(np.uint8)
            proz.stdin.write(daten.tobytes())
        proz.stdin.close()
        fehler = proz.stderr.read().decode("utf-8", "replace")
        if proz.wait(timeout=120) != 0:
            raise RuntimeError(f"ffmpeg: {fehler[-400:]}")
    except Exception:
        proz.kill()
        raise
    return {"sekunden": round(dauer, 1), "bilder": n}


def als_bytes(post: dict) -> bytes:
    with tempfile.TemporaryDirectory() as ordner:
        ziel = os.path.join(ordner, "reel.mp4")
        erstelle(post, ziel)
        with open(ziel, "rb") as f:
            return f.read()
