"""
Reel-Video auf dem Server (1080x1920, 30 Bilder/s, etwa 15 Sekunden, MP4/H.264)

Ablauf: Sternenhimmel blendet auf, der Mond (echte Phase) leuchtet, die Texte des
Reels erscheinen nacheinander (Hook, Einblendungen), am Ende das Soraya-Zeichen mit
Schlusssatz und "Link in Bio". Die Texte stehen in der "sicheren Zone" (Instagram und
TikTok legen unten Beschriftung und Knoepfe ueber das Video).

Ton: eine ruhige, selbst erzeugte Klangflaeche (weiche Akkorde, ein heller Glockenton bei
jedem neuen Text). Sie ist eigens berechnet -- keine fremde Musik, keine Lizenzfragen. Auf
Instagram/TikTok kannst du sie beim Posten durch einen Trend-Sound ersetzen.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import medien

W, H, FPS = 1080, 1920, 30
VERSION = "reel-9"
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
        t = medien.ohne_emojis(t)
        if t and t not in zeilen:
            zeilen.append(t)
    if len(zeilen) < 2:   # aeltere Reels ohne Einblendungen: Ueberschrift und Unterzeile
        for t in (post.get("titel"), post.get("untertitel")):
            t = medien.ohne_emojis(t)
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
    # weicher dunkler Schein hinter der Schrift: bleibt auch ueber hellen Sternen/Nebel und nach der
    # Video-Kompression gut lesbar (feine Serifen der Cormorant werden sonst schnell matschig)
    alpha = ebene.getchannel("A").filter(ImageFilter.GaussianBlur(14 * m))
    schatten = Image.new("RGBA", ebene.size, (6, 3, 18, 0))
    schatten.putalpha(alpha.point(lambda v: min(255, int(v * 0.85))))
    schatten.alpha_composite(ebene)
    return schatten.resize((ebene.width // m, ebene.height // m), Image.LANCZOS), kaesten


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
    medien._cta(d, ebene, W, y - 100, True, post.get("sprache") or "de", m, "voll")
    return ebene.resize((W, H), Image.LANCZOS)


def _sternschnuppe(bild: Image.Image, start: tuple[float, float], winkel: float, fortschritt: float) -> None:
    """Eine Sternschnuppe: heller Kopf mit goldenem Schweif, fortschritt 0..1 (blendet ein und aus)."""
    if not 0 < fortschritt < 1:
        return
    d = ImageDraw.Draw(bild, "RGBA")
    weg, schweif = 520, 190
    dx, dy = math.cos(winkel), math.sin(winkel)
    kx, ky = start[0] + dx * weg * fortschritt, start[1] + dy * weg * fortschritt
    staerke = math.sin(math.pi * fortschritt)
    for i in range(14):
        a, b = i / 14, (i + 1) / 14
        alpha = int(200 * staerke * (1 - a) ** 1.6)
        d.line([(kx - dx * schweif * a, ky - dy * schweif * a), (kx - dx * schweif * b, ky - dy * schweif * b)],
               fill=(255, 236, 190, alpha), width=max(1, int(4 * (1 - a))))
    r = 3.2
    d.ellipse([kx - r, ky - r, kx + r, ky + r], fill=(255, 250, 230, int(255 * staerke)))


# Akkordfolgen (Frequenzen in Hz), ruhig und etwas geheimnisvoll; je Post eine andere
AKKORDE = [
    [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66), (164.81, 196.0, 246.94)],
    [(146.83, 220.0, 277.18), (164.81, 207.65, 246.94), (130.81, 196.0, 246.94), (146.83, 185.0, 220.0)],
    [(196.0, 246.94, 293.66), (164.81, 207.65, 246.94), (174.61, 220.0, 261.63), (196.0, 233.08, 293.66)],
]
GLOCKE = [880.0, 987.77, 1174.66, 1318.51, 1567.98]   # pentatonisch, passt zu jedem Akkord


def klang(dauer: float, einsaetze: list[float], seed: int = 1, rate: int = 48000) -> np.ndarray:
    """Stereo-Klangflaeche (int16, Form [n, 2]): Akkorde mit weichem Ein-/Ausblenden, Glocke je Einsatz."""
    n = int(dauer * rate)
    t = np.arange(n, dtype=np.float32) / rate
    folge = AKKORDE[seed % len(AKKORDE)]
    links, rechts = np.zeros(n, np.float32), np.zeros(n, np.float32)
    teil = dauer / len(folge)
    for i, akkord in enumerate(folge):
        a, b = max(0.0, i * teil - 1.2), min(dauer, (i + 1) * teil + 1.2)    # ueberlappend = weiche Wechsel
        s, e = int(a * rate), int(b * rate)
        lokal = t[s:e] - a
        huelle = np.sin(np.pi * np.clip(lokal / (b - a), 0, 1)) ** 2
        for k, f in enumerate(akkord):
            for verstimmt, seite in ((0.997, 0), (1.003, 1)):              # leicht verstimmt = breiter Klang
                ton = np.sin(2 * np.pi * f * verstimmt * lokal + k) + 0.25 * np.sin(2 * np.pi * f * 2 * verstimmt * lokal)
                (links if seite == 0 else rechts)[s:e] += ton * huelle * 0.07
    rnd = np.random.default_rng(seed)
    for j, start in enumerate(einsaetze):
        f = GLOCKE[int(rnd.integers(len(GLOCKE)))]
        s = int(start * rate)
        lokal = t[s:min(n, s + int(2.5 * rate))] - start
        glocke = (np.sin(2 * np.pi * f * lokal) + 0.3 * np.sin(2 * np.pi * f * 2.76 * lokal)) * np.exp(-lokal * 2.2) * 0.09
        schwenk = 0.35 if j % 2 else 0.65
        links[s:s + len(lokal)] += glocke * (1 - schwenk) * 2
        rechts[s:s + len(lokal)] += glocke * schwenk * 2
    gesamt = np.stack([links, rechts], axis=1)
    rampe = np.minimum(1, np.minimum(t / 1.2, (dauer - t) / 1.5))[:, None]   # sanft rein und raus
    gesamt *= np.clip(rampe, 0, 1)
    spitze = float(np.abs(gesamt).max()) or 1.0
    gesamt *= 0.28 / spitze                                                 # leise: etwa -11 dBFS Spitze
    return (gesamt * 32767).astype(np.int16)


# TikTok-Fassung: kurz (Hook + eine Zeile + kurze Endkarte, ~8-9 s, wird oefter ganz und wiederholt geschaut)
# und ohne eigenen Ton -- in der TikTok-App kommt ein Sound dazu, ohne dass die Klangflaeche mitspielt
TIKTOK_ZEILEN = 2
TIKTOK_ENDE = 1.8


def zeitplan(zeilen: list[str], ende_s: float = 3.2) -> tuple[list[tuple[float, float]], float, float]:
    """Start/Ende je Zeile, Beginn der Endkarte, Gesamtdauer (Sekunden)."""
    t, plan = 0.0, []                     # Hook ab dem ersten Bild (Vorschaubild, erste Sekunde)
    for i, z in enumerate(zeilen):
        dauer = max(2.4, min(4.2, 1.1 + 0.32 * len(z.split())))
        if i == 0:
            dauer += 0.4
        plan.append((t, t + dauer))
        t += dauer + 0.15
    ende = t + 0.1
    return plan, ende, ende + ende_s


def erstelle(post: dict, ziel: str, tiktok: bool = False) -> dict:
    """Rendert das Reel nach `ziel` (MP4). tiktok=True: kurze Fassung ohne Klangflaeche.
    Rueckgabe: {"sekunden", "bilder"}."""
    meta = post.get("meta") or {}
    seed = post.get("id") or 1
    zeilen, _ = texte(post)
    if tiktok:
        zeilen = zeilen[:TIKTOK_ZEILEN]
    plan, end_start, dauer = zeitplan(zeilen, TIKTOK_ENDE if tiktok else 3.2)
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
    # ruhige Sterne auf eigener, etwas hoeherer Ebene: sie wandern waehrend des Videos langsam nach oben
    DRIFT = 90
    sternebene = Image.new("RGBA", (W, H + DRIFT), (0, 0, 0, 0))
    d = ImageDraw.Draw(sternebene, "RGBA")
    for x, y, r, farbe, a in ruhig:
        for yy in (y, y + H) if y < DRIFT else (y,):        # oben wiederholen, damit unten nichts fehlt
            d.ellipse([x - r, yy - r, x + r, yy + r], fill=farbe + (int(a * 255),))
    schnuppen = [(1.4, (W * 0.18, 260), math.radians(28)), (max(4.0, end_start - 3.0), (W * 0.62, 180), math.radians(152))]
    oben = Image.new("RGBA", (W, H), (0, 0, 0, 0))                 # kleines Zeichen + Datumszeile
    z = medien.portal(2 * 110)
    s = 2 * 110 / 312
    gross = Image.new("RGBA", (W * 2, 640), (0, 0, 0, 0))
    gross.alpha_composite(z, (int(W - 256 * s), int(20 - 112 * s)))
    # gleicher Kopf wie auf den Bildern: Format (gold) und darunter Datum · Mondphase
    medien.kopf(ImageDraw.Draw(gross, "RGBA"), W, 2, True, akzent, st["label"],
                None if st["label"] else medien.datumszeile(meta), y=172)
    gross = gross.resize((W, 320), Image.LANCZOS)
    oben.alpha_composite(gross, (0, 230))
    oben, oben_pos = _zuschneiden(oben)
    mit_mond = meta.get("phase_index") is not None
    r = 200
    mond = medien.mond(r * 2, meta.get("phase_index"), meta.get("beleuchtung")) if mit_mond else None
    if mond is not None:
        mond = mond.resize((mond.width // 2, mond.height // 2), Image.LANCZOS)
    schein = medien.mond_schein(r, meta.get("phase_index"), meta.get("beleuchtung")) if mit_mond else None
    mond_y = 760
    karten = [_textkarte(z_, breite=W - 160, groesse=92 if i == 0 else 78, name="cormorant", farbe="#F6E3B4",
                         max_zeilen=4, akzent=akzent) for i, z_ in enumerate(zeilen)]
    text_mitte = 1270
    endkarte, end_pos = _zuschneiden(_endkarte(post))

    ffmpeg = ffmpeg_pfad()
    ton = os.path.join(os.path.dirname(os.path.abspath(ziel)) or ".", f".klang-{os.getpid()}-{seed}.raw")
    with open(ton, "wb") as f:
        if tiktok:      # Stille (eine Tonspur bleibt drin, manche Apps erwarten sie)
            f.write(np.zeros((int((dauer + 0.5) * 48000), 2), dtype=np.int16).tobytes())
        else:
            f.write(klang(dauer + 0.5, [max(0.0, s) for s, _ in plan] + [end_start], int(seed)).tobytes())
    befehl = [ffmpeg, "-y", "-loglevel", "error",
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
              "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", ton,
              "-shortest", "-map", "0:v", "-map", "1:a",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
              "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", ziel]
    proz = subprocess.Popen(befehl, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / FPS
            bild = grund.copy()
            versatz = int(DRIFT * t / dauer)
            bild.paste(sternebene.crop((0, versatz, W, versatz + H)), (0, 0), sternebene.crop((0, versatz, W, versatz + H)))
            dd = ImageDraw.Draw(bild, "RGBA")
            for k, (x, y, rr, farbe, a) in enumerate(funkelnd):      # goldene Sterne funkeln
                f = 0.55 + 0.45 * math.sin(t * (1.3 + (k % 5) * 0.37) + k * 1.7)
                yy = (y - versatz * 1.6) % H                         # naeher, daher etwas schneller
                dd.ellipse([x - rr, yy - rr, x + rr, yy + rr], fill=farbe + (int(a * f * 255),))
            for start_t, pos, winkel in schnuppen:
                _sternschnuppe(bild, pos, winkel, (t - start_t) / 0.9)
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
                        # sanft von unten herein, beim Ausblenden ein wenig nach oben
                        hub = 0 if start <= 0 else 26 * (1 - _weich((t - start) / 0.6))
                        hub -= 18 * (1 - raus)
                        medien.aufkleben(bild, _mit_alpha(k, raus),
                                         (W / 2 - karte.width / 2, text_mitte - karte.height / 2 + hub))
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
    finally:
        try:
            os.remove(ton)
        except OSError:
            pass
    return {"sekunden": round(dauer, 1), "bilder": n}


def als_bytes(post: dict, tiktok: bool = False) -> bytes:
    with tempfile.TemporaryDirectory() as ordner:
        ziel = os.path.join(ordner, "reel.mp4")
        erstelle(post, ziel, tiktok)
        with open(ziel, "rb") as f:
            return f.read()
