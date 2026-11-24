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
import motive

W, H, FPS = 1080, 1920, 30
VERSION = "reel-31"
EINBLENDEN, AUSBLENDEN = 0.45, 0.4
ERSTE_SEKUNDE = 1.0         # Bewegung im ersten Moment: hier entscheidet sich, ob jemand weiterwischt


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
    return zeilen[:13 if reel_format(post) in ("stopp", "woche") else 5], (sk.get("schluss") or "").strip()


def reel_format(post: dict) -> str | None:
    """Format des zweiten Reels (tagesplan.REEL2_FORMATE), sonst None."""
    meta = post.get("meta") or {}
    return meta.get("reel_format") if meta.get("reel_nr") == 2 else None


def _textkarte(text: str, *, breite: int, groesse: int, name: str, farbe: str, zeilenhoehe=1.15, max_zeilen=4,
               akzent=(233, 207, 156), gold: bool = False):
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
    # das wichtigste Wort (das laengste mit mind. 5 Buchstaben) leuchtet golden (reel-29: "lebendiger")
    woerter = [re.sub(r"[^\w]", "", w) for z in b["zeilen"] for w in z.split(" ")]
    kandidaten = [w for w in woerter if len(w) >= 5]
    gold_wort = max(kandidaten, key=len) if kandidaten and gold else ""
    gold_farbe = tuple(min(255, int(c * 1.08)) for c in akzent)
    for i, zeile in enumerate(b["zeilen"]):
        grund = kopf_h + b["g"] * 0.8 + i * b["g"] * b["zh"]
        breite_z = font.getlength(zeile) / m
        x = bw / 2 - breite_z / 2
        for w in zeile.split(" "):
            wb = font.getlength(w) / m
            treffer = gold_wort and re.sub(r"[^\w]", "", w) == gold_wort
            d.text((x * m, grund * m), w, font=font, fill=(gold_farbe if treffer else medien._rgb(farbe)) + (255,), anchor="ls")
            if treffer:
                gold_wort = ""                      # nur einmal
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


FOLGEN = {"de": "Folge Soraya – jeden Tag neu", "en": "Follow Soraya – new every day",
          "hu": "Kövesd Sorayát – minden nap valami új", "it": "Segui Soraya – novità ogni giorno"}


# TikTok: der Link in der Bio ist (unter 1000 Followern) nicht antippbar -> die Hauptaufforderung ist Folgen
FOLGEN_KNOPF = {"de": "Folge – morgen geht's weiter", "en": "Follow for tomorrow", "hu": "Kövess, holnap folytatjuk",
                "it": "Seguimi, domani si continua"}
# Reels haben keinen antippbaren Link -> unter "Folgen" der Name, unter dem man die App findet
PLAY = {"de": "Im Google Play Store: „Soraya Astro“", "en": "On Google Play: search “Soraya Astro”",
        "hu": "Keresd a Google Playen: „Soraya Astro”", "it": "Su Google Play: cerca “Soraya Astro”"}
SUCHEN = {"de": "Oder such: Soraya Astro Guide", "en": "Or search: Soraya Astro Guide",
          "hu": "Vagy keress rá: Soraya Astro Guide", "it": "Oppure cerca: Soraya Astro Guide"}


# Namen der Formate des zweiten Reels (tagesplan.REEL2_FORMATE) fuer den Ausblick "Heute Abend / Morgen: …"
REEL2_TITEL = {
    "woche":   {"de": "Deine Woche in einem Wort", "en": "Your week in one word", "hu": "A heted egy szóban", "it": "La tua settimana in una parola"},
    "glueck":  {"de": "Die 3 Glückspilze des Tages", "en": "The 3 lucky signs of the day", "hu": "A nap 3 szerencsése", "it": "I 3 fortunati del giorno"},
    "ritual":  {"de": "Ein kleines Ritual für 3 Zeichen", "en": "A little ritual for 3 signs", "hu": "Esti rituálé három jegynek", "it": "Un piccolo rituale per 3 segni"},
    "element": {"de": "Der Elemente-Check", "en": "The element check", "hu": "Az elemek ereje", "it": "La forza degli elementi"},
    "stopp":   {"de": "Alle 12 Zeichen: Stopp bei deinem!", "en": "All 12 signs: stop at yours!", "hu": "Mind a 12 jegy: állj meg a tiédnél!", "it": "Tutti i 12 segni: fermati al tuo!"},
    "karte":   {"de": "Wähl eine Karte", "en": "Pick a card", "hu": "Válassz egy kártyát", "it": "Scegli una carta"},
    "dreier":  {"de": "3 Zeichen, eine Botschaft", "en": "3 signs, one message", "hu": "Három jegy üzenete", "it": "Tre segni, un messaggio"},
}
AUSBLICK = {"heute": {"de": "Heute Abend", "en": "Tonight", "hu": "Ma este", "it": "Stasera"},
            "morgen": {"de": "Morgen", "en": "Tomorrow", "hu": "Holnap", "it": "Domani"}}
AUSBLICK_FOLGEN = {"de": "folge, damit du es nicht verpasst", "en": "follow so you don't miss it",
                   "hu": "kövess, hogy le ne maradj", "it": "seguimi per non perderlo"}


def ausblick(post: dict) -> str:
    """Was als naechstes kommt: beim 1. Reel das Format des 2. Reels heute Abend, beim 2. Reel das von morgen.
    Gibt "" zurueck, wenn kein Datum bekannt ist."""
    from datetime import date as _date, timedelta as _td
    import tagesplan
    sp = (post.get("sprache") or "en")[:2]
    tag = post.get("geplant_fuer")
    if isinstance(tag, str):
        try:
            tag = _date.fromisoformat(tag[:10])
        except ValueError:
            return ""
    if not isinstance(tag, _date):
        return ""
    zweites = (post.get("meta") or {}).get("reel_nr") == 2
    ziel = tag + _td(days=1) if zweites else tag
    fmt = tagesplan.REEL2_FORMATE.get(ziel.weekday(), "dreier")
    if tagesplan.app_funktion(ziel):
        fmt = "dreier"
    wann = AUSBLICK["morgen" if zweites else "heute"].get(sp, AUSBLICK["morgen" if zweites else "heute"]["en"])
    titel = REEL2_TITEL[fmt].get(sp, REEL2_TITEL[fmt]["en"])
    return f"{wann}: {titel}"


def _endkarte(post: dict, tiktok: bool = False) -> Image.Image:
    """Schlussbild: grosses Soraya-Zeichen, Marke, Schlusssatz, Link-Knopf (als Ebene).
    tiktok=True: goldener Folgen-Knopf statt „Link in Bio“, darunter der Name zum Suchen."""
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
    sp = (post.get("sprache") or "en")[:2]
    # "Link in Bio"-Knopf, gleiche Form wie auf den Bildern (TikTok: "Folge fuer morgen")
    medien._cta(d, ebene, W, y - 100, True, sp, m, "voll", FOLGEN_KNOPF.get(sp, FOLGEN_KNOPF["en"]) if tiktok else None)
    # darunter: folgen mit Grund (Ausblick auf das naechste Format) -- aus Zuschauern werden Follower (reel-27, 24.11.:
    # 717.000 Aufrufe, aber nur ~1.000 Follower); bei TikTok der Name zum Suchen
    try:
        vorschau = "" if tiktok else ausblick(post)
    except Exception:  # noqa: BLE001
        vorschau = ""
    if vorschau:
        unten_text = f"{vorschau} – {AUSBLICK_FOLGEN.get(sp, AUSBLICK_FOLGEN['en'])}"
    else:
        unten = (SUCHEN if tiktok else FOLGEN)
        unten_text = unten.get(sp, unten["en"])
    f = medien.messe_text(unten_text, breite=W - 200, groesse=40 if vorschau else 32,
                          name="inter600" if vorschau else "inter500", zeilenhoehe=1.3, max_zeilen=2, min_groesse=26)
    medien.zeichne_text(d, f, W / 2, y + 78 + 34, "#E9CF9C" if vorschau else "#CDB98C", m)
    if not tiktok:
        g = medien.messe_text(PLAY.get(sp, PLAY["en"]), breite=W - 240, groesse=28,
                              name="inter400", zeilenhoehe=1.3, max_zeilen=2, min_groesse=22)
        medien.zeichne_text(d, g, W / 2, y + 78 + 34 + f["hoehe"] + 22, "#8F83AD", m)
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


# ---------------------------------------------------------------------------
# Bewegte Bildideen (reel-10): Sternbild zeichnet sich, Umlaufbahn um den Mond, Goldstaub,
# Lichtschimmer ueber dem Hook, sanftes Aufleuchten bei jeder neuen Zeile
# ---------------------------------------------------------------------------
# vereinfachte Sternbilder (x, y in 0..1) und ihre Linien, Reihenfolge wie medien.ZEICHEN_GLYPHE
STERNBILDER = [
    ([(0.1, 0.55), (0.45, 0.38), (0.7, 0.4), (0.88, 0.55)], [(0, 1), (1, 2), (2, 3)]),
    ([(0.45, 0.78), (0.5, 0.6), (0.42, 0.5), (0.35, 0.42), (0.1, 0.22), (0.58, 0.5), (0.66, 0.42), (0.9, 0.18)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7)]),
    ([(0.3, 0.1), (0.28, 0.35), (0.25, 0.6), (0.2, 0.9), (0.6, 0.12), (0.62, 0.38), (0.66, 0.62), (0.72, 0.9)],
     [(0, 1), (1, 2), (2, 3), (0, 4), (4, 5), (5, 6), (6, 7), (1, 5)]),
    ([(0.5, 0.5), (0.45, 0.12), (0.18, 0.86), (0.82, 0.84)], [(1, 0), (0, 2), (0, 3)]),
    ([(0.2, 0.3), (0.28, 0.14), (0.42, 0.12), (0.46, 0.3), (0.36, 0.45), (0.4, 0.6), (0.76, 0.55), (0.88, 0.76), (0.6, 0.76)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 5)]),
    ([(0.12, 0.3), (0.3, 0.4), (0.46, 0.45), (0.62, 0.4), (0.8, 0.24), (0.52, 0.66), (0.4, 0.88), (0.72, 0.82)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (2, 5), (5, 6), (5, 7)]),
    ([(0.5, 0.14), (0.25, 0.45), (0.75, 0.45), (0.2, 0.82), (0.8, 0.76)], [(0, 1), (0, 2), (1, 2), (1, 3), (2, 4)]),
    ([(0.08, 0.2), (0.18, 0.3), (0.1, 0.44), (0.3, 0.36), (0.4, 0.46), (0.48, 0.6), (0.55, 0.74), (0.68, 0.84),
      (0.82, 0.82), (0.9, 0.7), (0.84, 0.6)], [(0, 1), (2, 1), (1, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10)]),
    ([(0.18, 0.52), (0.34, 0.4), (0.5, 0.28), (0.62, 0.42), (0.82, 0.34), (0.8, 0.62), (0.56, 0.68), (0.3, 0.72)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 0), (1, 3), (3, 6)]),
    ([(0.1, 0.3), (0.3, 0.46), (0.5, 0.72), (0.66, 0.62), (0.9, 0.24), (0.7, 0.34), (0.4, 0.3)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 0)]),
    ([(0.08, 0.3), (0.28, 0.24), (0.44, 0.4), (0.6, 0.34), (0.76, 0.5), (0.92, 0.44), (0.56, 0.66), (0.42, 0.86)],
     [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (3, 6), (6, 7)]),
    ([(0.06, 0.14), (0.18, 0.08), (0.22, 0.2), (0.32, 0.46), (0.5, 0.86), (0.68, 0.58), (0.86, 0.5), (0.94, 0.38), (0.84, 0.32)],
     [(0, 1), (1, 2), (2, 0), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 6)]),
]


def welches_zeichen(post: dict, st: dict) -> int | None:
    """Sternbild fuers Reel: Ereignis-Zeichen, sonst Zeichen am Anfang des Hooks, sonst das Mondzeichen."""
    if st.get("zeichen") is not None:
        return st["zeichen"]
    meta = post.get("meta") or {}
    for text in [(post.get("skript") or {}).get("hook"), post.get("titel"), meta.get("mond_zeichen")]:
        i = medien.zeichen_aus_text(text)
        if i is not None:
            return i
    return None


def _sternbild(d: ImageDraw.ImageDraw, idx: int, kasten: tuple, t: float, sichtbar: float, farbe, start=0.35, laenge=2.6) -> None:
    """Zeichnet das Sternbild Linie fuer Linie (start..start+laenge), danach funkeln die Sterne leise."""
    if sichtbar <= 0:
        return
    punkte, linien = STERNBILDER[idx]
    x0, y0, bw, bh = kasten
    p = [(x0 + x * bw, y0 + y * bh) for x, y in punkte]
    fortschritt = (t - start) / laenge * len(linien)
    erreicht = set()
    for k, (a, b) in enumerate(linien):
        f = min(1.0, max(0.0, fortschritt - k))
        if f <= 0:
            break
        (ax, ay), (bx, by) = p[a], p[b]
        d.line([(ax, ay), (ax + (bx - ax) * f, ay + (by - ay) * f)], fill=farbe + (int(165 * sichtbar),), width=3)
        erreicht.add(a)
        if f >= 1:
            erreicht.add(b)
    for i, (x, y) in enumerate(p):
        if i not in erreicht:
            continue
        funkeln = 0.75 + 0.25 * math.sin(t * 2.1 + i * 1.3)
        for r, a in ((24, 0.08), (12, 0.22), (5, 1.0)):
            d.ellipse([x - r, y - r, x + r, y + r], fill=farbe + (int(255 * a * funkeln * sichtbar),))


ELEMENT_FARBE = {0: (244, 176, 96), 1: (156, 206, 150), 2: (206, 218, 238), 3: (128, 178, 236)}   # Feuer, Erde, Luft, Wasser


def drei_zeichen(post: dict) -> list[int]:
    """Zweites Reel = Drei-Zeichen-Check: die drei Zeichen vor dem Doppelpunkt im Hook ("Stier, Waage, Krebs: ...")."""
    if (post.get("meta") or {}).get("reel_nr") != 2:
        return []
    hook = (post.get("skript") or {}).get("hook") or ""
    if ":" not in hook:
        return []
    teile = [t.strip() for t in re.split(r",|\bés\b|\bund\b|\band\b|\be\b", hook.split(":", 1)[0]) if t.strip()]
    idx = [medien.zeichen_aus_text(t) for t in teile]
    return idx if len(idx) == 3 and None not in idx and len(set(idx)) == 3 else []


def _hell(farbe, f=0.45):
    return tuple(int(c + (255 - c) * f) for c in farbe)


def _medaillon(i: int, gr: int, r: float, glyph: float, name: str | None = None) -> tuple:
    """Sternzeichen-Medaillon (reel-26, "optisches Update"): Verlauf in der Element-Farbe, goldener Aussenring mit
    zwoelf Lichtpunkten wie ein Astrolabium, feiner Innenring, leuchtendes Symbol. Rueckgabe (normal, leuchtend)."""
    from PIL import ImageFilter
    farbe = ELEMENT_FARBE[i % 4]
    gold = (233, 207, 156)
    m = 2
    gr = max(gr, int(r * 4.4))                                   # Platz fuer den weichen Schein (sonst eckige Kante)
    hoehe = gr + (int(r * 0.9) if name else 0)
    ebene = Image.new("RGBA", (gr * m, hoehe * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(ebene)
    c = gr / 2
    for k in range(14, 0, -1):                                   # weicher Verlauf von innen nach aussen
        rr = r * k / 14
        a = int(10 + 40 * (k / 14) ** 2)
        d.ellipse([(c - rr) * m, (c - rr) * m, (c + rr) * m, (c + rr) * m], fill=tuple(int(x * 0.45) for x in farbe) + (a,))
    d.ellipse([(c - r) * m, (c - r) * m, (c + r) * m, (c + r) * m], outline=gold + (235,), width=int(3 * m))
    ri = r - max(7, r * 0.09)
    d.ellipse([(c - ri) * m, (c - ri) * m, (c + ri) * m, (c + ri) * m], outline=farbe + (150,), width=int(1.5 * m))
    for k in range(12):                                          # Lichtpunkte auf dem Ring
        w = math.radians(k * 30 - 90)
        x, y = c + r * math.cos(w), c + r * math.sin(w)
        pr = (3.2 if k % 3 == 0 else 2.0) * (r / 100)
        d.ellipse([(x - pr) * m, (y - pr) * m, (x + pr) * m, (y + pr) * m], fill=_hell(gold, 0.5) + (255,))
    # Symbol mit eigenem Schein
    schein = Image.new("RGBA", ebene.size, (0, 0, 0, 0))
    ImageDraw.Draw(schein).text((c * m, c * m + glyph * 0.03 * m), medien.ZEICHEN_GLYPHE[i],
                                font=medien.schrift("zeichen", glyph * m), fill=farbe + (210,), anchor="mm")
    ebene.alpha_composite(schein.filter(ImageFilter.GaussianBlur(glyph * 0.09 * m)))
    d = ImageDraw.Draw(ebene)
    d.text((c * m, c * m + glyph * 0.03 * m), medien.ZEICHEN_GLYPHE[i], font=medien.schrift("zeichen", glyph * m),
           fill=_hell(farbe, 0.35) + (255,), anchor="mm")
    if name:
        medien.gesperrt(d, name.upper(), c * m, (c + r + 58) * m, medien.schrift("cinzel", 36 * m), 5 * m, _hell(farbe, 0.2) + (255,))
    ebene = ebene.resize((gr, hoehe), Image.LANCZOS)
    glow = Image.new("RGBA", ebene.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([c - r - r * 0.3, c - r - r * 0.3, c + r + r * 0.3, c + r + r * 0.3], fill=farbe + (150,))
    hell = glow.filter(ImageFilter.GaussianBlur(r * 0.33))
    hell.alpha_composite(ebene)
    return ebene, hell


def _umlauf(gr: int, r: float, farbe) -> Image.Image:
    """Punkt-Ring um das aktive Zeichen (dreht sich im Video langsam)."""
    m = 2
    ebene = Image.new("RGBA", (gr * m, gr * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(ebene)
    c = gr / 2
    for k in range(36):
        w = math.radians(k * 10)
        x, y = c + r * math.cos(w), c + r * math.sin(w)
        pr = 2.6 if k % 6 == 0 else 1.3
        a = 255 if k % 6 == 0 else 150
        d.ellipse([(x - pr) * m, (y - pr) * m, (x + pr) * m, (y + pr) * m], fill=_hell(farbe, 0.55) + (a,))
    return ebene.resize((gr, gr), Image.LANCZOS)


def _funke(d: ImageDraw.ImageDraw, x: float, y: float, gr: float, farbe, alpha: float) -> None:
    """Kleiner vierzackiger Stern."""
    if alpha <= 0.02:
        return
    f = farbe + (int(255 * alpha),)
    d.polygon([(x, y - gr), (x + gr * 0.25, y - gr * 0.25), (x + gr, y), (x + gr * 0.25, y + gr * 0.25), (x, y + gr),
               (x - gr * 0.25, y + gr * 0.25), (x - gr, y), (x - gr * 0.25, y - gr * 0.25)], fill=f)


def _aktiv_schmuck(bild: Image.Image, ring: Image.Image, x: float, y: float, t: float, r: float, farbe, sichtbar: float) -> None:
    """Drehender Punkt-Ring und drei kreisende Funken um das gerade aktive Zeichen."""
    gedreht = ring.rotate(-t * 22, resample=Image.BILINEAR)
    medien.aufkleben(bild, _mit_alpha(gedreht, 0.9 * sichtbar), (x - gedreht.width / 2, y - gedreht.height / 2))
    d = ImageDraw.Draw(bild, "RGBA")
    for k in range(3):
        w = t * 1.3 + k * 2.094
        fx, fy = x + (r + 26) * math.cos(w), y + (r + 26) * math.sin(w)
        _funke(d, fx, fy, 9 + 3 * math.sin(t * 4 + k), _hell(farbe, 0.6), (0.6 + 0.4 * math.sin(t * 5 + k * 1.7)) * sichtbar)


def _dreier_ebenen(drei: list[int], sprache: str) -> dict:
    """Je Zeichen ein Medaillon (Symbol in der Element-Farbe, Name darunter) -- normal, leuchtend, Ring."""
    spalte = {"de": 0, "en": 1, "hu": 2, "it": 3}.get(sprache, 1)
    out = {}
    for i in drei:
        normal, hell = _medaillon(i, 300, 104, 112, medien.ZEICHEN_NAMEN[i][spalte])
        out[i] = (normal, hell, _umlauf(320, 132, ELEMENT_FARBE[i % 4]))
    return out


def _dreier_malen(bild: Image.Image, reihe: dict, drei: list[int], aktiv, t: float, sichtbar: float) -> None:
    """Drei Medaillons nebeneinander; das Zeichen der laufenden Zeile leuchtet und wird groesser, die anderen treten zurueck."""
    y = 700
    for k, i in enumerate(drei):
        x = W / 2 + (k - 1) * 330
        normal, hell, ring = reihe[i]
        if aktiv is None:
            puls = 0.9 + 0.1 * math.sin(t * 1.6 + k * 1.2)
            ebene, skala, alpha = normal, 1.0, puls
        elif aktiv == i:
            ebene, skala, alpha = hell, 1.16, 1.0
        else:
            ebene, skala, alpha = normal, 0.9, 0.38
        if abs(skala - 1) > 0.01:
            ebene = ebene.resize((int(ebene.width * skala), int(ebene.height * skala)), Image.BILINEAR)
        if aktiv == i:
            _aktiv_schmuck(bild, ring, x, y, t, 104 * skala, ELEMENT_FARBE[i % 4], sichtbar)
        medien.aufkleben(bild, _mit_alpha(ebene, alpha * sichtbar), (x - ebene.width / 2, y - ebene.width / 2))


ELEMENT_NAMEN = {0: ("FEUER", "FIRE", "TŰZ", "FUOCO"), 1: ("ERDE", "EARTH", "FÖLD", "TERRA"),
                 2: ("LUFT", "AIR", "LEVEGŐ", "ARIA"), 3: ("WASSER", "WATER", "VÍZ", "ACQUA")}
KARTE_WORT = {"de": "KARTE", "en": "CARD", "hu": "KÁRTYA", "it": "CARTA"}


def _spalte(sprache: str) -> int:
    return {"de": 0, "en": 1, "hu": 2, "it": 3}.get(sprache, 1)


def _dreier_zusatz(fmt: str | None, drei: list[int], sprache: str) -> Image.Image | None:
    """Kleine feste Zugabe zur Dreier-Reihe: Platz 3/2/1 (Glückspilze) oder der Name des Elements."""
    if fmt != "element":
        return None
    m = 2
    ebene = Image.new("RGBA", (W * m, 260 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(ebene)
    if fmt == "element":
        farbe = ELEMENT_FARBE[drei[0] % 4]
        medien.gesperrt(d, ELEMENT_NAMEN[drei[0] % 4][_spalte(sprache)], W * m / 2, 150 * m,
                        medien.schrift("cinzel", 50 * m), 16 * m, farbe + (255,))
        d.line([(W * m / 2 - 150 * m, 178 * m), (W * m / 2 + 150 * m, 178 * m)], fill=farbe + (120,), width=2 * m)
    else:
        for k, platz in enumerate(("3", "2", "1")):
            x, y, r = (W / 2 + (k - 1) * 330) * m, 200 * m, 34 * m
            d.ellipse([x - r, y - r, x + r, y + r], fill=(30, 22, 52, 230), outline=(233, 207, 156, 255), width=3 * m)
            d.text((x, y + 2 * m), platz, font=medien.schrift("cinzel", 40 * m), fill=(246, 227, 180, 255), anchor="mm")
    return ebene.resize((W, 260), Image.LANCZOS)


PLATZ_TEXT = {"de": "PLATZ {n}", "en": "NO. {n}", "hu": "{n}. HELY", "it": "{n}° POSTO"}


def _platz_ebenen(sprache: str) -> dict:
    """Glückspilze: Platz-Schild, das erst ueber dem gerade leuchtenden Zeichen erscheint (Platz 3 -> 2 -> 1)."""
    out = {}
    m = 2
    for k, n in enumerate((3, 2, 1)):
        text = PLATZ_TEXT.get(sprache, PLATZ_TEXT["en"]).format(n=n)
        ebene = Image.new("RGBA", (320 * m, 90 * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(ebene)
        erster = n == 1
        d.rounded_rectangle([10 * m, 12 * m, 310 * m, 78 * m], radius=33 * m,
                            fill=(233, 207, 156, 255) if erster else (30, 22, 52, 235),
                            outline=(246, 227, 180, 255), width=3 * m)
        medien.gesperrt(d, text, 160 * m, 58 * m, medien.schrift("cinzel", 34 * m), 5 * m,
                        (60, 40, 20, 255) if erster else (246, 227, 180, 255))
        out[k] = ebene.resize((320, 90), Image.LANCZOS)
    return out


def _zwoelf_ebenen(gr: int = 180, r: float = 66, glyph: float = 74) -> dict:
    """Alle zwoelf Zeichen als kleine Medaillons (normal, leuchtend, Ring) fuer Stopp und Wochen-Rad."""
    return {i: _medaillon(i, gr, r, glyph) + (_umlauf(int(r * 2 + 70), r + 22, ELEMENT_FARBE[i % 4]),) for i in range(12)}


def _zwoelf_malen(bild: Image.Image, ebenen: dict, aktiv, t: float, sichtbar: float) -> None:
    """4 x 3 Raster; das laufende Zeichen leuchtet gross, die anderen treten zurueck. Ohne aktives Zeichen
    laeuft ein Licht durch alle zwoelf (Hook: „gleich kommt deins“)."""
    lauf = int(t / 0.12) % 12 if aktiv is None else None
    for i in range(12):
        x = W / 2 + (i % 4 - 1.5) * 225
        y = 530 + (i // 4) * 185
        normal, hell, ring = ebenen[i]
        if aktiv is None:
            ebene, skala, alpha = (hell, 1.08, 1.0) if i == lauf else (normal, 1.0, 0.75)
        elif aktiv == i:
            ebene, skala, alpha = hell, 1.35, 1.0
        else:
            ebene, skala, alpha = normal, 0.88, 0.3
        if abs(skala - 1) > 0.01:
            ebene = ebene.resize((int(ebene.width * skala), int(ebene.height * skala)), Image.BILINEAR)
        if aktiv == i:
            _aktiv_schmuck(bild, ring, x, y, t, 66 * skala, ELEMENT_FARBE[i % 4], sichtbar)
        medien.aufkleben(bild, _mit_alpha(ebene, alpha * sichtbar), (x - ebene.width / 2, y - ebene.height / 2))


RAD_MITTE, RAD_R = (W / 2, 720), 260


def _rad_winkel(plan: list, zeichen_je_zeile: list, t: float) -> float:
    """Drehung des Rads (Grad): im Hook langsames Kreisen, dann dreht sich das Zeichen der laufenden Zeile nach oben."""
    ziele = [(a, -zeichen_je_zeile[nr] * 30.0) for nr, (a, _b) in enumerate(plan) if nr and zeichen_je_zeile[nr] is not None]
    if not ziele or t < ziele[0][0]:
        return t * 18.0
    vorher = ziele[0][0] * 18.0
    for k, (a, ziel) in enumerate(ziele):
        if t < a:
            break
        start = vorher if k == 0 else ziele[k - 1][1]
        diff = (ziel - start + 180) % 360 - 180                    # kuerzester Weg
        wert = start + diff * _weich((t - a) / 0.45)
        vorher = wert
    return vorher


def _rad_malen(bild: Image.Image, ebenen: dict, gross: dict, plan: list, zeichen_je_zeile: list, t: float, sichtbar: float,
               namen: dict | None = None) -> None:
    """„Deine Woche in einem Wort“: zwoelf Zeichen im Kreis; das Rad dreht das aktuelle Zeichen nach oben unter den
    goldenen Stern, in der Mitte leuchtet es gross."""
    cx, cy = RAD_MITTE
    winkel = _rad_winkel(plan, zeichen_je_zeile, t)
    aktiv = next((zeichen_je_zeile[nr] for nr, (a_, b_) in enumerate(plan) if nr and a_ - 0.05 <= t <= b_ + 0.05), None)
    d = ImageDraw.Draw(bild, "RGBA")
    gold = (233, 207, 156)
    d.ellipse([cx - RAD_R, cy - RAD_R, cx + RAD_R, cy + RAD_R], outline=gold + (int(70 * sichtbar),), width=2)
    d.ellipse([cx - RAD_R + 95, cy - RAD_R + 95, cx + RAD_R - 95, cy + RAD_R - 95], outline=gold + (int(40 * sichtbar),), width=1)
    for i in range(12):
        w = math.radians(winkel + i * 30 - 90)
        x, y = cx + RAD_R * math.cos(w), cy + RAD_R * math.sin(w)
        normal, hell, ring = ebenen[i]
        oben = abs(((winkel + i * 30) + 180) % 360 - 180) < 8
        if aktiv is not None and i == aktiv and oben:
            ebene, alpha = hell, 1.0
        else:
            ebene, alpha = normal, 0.55 if aktiv is not None else 0.85
        medien.aufkleben(bild, _mit_alpha(ebene, alpha * sichtbar), (x - ebene.width / 2, y - ebene.height / 2))
    # goldener Zeiger oben
    y0 = cy - RAD_R + 62                                           # goldener Zeiger innen, zeigt auf das obere Zeichen
    d.polygon([(cx - 11, y0 + 14), (cx + 11, y0 + 14), (cx, y0 - 4)], fill=gold + (int(230 * sichtbar),))
    _funke(d, cx, y0 + 30, 7 + 2 * math.sin(t * 3), gold, 0.8 * sichtbar)
    if aktiv is not None:                                          # Mitte: das aktuelle Zeichen gross
        start = next(a_ for nr, (a_, b_) in enumerate(plan) if nr and a_ - 0.05 <= t <= b_ + 0.05)
        auf = _weich((t - start) / 0.35)
        normal, hell, ring = gross[aktiv]
        _aktiv_schmuck(bild, ring, cx, cy, t, 100, ELEMENT_FARBE[aktiv % 4], sichtbar * auf)
        medien.aufkleben(bild, _mit_alpha(hell, sichtbar * auf), (cx - hell.width / 2, cy - hell.height / 2))
        if namen and aktiv in namen:
            n = namen[aktiv]
            medien.aufkleben(bild, _mit_alpha(n, sichtbar * auf), (cx - n.width / 2, cy + 118))
    else:                                                          # Hook: Portal-Licht in der Mitte
        glimm = 0.5 + 0.5 * math.sin(t * 2.2)
        _funke(d, cx, cy, 34 + 6 * glimm, gold, (0.55 + 0.35 * glimm) * sichtbar)


def _karten_ebenen(sprache: str) -> dict:
    """Drei Karten fuer „Wähl eine Karte“: Rueckseite (verdeckt, Sternenmuster) und Vorderseite (aufgedeckt, hell)."""
    m, bw, bh = 2, 250, 370
    wort = KARTE_WORT.get(sprache, "CARD")
    out = {}
    for k in range(3):
        rueck = Image.new("RGBA", (bw * m, bh * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(rueck)
        d.rounded_rectangle([0, 0, bw * m - 1, bh * m - 1], radius=22 * m, fill=(34, 24, 62, 255), outline=(233, 207, 156, 255), width=4 * m)
        d.rounded_rectangle([14 * m, 14 * m, (bw - 14) * m, (bh - 14) * m], radius=14 * m, outline=(233, 207, 156, 110), width=2 * m)
        rnd = np.random.default_rng(11 + k)
        for _ in range(26):
            x, y = rnd.uniform(30, bw - 30) * m, rnd.uniform(30, bh - 30) * m
            r = rnd.uniform(1.5, 3.5) * m
            d.ellipse([x - r, y - r, x + r, y + r], fill=(233, 207, 156, int(rnd.uniform(90, 220))))
        d.text((bw * m / 2, bh * m / 2), str(k + 1), font=medien.schrift("cinzel", 150 * m), fill=(246, 227, 180, 255), anchor="mm")
        vorn = Image.new("RGBA", (bw * m, bh * m), (0, 0, 0, 0))
        d = ImageDraw.Draw(vorn)
        d.rounded_rectangle([0, 0, bw * m - 1, bh * m - 1], radius=22 * m, fill=(246, 227, 180, 255), outline=(255, 244, 214, 255), width=4 * m)
        d.rounded_rectangle([14 * m, 14 * m, (bw - 14) * m, (bh - 14) * m], radius=14 * m, outline=(160, 120, 60, 160), width=2 * m)
        medien.gesperrt(d, wort, bw * m / 2, 70 * m, medien.schrift("cinzel", 28 * m), 6 * m, (120, 86, 40, 255))
        d.text((bw * m / 2, bh * m / 2 + 10 * m), str(k + 1), font=medien.schrift("cinzel", 150 * m), fill=(96, 64, 30, 255), anchor="mm")
        sx, sy, sr = bw * m / 2, (bh - 62) * m, 16 * m
        d.polygon([(sx, sy - sr), (sx + sr * 0.3, sy - sr * 0.3), (sx + sr, sy), (sx + sr * 0.3, sy + sr * 0.3), (sx, sy + sr),
                   (sx - sr * 0.3, sy + sr * 0.3), (sx - sr, sy), (sx - sr * 0.3, sy - sr * 0.3)], fill=(160, 120, 60, 255))
        out[k] = (rueck.resize((bw, bh), Image.LANCZOS), vorn.resize((bw, bh), Image.LANCZOS))
    return out


def _karten_malen(bild: Image.Image, karten: dict, plan: list, t: float, sichtbar: float) -> None:
    """Erst drei verdeckte, leise schwebende Karten (Zeit zum Waehlen); mit jeder Zeile dreht sich eine Karte um."""
    for k in range(3):
        x = W / 2 + (k - 1) * 300
        y = 700 + 12 * math.sin(t * 1.5 + k * 2.1)
        rueck, vorn = karten[k]
        start = plan[k + 1][0] if k + 1 < len(plan) else 1e9
        p = min(1.0, max(0.0, (t - start) / 0.55))
        breite = abs(math.cos(math.pi * p))
        seite = vorn if p >= 0.5 else rueck
        laufend = k + 1 < len(plan) and plan[k + 1][0] - 0.2 <= t <= plan[k + 1][1] + 0.1
        if p <= 0:                                # noch verdeckt
            alpha, skala = 1.0, 1.0
        elif laufend:
            alpha, skala = 1.0, 1.1
        else:
            alpha, skala = 0.5, 0.94
        w_ = max(2, int(seite.width * skala * max(breite, 0.02)))
        h_ = int(seite.height * skala)
        e = seite.resize((w_, h_), Image.BILINEAR)
        medien.aufkleben(bild, _mit_alpha(e, alpha * sichtbar), (x - w_ / 2, y - h_ / 2))


# ---------------------------------------------------------------------------
# Farbwelten und bewegte Szenen (reel-28): jedes Reel bekommt je nach Zeichen/Format eine eigene Welt
# ---------------------------------------------------------------------------
WELT_ELEMENT = {0: "feuer", 1: "erde", 2: "luft", 3: "wasser"}
SZENE_FARBEN = {   # Farben der bewegten Szene je Welt (zwei Toene)
    "feuer": ((255, 140, 60), (255, 70, 90)), "erde": ((150, 210, 120), (230, 200, 120)),
    "luft": ((170, 190, 255), (240, 200, 255)), "wasser": ((60, 220, 210), (90, 150, 255)),
    "mitternacht": ((150, 140, 255), (220, 220, 255)), "gold": ((255, 200, 110), (255, 150, 90)),
    "rose": ((255, 130, 180), (200, 120, 255)), "amethyst": ((170, 110, 255), (255, 140, 210)),
    "nacht": ((130, 100, 220), (210, 120, 190)),
}
FORMAT_WELT = {"woche": ("amethyst", "galaxie"), "stopp": ("mitternacht", "polarlicht"), "karte": ("rose", "nebel"),
               "glueck": ("gold", "staub"), "ritual": ("gold", "nebel")}
SZENEN = ("nebel", "polarlicht", "galaxie", "staub")


def welt(post: dict, st: dict, drei: list[int]) -> tuple[str, str]:
    """(Farbwelt, Szene) des Reels: Format des 2. Reels, Vollmond/Neumond, Element des Zeichens, Liebe -- sonst wie das Bild."""
    meta = post.get("meta") or {}
    thema = meta.get("thema") or ""
    seed = int(post.get("id") or 0)
    fmt = reel_format(post)
    if fmt in FORMAT_WELT:
        return FORMAT_WELT[fmt]
    if "Vollmond" in thema or "Neumond" in thema:
        return "mitternacht", "polarlicht" if "Vollmond" in thema else "nebel"
    if thema == "Liebe & Beziehung":
        return "rose", "nebel"
    zeichen = drei[0] if drei else medien.zeichen_aus_text((post.get("skript") or {}).get("hook") or "")
    if fmt == "element" and drei:
        zeichen = drei[0]
    if zeichen is not None:
        return WELT_ELEMENT[zeichen % 4], SZENEN[(seed + zeichen) % len(SZENEN)]
    return st["palette"], SZENEN[seed % len(SZENEN)]


def _strahlen(farbe, gr: int = 1000) -> Image.Image:
    """Weicher Kranz aus Lichtstrahlen (dreht sich langsam hinter dem Motiv)."""
    from PIL import ImageFilter
    b = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    c = gr / 2
    for k in range(18):
        w = math.radians(k * 20)
        breite = math.radians(3.2 if k % 2 else 5.5)
        lang = c * (0.95 if k % 2 else 0.8)
        d.polygon([(c, c), (c + lang * math.cos(w - breite), c + lang * math.sin(w - breite)),
                   (c + lang * math.cos(w + breite), c + lang * math.sin(w + breite))], fill=farbe + (70 if k % 2 else 110,))
    maske = Image.new("L", (gr, gr), 0)
    ImageDraw.Draw(maske).ellipse([gr * 0.05, gr * 0.05, gr * 0.95, gr * 0.95], fill=255)
    maske = maske.filter(ImageFilter.GaussianBlur(gr * 0.12))
    b.putalpha(Image.fromarray((np.asarray(b.getchannel("A"), np.float32) * np.asarray(maske, np.float32) / 255).astype(np.uint8)))
    return b.filter(ImageFilter.GaussianBlur(10))


def _schleier(farbe, gr: int = 900) -> Image.Image:
    """Grosser weicher Lichtfleck (Light Leak), zieht langsam durchs Bild."""
    from PIL import ImageFilter
    b = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    ImageDraw.Draw(b).ellipse([gr * 0.2, gr * 0.3, gr * 0.8, gr * 0.7], fill=farbe + (110,))
    return b.filter(ImageFilter.GaussianBlur(gr * 0.13))


AKZENTE = ("strahlen", "schleier", "wellen", "funken", "kometen")


def akzent_fuer(post: dict, szene_art: str) -> str:
    """Genau EIN Bewegungs-Effekt je Reel (Wunsch Attila: Abwechslung, aber nicht zu viel auf einmal)."""
    seed = int(post.get("id") or 0)
    wahl = AKZENTE[(seed * 7 + 3) % len(AKZENTE)]
    if wahl == "funken" and szene_art == "staub":          # zwei Teilchen-Effekte zusammen waeren zu unruhig
        wahl = "wellen"
    return wahl


class Funkenregen:
    """Goldene vierzackige Funken, die langsam herabsinken und funkeln."""

    def __init__(self, seed: int, farbe):
        rng = np.random.default_rng(seed + 11)
        self.farbe = farbe
        self.f = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(5, 11), rng.uniform(18, 45), rng.uniform(0, 6.28))
                  for _ in range(55)]

    def malen(self, bild: Image.Image, t: float) -> None:
        d = ImageDraw.Draw(bild, "RGBA")
        for x, y, gr, tempo, ph in self.f:
            yy = (y + t * tempo) % H
            xx = x + 20 * math.sin(t * 0.6 + ph)
            _funke(d, xx, yy, gr * (0.8 + 0.2 * math.sin(t * 3 + ph)), self.farbe, 0.35 + 0.45 * max(0.0, math.sin(t * 2.2 + ph)))


def _wellen_malen(bild: Image.Image, t: float, cx: float, cy: float, farbe) -> None:
    """Sanfte Lichtwellen, die vom Motiv ausgehen (wie Ringe auf dem Wasser)."""
    d = ImageDraw.Draw(bild, "RGBA")
    for k in range(3):
        u = ((t / 3.2) + k / 3) % 1.0
        r = 150 + u * 520
        a = int(110 * (1 - u) ** 1.5)
        for dr, f in ((0, 1.0), (6, 0.45), (12, 0.2)):
            d.ellipse([cx - r - dr, cy - r - dr, cx + r + dr, cy + r + dr], outline=farbe + (int(a * f),), width=3)


def hintergrund_plan(post: dict) -> dict:
    """Der Hintergrund eines Reels, einmal festgelegt und in meta.hintergrund gemerkt (Wunsch Attila 24.11.: "fixieren",
    im Content Studio sehen): {"art": "video"|"gezeichnet", "welt", "szene", "effekt", ["video": {id, quelle, link, ...}]}."""
    fest = (post.get("meta") or {}).get("hintergrund")
    if isinstance(fest, dict) and fest.get("art") in ("video", "gezeichnet"):
        return fest
    st = medien.stil(post)
    farbwelt, szene = welt(post, st, drei_zeichen(post))
    effekt = akzent_fuer(post, szene)
    wahl = None
    try:
        import stock
        wahl = stock.waehle(post, farbwelt)
    except Exception:  # noqa: BLE001
        wahl = None
    if wahl:
        return {"art": "video", "welt": farbwelt, "szene": "", "video": wahl,
                "effekt": "funken" if effekt in ("strahlen", "wellen") else effekt}
    return {"art": "gezeichnet", "welt": farbwelt, "szene": szene, "effekt": effekt}


def hintergrund_merken(post: dict) -> dict:
    """Plan festlegen und speichern (einmal je Reel), Rueckgabe wie hintergrund_plan."""
    plan = hintergrund_plan(post)
    meta = post.get("meta") or {}
    if meta.get("hintergrund") != plan and post.get("id"):
        try:
            import db
            db.setze_meta(int(post["id"]), "hintergrund", plan)
            post["meta"] = {**meta, "hintergrund": plan}
        except Exception as e:  # noqa: BLE001
            print(f"[Reel] Hintergrund nicht gemerkt: {e}", flush=True)
    return plan


def hintergrund_quelle(post: dict) -> dict | None:
    """Welches echte Video (Pixabay/Pexels) dieses Reel als Hintergrund hat -- fuer den Link im Content Studio."""
    if post.get("art") != "reel":
        return None
    plan = hintergrund_plan(post)
    v = plan.get("video") or {}
    return {"quelle": v.get("quelle"), "id": v.get("id")} if plan.get("art") == "video" else None


class Szene:
    """Bewegter Hintergrund: driftender Nebel, wehendes Polarlicht, kreisende Galaxie oder aufsteigender Sternenstaub.
    Alles wird einmal vorbereitet; pro Bild nur verschoben/gedreht (schnell)."""

    def __init__(self, art: str, palette: str, seed: int):
        from PIL import ImageFilter
        self.art = art
        f1, f2 = SZENE_FARBEN.get(palette, SZENE_FARBEN["nacht"])
        rng = np.random.default_rng(seed or 3)
        if art == "nebel":
            gw, gh = W // 4 + 80, H // 4 + 80
            ys, xs = np.mgrid[0:gh, 0:gw].astype(np.float32)
            wolken = sum((np.asarray(Image.fromarray((rng.random((g, g)) * 255).astype(np.uint8), "L")
                                     .resize((gw, gh), Image.BICUBIC), np.float32) / 255) * f
                         for g, f in ((4, 0.5), (9, 0.3), (19, 0.2)))
            mix = np.clip((wolken - 0.3) * 1.8, 0, 1)
            farbe = np.array(f1, np.float32) * (1 - mix[..., None]) + np.array(f2, np.float32) * mix[..., None]
            alpha = np.clip((wolken - 0.42) * 2.2, 0, 1) * 120
            arr = np.dstack([farbe, alpha]).astype(np.uint8)
            self.bild = Image.fromarray(arr, "RGBA").resize((gw * 4, gh * 4), Image.BICUBIC).filter(ImageFilter.GaussianBlur(18))
        elif art == "polarlicht":
            self.baender = []
            for k in range(3):
                b = Image.new("RGBA", (W * 2, 700), (0, 0, 0, 0))
                d = ImageDraw.Draw(b)
                farbe = f1 if k % 2 == 0 else f2
                phase, amp, dicke = rng.uniform(0, 6.28), rng.uniform(60, 120), rng.uniform(70, 130)
                for x in range(0, W * 2, 6):
                    y = 350 + amp * math.sin(x / 260 + phase) + 40 * math.sin(x / 90 + phase * 2)
                    for j in range(6):
                        d.line([(x, y - dicke * (j / 6)), (x, y - dicke * (j / 6) - 18)],
                               fill=farbe + (int(70 * (1 - j / 6)),), width=6)
                self.baender.append((b.filter(ImageFilter.GaussianBlur(22)), 200 + k * 170, rng.uniform(25, 45), rng.uniform(0, 6.28)))
        elif art == "galaxie":
            g = 1500
            b = Image.new("RGBA", (g, g), (0, 0, 0, 0))
            d = ImageDraw.Draw(b)
            for arm in range(3):
                for k in range(900):
                    r = 20 + k * 0.75
                    w = arm * 2.094 + r / 140 + rng.normal(0, 0.18)
                    x, y = g / 2 + r * math.cos(w), g / 2 + r * math.sin(w) * 0.55
                    farbe = f1 if rng.random() < 0.6 else f2
                    pr = rng.uniform(1.0, 3.2)
                    d.ellipse([x - pr, y - pr, x + pr, y + pr], fill=farbe + (int(rng.uniform(60, 200)),))
            kern = Image.new("RGBA", (g, g), (0, 0, 0, 0))
            ImageDraw.Draw(kern).ellipse([g / 2 - 120, g / 2 - 70, g / 2 + 120, g / 2 + 70], fill=f2 + (130,))
            b.alpha_composite(kern.filter(ImageFilter.GaussianBlur(60)))
            self.bild = b.filter(ImageFilter.GaussianBlur(1.2))
        else:   # staub
            self.teilchen = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(2.0, 5.5), rng.uniform(25, 80),
                              rng.uniform(0, 6.28), f1 if rng.random() < 0.5 else f2) for _ in range(190)]

    def malen(self, bild: Image.Image, t: float, sichtbar: float = 1.0) -> None:
        if self.art == "nebel":
            dx, dy = 40 * math.sin(t / 7), 30 * math.cos(t / 9) + t * 4
            x0, y0 = 160 + dx, 160 + (dy % 140)
            ausschnitt = self.bild.crop((int(x0), int(y0), int(x0) + W, int(y0) + H))
            medien.aufkleben(bild, _mit_alpha(ausschnitt, 0.85 * sichtbar), (0, 0))
        elif self.art == "polarlicht":
            for b, y, tempo, ph in self.baender:
                x = -((t * tempo) % W)
                a = (0.55 + 0.45 * math.sin(t * 0.7 + ph)) * sichtbar
                medien.aufkleben(bild, _mit_alpha(b, a), (int(x), y))
        elif self.art == "galaxie":
            g = self.bild.rotate(t * 3.5, resample=Image.BILINEAR)
            medien.aufkleben(bild, _mit_alpha(g, 0.95 * sichtbar), (W / 2 - g.width / 2, 980 - g.height / 2))
        else:
            d = ImageDraw.Draw(bild, "RGBA")
            for x, y, r, tempo, ph, farbe in self.teilchen:
                yy = (y - t * tempo) % H
                xx = x + 14 * math.sin(t * 0.8 + ph)
                a = int(255 * (0.5 + 0.4 * math.sin(t * 2 + ph)) * sichtbar)
                d.ellipse([xx - r * 2.2, yy - r * 2.2, xx + r * 2.2, yy + r * 2.2], fill=farbe + (a // 6,))   # weicher Schein
                d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=farbe + (a,))


def _neumond_kranz(r: float, beleuchtung) -> Image.Image:
    """Neumond: weicher goldener Lichtkranz um die dunkle Scheibe und ein feiner, heller Saum auf der Seite,
    an der die neue Sichel erscheint (rechts) -- wie bei einer Sonnenfinsternis, ruhig statt einer schwarzen Kugel."""
    from PIL import ImageFilter
    gr = int(r * 3.2)
    c = gr / 2
    kranz = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    d = ImageDraw.Draw(kranz)
    for breite, a in ((int(r * 0.26), 120), (int(r * 0.1), 190)):
        d.ellipse([c - r - breite / 2, c - r - breite / 2, c + r + breite / 2, c + r + breite / 2],
                  outline=(240, 214, 160, a), width=breite)
    kranz = kranz.filter(ImageFilter.GaussianBlur(r * 0.12))
    saum = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
    ImageDraw.Draw(saum).arc([c - r, c - r, c + r, c + r], start=-70, end=70, fill=(255, 246, 225, 255), width=max(3, int(r * 0.05)))
    saum = saum.filter(ImageFilter.GaussianBlur(r * 0.012))
    kranz.alpha_composite(saum)
    return kranz


def _bahn_punkte(cx, cy, rx, ry, neigung, n=180):
    c, s = math.cos(neigung), math.sin(neigung)
    out = []
    for i in range(n + 1):
        w = 2 * math.pi * i / n
        x, y = rx * math.cos(w), ry * math.sin(w)
        out.append((cx + x * c - y * s, cy + x * s + y * c, math.sin(w)))
    return out


def _staub(seed: int, n: int = 56) -> list[tuple]:
    rnd = medien.zufall(seed + 99)
    return [(rnd() * W, rnd() * H, 1.2 + rnd() * 2.8, 18 + rnd() * 40, rnd() * 6.28, 0.25 + rnd() * 0.5) for _ in range(n)]


def _staub_malen(d, staub, t, sichtbar, farbe) -> None:
    for x, y, r, tempo, phase, a in staub:
        yy = (y - tempo * t) % H
        xx = x + 22 * math.sin(t * 0.6 + phase)
        alpha = a * (0.6 + 0.4 * math.sin(t * 1.7 + phase)) * sichtbar
        d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=farbe + (int(200 * alpha),))


def _schimmer(karte: Image.Image, fortschritt: float) -> Image.Image:
    """Ein schmaler goldener Lichtstreif gleitet einmal schraeg ueber den Text (fortschritt 0..1)."""
    if not 0 < fortschritt < 1:
        return karte
    a = np.asarray(karte.getchannel("A"), dtype=np.float32) / 255
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    mitte = -0.3 * w + fortschritt * 1.6 * w
    band = np.clip(1 - np.abs((xx + 0.35 * yy) - mitte) / (0.12 * w), 0, 1) ** 1.5
    licht = (band * a * 0.95 * 255).astype(np.uint8)
    glanz = Image.new("RGBA", (w, h), (255, 244, 214, 0))
    glanz.putalpha(Image.fromarray(licht, "L"))
    out = karte.copy()
    out.alpha_composite(glanz)
    return out


def _glut(breite: int, hoehe: int, farbe) -> Image.Image:
    yy, xx = np.mgrid[0:hoehe, 0:breite]
    r = np.sqrt(((xx - breite / 2) / (breite / 2)) ** 2 + ((yy - hoehe / 2) / (hoehe / 2)) ** 2)
    a = (np.clip(1 - r, 0, 1) ** 2 * 90).astype(np.uint8)
    g = Image.new("RGBA", (breite, hoehe), farbe + (0,))
    g.putalpha(Image.fromarray(a, "L"))
    return g


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


# Ungarisch laeuft auf Facebook (Leserinnen etwa 45-70): etwas mehr Zeit zum Lesen je Zeile
TEMPO = {"hu": 1.12}


ZWEITES_REEL_TEMPO = 1.25


def zeitplan(zeilen: list[str], ende_s: float = 3.2, tempo: float = 1.0, kurz: bool = False,
             hook_extra: float = 0.0) -> tuple[list[tuple[float, float]], float, float]:
    """Start/Ende je Zeile, Beginn der Endkarte, Gesamtdauer (Sekunden). tempo > 1: langsamer (mehr Lesezeit).
    kurz: Zeilen nach dem Hook nur gut eine Sekunde (Stopp bei deinem Zeichen); hook_extra: Zeit zum Waehlen."""
    t, plan = 0.0, []                     # Hook ab dem ersten Bild (Vorschaubild, erste Sekunde)
    for i, z in enumerate(zeilen):
        if kurz and i:
            dauer = max(1.25, min(1.55, 0.7 + 0.15 * len(z.split()))) * tempo
        else:
            dauer = max(2.4, min(4.2, 1.1 + 0.32 * len(z.split()))) * tempo
        if i == 0:
            dauer += 0.4 + hook_extra
        plan.append((t, t + dauer))
        t += dauer + 0.15
    ende = t + 0.1
    return plan, ende, ende + ende_s


def musik_fuer(post: dict, dauer: float, einsaetze: list[float], seed: int) -> np.ndarray:
    """Musik mit echten Instrumenten (musik.py), Stil nach Format; ohne Klang-Bank die alte Klangflaeche."""
    try:
        import musik
        if musik.bereit():
            return musik.stueck(dauer, einsaetze, seed, musik.stil_fuer(post.get("meta")))
    except Exception:
        pass
    return klang(dauer, einsaetze, seed)


def erstelle(post: dict, ziel: str, tiktok: bool = False) -> dict:
    """Rendert das Reel nach `ziel` (MP4). tiktok=True: kurze Fassung ohne Klangflaeche.
    Rueckgabe: {"sekunden", "bilder"}."""
    meta = post.get("meta") or {}
    seed = post.get("id") or 1
    zeilen, _ = texte(post)
    fmt = reel_format(post)
    drei = drei_zeichen(post) if not tiktok else []
    zwoelf = fmt in ("stopp", "woche") and len(zeilen) >= 13
    rad = zwoelf and fmt == "woche"
    karten_spiel = fmt == "karte" and len(zeilen) >= 4
    zeichen_je_zeile = [medien.zeichen_aus_text(z_) for z_ in zeilen]
    if drei:            # die Namen stehen gross in der Dreier-Reihe -> die Saetze kommen ohne sie aus
        for nr, z_ in enumerate(zeilen):
            rest = re.split(r"\s*[:–—]\s*", z_, maxsplit=1)
            if len(rest) > 1 and rest[1].strip() and (nr == 0 or zeichen_je_zeile[nr] in drei):
                zeilen[nr] = rest[1].strip()[:1].upper() + rest[1].strip()[1:]
    if rad:             # Wochen-Rad: der Name steht in der Radmitte -> im Text nur das Wort (gross)
        for nr in range(1, len(zeilen)):
            rest = re.split(r"\s*[:–—]\s*", zeilen[nr], maxsplit=1)
            if len(rest) > 1 and rest[1].strip() and zeichen_je_zeile[nr] is not None:
                zeilen[nr] = rest[1].strip()[:1].upper() + rest[1].strip()[1:]
    if tiktok and not (zwoelf or karten_spiel):        # Spiele brauchen alle Zeilen
        zeilen = zeilen[:TIKTOK_ZEILEN]
    tempo = 1.0 if tiktok else TEMPO.get((post.get("sprache") or "")[:2], 1.0)
    if not tiktok and meta.get("reel_nr") == 2 and not zwoelf:
        tempo *= ZWEITES_REEL_TEMPO       # Drei-Zeichen-Check: jedes Zeichen bleibt laenger stehen (Facebook: 15-30 s am besten)
    plan, end_start, dauer = zeitplan(zeilen, TIKTOK_ENDE if tiktok else 3.2, tempo, kurz=zwoelf,
                                      hook_extra=1.6 if karten_spiel else 0.0)
    SCHLEIFE = 0.7          # die letzten Sekundenbruchteile blenden zurueck zum Anfang (Video laeuft nahtlos weiter)
    n = int(round(dauer * FPS))

    # --- feste Ebenen einmal vorbereiten
    # leichtes, festes Rauschen gegen Farbstufen im Verlauf (H.264 macht sonst sichtbare Ringe)
    st = medien.stil(post)
    hg = hintergrund_plan(post) if not tiktok else None
    farbwelt, szene_art = (hg["welt"], hg.get("szene") or "") if hg else (st["palette"], "")
    akzent = medien.PALETTEN[st["palette"]]["akzent"]
    roh = np.asarray(medien._verlauf_hintergrund(W, H, farbwelt), dtype=np.float32)
    # Schritt C: bei jedem zweiten Reel ein echtes Video als Hintergrund (stock.py, nur mit PEXELS_API_KEY)
    echt = None
    if not tiktok:
        try:
            import stock
            if hg and hg["art"] == "video":
                pfad = stock.datei(hg["video"])
                echt = {"pfad": pfad, "id": hg["video"]["id"], "quelle": hg["video"].get("quelle")} if pfad else None
        except Exception:  # noqa: BLE001
            echt = None
    if hg and hg["art"] == "video" and not echt:       # Video nicht ladbar -> gezeichnete Szene derselben Welt
        szene_art = SZENEN[int(seed) % len(SZENEN)]
    szene_bewegt = Szene(szene_art, farbwelt, int(seed)) if szene_art and not echt else None
    f1, f2 = SZENE_FARBEN.get(farbwelt, SZENE_FARBEN["nacht"])
    effekt = (hg.get("effekt") or akzent_fuer(post, szene_art)) if hg else ""
    if echt and effekt in ("strahlen", "wellen"):        # das echte Bild ist das Motiv -> nur ruhige Effekte
        effekt = "funken"
    strahlen = _strahlen(tuple(min(255, int(c * 0.9 + 25)) for c in f1)) if effekt == "strahlen" else None
    schleier = [(_schleier(f1), 0.0), (_schleier(f2), 2.6)] if effekt == "schleier" else []
    funkenregen = Funkenregen(int(seed), tuple(min(255, int(c * 0.8 + 50)) for c in f1)) if effekt == "funken" else None
    wellen_farbe = tuple(min(255, int(c * 0.85 + 40)) for c in f1) if effekt == "wellen" else None
    rauschen = np.random.default_rng(7).uniform(-1.6, 1.6, roh.shape[:2])[..., None]
    grund = Image.fromarray(np.clip(roh + rauschen, 0, 255).astype(np.uint8), "RGB")
    # "atmender" Hintergrund: zweite, hellere Fassung, sanft ueberblendet
    grund_hell = Image.fromarray(np.clip((roh + rauschen) * 1.22 + 6, 0, 255).astype(np.uint8), "RGB")
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
    schnuppen = [(0.25, (W * 0.18, 260), math.radians(28)), (max(4.0, end_start - 3.0), (W * 0.62, 180), math.radians(152))]
    if not tiktok and hintergrund_plan(post).get("effekt") == "kometen":   # alle ~3,5 s eine Sternschnuppe
        schnuppen += [(t0, (W * (0.12 if k % 2 else 0.7), 150 + 90 * (k % 3)), math.radians(30 if k % 2 else 150))
                      for k, t0 in enumerate(np.arange(2.0, end_start - 1.0, 3.5))]
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
    motiv = motive.waehle(post, st)                    # Hauptmotiv je Format (reel-11)
    eigene_optik = bool(drei) or zwoelf or karten_spiel
    mit_mond = meta.get("phase_index") is not None and motiv == "mond" and not eigene_optik and not echt
    r = 200
    mond = medien.mond(r * 2, meta.get("phase_index"), meta.get("beleuchtung")) if mit_mond else None
    if mond is not None:
        mond = mond.resize((mond.width // 2, mond.height // 2), Image.LANCZOS)
    schein = medien.mond_schein(r, meta.get("phase_index"), meta.get("beleuchtung")) if mit_mond else None
    mond_y = 720
    # groessere Schrift (gut lesbar auch fuer aeltere Augen und in der kleinen Vorschau)
    karten = [_textkarte(z_, breite=W - 140, groesse=106 if i == 0 else (150 if rad else 90), name="cormorant", farbe="#F6E3B4",
                         max_zeilen=3, akzent=(250, 208, 120), gold=not rad and len(z_.split()) > 2) for i, z_ in enumerate(zeilen)]
    text_mitte = 1200          # etwas hoeher: Facebook zeigt Reels im Feed beschnitten (unten fehlt sonst Text)
    if echt:
        text_mitte = 1400      # echtes Video: die Mitte (Mond, Flamme …) bleibt frei
    endkarte, end_pos = _zuschneiden(_endkarte(post, tiktok))
    # Bildideen (reel-10)
    zeichen = welches_zeichen(post, st)
    sb_kasten = (70, mond_y - 430, W - 140, 860)                    # Sternbild rund um den Mond
    held = None if eigene_optik or echt else motive.baue(motiv, W / 2, mond_y, zeichen=zeichen, akzent=akzent, seed=int(seed), post=post)
    sprache = (post.get("sprache") or "de")[:2]
    reihe = _dreier_ebenen(drei, sprache) if drei else None
    zusatz = _dreier_zusatz(fmt, drei, sprache) if drei else None
    plaetze = _platz_ebenen(sprache) if drei and fmt == "glueck" else None
    zwoelf_ebenen = _zwoelf_ebenen(*((130, 46, 52) if rad else ())) if zwoelf else None
    rad_gross = _zwoelf_ebenen(260, 100, 128) if rad else None
    rad_namen = None
    if rad:                                                        # Namen klein in der Radmitte (Text zeigt nur das Wort)
        rad_namen = {}
        for i in range(12):
            nb = Image.new("RGBA", (800, 90), (0, 0, 0, 0))
            medien.gesperrt(ImageDraw.Draw(nb), medien.ZEICHEN_NAMEN[i][_spalte(sprache)].upper(), 400, 60,
                            medien.schrift("cinzel", 56), 9, _hell(ELEMENT_FARBE[i % 4], 0.25) + (255,))
            rad_namen[i] = nb.resize((400, 45), Image.LANCZOS)
    karten_ebenen = _karten_ebenen(sprache) if karten_spiel else None
    # reel-18 (Wunsch Attila 08.11.): kein Sternbild aus Linien und keine kreisende Umlaufbahn mehr -- das wirkte wie
    # ein Planet mit Ring und "stehende Sterne"; das Zeichen steht ohnehin im kleinen Kreis unter dem Mond
    zeichen = None
    bahn = []
    # Neumond (fast kein Licht): statt einer dunklen Kugel ein zarter goldener Lichtkranz und ein feiner Lichtsaum
    neumond = _neumond_kranz(r, meta.get("beleuchtung")) if mit_mond and float(meta.get("beleuchtung") or 0) < 8 else None
    staub = _staub(int(seed))
    staub_farbe = (236, 180, 160) if st["palette"] == "liebe" else (233, 207, 156)
    glut = _glut(1000, 560, tuple(akzent))
    # kleine Szene je Format: Liebe = zwei Lichter kreisen gegenlaeufig um den Mond, Ritual = Kerzenschein von unten
    szene = st["layout"]
    kerze = _glut(1300, 900, (255, 176, 92)) if (szene == "ritual" and motiv != "kerze") or fmt == "ritual" else None

    def lichter(u: float) -> list:
        if szene == "liebe":
            return [(u, (255, 214, 200)), ((1 - u + 0.5) % 1.0, (255, 170, 170))]
        return [(u, (255, 240, 205))]

    ffmpeg = ffmpeg_pfad()
    ton = os.path.join(os.path.dirname(os.path.abspath(ziel)) or ".", f".klang-{os.getpid()}-{seed}.raw")
    with open(ton, "wb") as f:
        if tiktok:      # Stille (eine Tonspur bleibt drin, manche Apps erwarten sie)
            f.write(np.zeros((int((dauer + 0.5) * 48000), 2), dtype=np.int16).tobytes())
        else:
            f.write(musik_fuer(post, dauer + 0.5, [max(0.0, s) for s, _ in plan] + [end_start], int(seed)).tobytes())
    befehl = [ffmpeg, "-y", "-loglevel", "error",
              "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
              "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", ton,
              "-shortest", "-map", "0:v", "-map", "1:a",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
              "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", ziel]
    proz = subprocess.Popen(befehl, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    leser, letztes = None, None
    if echt:   # echtes Video: endlos wiederholt, auf 1080x1920 zugeschnitten, langsam herangezoomt
        leser = subprocess.Popen([ffmpeg, "-loglevel", "error", "-stream_loop", "-1", "-i", echt["pfad"], "-t", f"{dauer + 0.5:.2f}",
                                  "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        grund_arr = np.asarray(grund, dtype=np.float32)
    try:
        for i in range(n):
            t = i / FPS
            atem = 0.5 + 0.5 * math.sin(t * 0.9)
            if leser is not None:
                roh_bild = leser.stdout.read(W * H * 3)
                if len(roh_bild) == W * H * 3:
                    letztes = np.frombuffer(roh_bild, dtype=np.uint8).reshape(H, W, 3)
                if letztes is not None:
                    # abgedunkelt und leicht in der Farbwelt getoent, damit die Schrift gut lesbar bleibt
                    mix = letztes.astype(np.float32) * 0.62 + grund_arr * 0.30
                    z = 1 + 0.06 * t / max(dauer, 1)                   # langsamer Zoom (Bewegung)
                    bild = Image.fromarray(np.clip(mix, 0, 255).astype(np.uint8), "RGB")
                    if z > 1.002:
                        bw_, bh_ = int(W / z), int(H / z)
                        bild = bild.crop(((W - bw_) // 2, (H - bh_) // 2, (W - bw_) // 2 + bw_, (H - bh_) // 2 + bh_)).resize((W, H), Image.BILINEAR)
                else:
                    bild = grund.copy()
            else:
                bild = Image.blend(grund, grund_hell, 0.55 * atem) if not tiktok else grund.copy()
            for k, (sl, ph) in enumerate(schleier):                 # Lichtschleier ziehen diagonal durchs Bild
                u = ((t + ph * 3) / 9.0) % 1.0
                sx = -sl.width + u * (W + sl.width * 1.2) if k == 0 else W - u * (W + sl.width * 1.2)
                sy = 150 + 900 * u if k == 0 else 1300 - 800 * u
                medien.aufkleben(bild, _mit_alpha(sl, 0.75 * math.sin(math.pi * u)), (sx, sy))
            if szene_bewegt is not None:
                szene_bewegt.malen(bild, t)
            if funkenregen is not None:
                funkenregen.malen(bild, t)
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
            u = (t - (dauer - SCHLEIFE)) / SCHLEIFE               # am Schluss zurueck zum Anfangsbild (Schleife):
            weg = _weich(2 * u)                                    # erst geht die Endkarte,
            rueck = _weich(2 * u - 1)                              # dann kommt der Anfang zurueck
            sichtbar_ende = max(sichtbar_ende, rueck)
            _staub_malen(dd, staub, t, 0.5 + 0.5 * sichtbar_ende, staub_farbe)
            if zeichen is not None:
                _sternbild(dd, zeichen, sb_kasten, t, sichtbar_ende * _weich(t / 0.6), tuple(akzent))
            umlauf = (t / 7.0) % 1.0                                 # ein Lichtpunkt umkreist den Mond
            if bahn and sichtbar_ende > 0:
                dd.line([(x, y) for x, y, _ in bahn], fill=tuple(akzent) + (int(105 * sichtbar_ende * _weich(t / 1.2)),), width=2)
                for u, fb in lichter(umlauf):
                    bx, by, vorne = bahn[int(u * (len(bahn) - 1))]
                    if vorne < 0:                                    # hinter dem Mond
                        for r_, a_ in ((18, 0.15), (6, 0.9)):
                            dd.ellipse([bx - r_, by - r_, bx + r_, by + r_], fill=fb + (int(255 * a_ * sichtbar_ende),))
            if kerze is not None:                                    # warmes Kerzenlicht von unten, flackernd
                flacker = 0.75 + 0.15 * math.sin(t * 7.3) + 0.1 * math.sin(t * 12.9 + 1)
                medien.aufkleben(bild, _mit_alpha(kerze, flacker * (0.4 + 0.6 * sichtbar_ende)), (W / 2 - kerze.width / 2, H - kerze.height + 120))
            if sichtbar_ende > 0:
                medien.aufkleben(bild, _mit_alpha(oben, sichtbar_ende), oben_pos)
            if mond is not None and sichtbar_ende > 0:
                auf = 1.0
                puls = 0.75 + 0.25 * math.sin(t * 1.4)
                medien.aufkleben(bild, _mit_alpha(schein, auf * puls * sichtbar_ende),
                                 (W / 2 - schein.width / 2, mond_y - schein.height / 2))
                skala = 0.94 + 0.08 * min(1.0, t / max(end_start, 1))   # langsamer Zoom (Bewegung)
                mb = mond if abs(skala - 1) < 0.002 else mond.resize((int(mond.width * skala), int(mond.height * skala)), Image.BILINEAR)
                if neumond is not None:
                    nk = neumond if abs(skala - 1) < 0.002 else neumond.resize((int(neumond.width * skala), int(neumond.height * skala)), Image.BILINEAR)
                    medien.aufkleben(bild, _mit_alpha(nk, (0.8 + 0.2 * math.sin(t * 1.1)) * sichtbar_ende),
                                     (W / 2 - nk.width / 2, mond_y - nk.height / 2))
                    medien.aufkleben(bild, _mit_alpha(mb, 0.55 * sichtbar_ende), (W / 2 - mb.width / 2, mond_y - mb.height / 2))
                else:
                    medien.aufkleben(bild, _mit_alpha(mb, auf * sichtbar_ende), (W / 2 - mb.width / 2, mond_y - mb.height / 2))
            if strahlen is not None and sichtbar_ende > 0 and not zwoelf and not karten_spiel:
                sk = strahlen.rotate(t * 9, resample=Image.BILINEAR)   # Strahlenkranz hinter dem Motiv
                medien.aufkleben(bild, _mit_alpha(sk, (0.42 + 0.2 * math.sin(t * 1.7)) * sichtbar_ende),
                                 (W / 2 - sk.width / 2, (700 if drei else mond_y) - sk.height / 2))
            if wellen_farbe is not None and sichtbar_ende > 0 and not zwoelf and not karten_spiel:
                _wellen_malen(bild, t, W / 2, 700 if drei else mond_y, wellen_farbe)
            if held is not None:          # Vorlauf: das Symbol steht schon im ersten Bild (Titelbild der Plattformen)
                held.zeichne(bild, t + 1.2, sichtbar_ende)
            if reihe is not None and sichtbar_ende > 0:
                aktiv = next((zeichen_je_zeile[nr] for nr, (a_, b_) in enumerate(plan)
                              if nr and a_ - 0.2 <= t <= b_ + 0.1 and zeichen_je_zeile[nr] in drei), None)
                if t < 0.9:                       # erste Sekunde: die drei Zeichen leuchten nacheinander auf
                    aktiv = drei[min(2, int(t / 0.3))]
                _dreier_malen(bild, reihe, drei, aktiv, t, sichtbar_ende)
                if zusatz is not None:
                    medien.aufkleben(bild, _mit_alpha(zusatz, sichtbar_ende), (0, 380))
                zeile = next(((nr, a_) for nr, (a_, b_) in enumerate(plan)
                              if nr and a_ - 0.2 <= t <= b_ + 0.1 and zeichen_je_zeile[nr] in drei), None)
                if plaetze is not None and zeile is not None:          # Platz-Schild ueber dem aktiven Zeichen
                    k = drei.index(zeichen_je_zeile[zeile[0]])
                    auf = _weich((t - zeile[1]) / 0.4)
                    schild = plaetze[k]
                    sx, sy = W / 2 + (k - 1) * 330, 700 - 178 - 14 * (1 - auf)
                    medien.aufkleben(bild, _mit_alpha(schild, auf * sichtbar_ende), (sx - schild.width / 2, sy - schild.height / 2))
                    if k == 2:                                         # Platz 1: goldene Funken
                        dd2 = ImageDraw.Draw(bild, "RGBA")
                        for j in range(4):
                            _funke(dd2, sx - 150 + j * 100, sy - 40 - 12 * math.sin(t * 3 + j), 8, (246, 227, 180),
                                   auf * (0.5 + 0.5 * math.sin(t * 5 + j)) * sichtbar_ende)
            if rad_gross is not None and sichtbar_ende > 0:
                _rad_malen(bild, zwoelf_ebenen, rad_gross, plan, zeichen_je_zeile, t, sichtbar_ende, rad_namen)
            elif zwoelf_ebenen is not None and sichtbar_ende > 0:
                aktiv = next((zeichen_je_zeile[nr] for nr, (a_, b_) in enumerate(plan)
                              if nr and a_ - 0.1 <= t <= b_ + 0.05), None)
                _zwoelf_malen(bild, zwoelf_ebenen, aktiv, t, sichtbar_ende)
            if karten_ebenen is not None and sichtbar_ende > 0:
                _karten_malen(bild, karten_ebenen, plan, t, sichtbar_ende)
            if bahn and sichtbar_ende > 0:
                d2 = ImageDraw.Draw(bild, "RGBA")
                for u, fb in lichter(umlauf):
                    bx, by, vorne = bahn[int(u * (len(bahn) - 1))]
                    if vorne >= 0:
                        for r_, a_ in ((20, 0.15), (7, 0.95)):
                            d2.ellipse([bx - r_, by - r_, bx + r_, by + r_], fill=fb + (int(255 * a_ * sichtbar_ende),))
            for nr, ((start, stopp), (karte, kaesten)) in enumerate(zip(plan, karten)):
                if nr and 0 <= t - start <= 0.9:                       # neue Zeile: weiches Aufleuchten dahinter
                    medien.aufkleben(bild, _mit_alpha(glut, math.sin(math.pi * (t - start) / 0.9) * 0.9),
                                     (W / 2 - glut.width / 2, text_mitte - glut.height / 2))
                if not nr and t < ERSTE_SEKUNDE:                       # erstes Bild: Hook leuchtet golden, klingt ab
                    medien.aufkleben(bild, _mit_alpha(glut, 0.85 * (1 - _weich(t / ERSTE_SEKUNDE))),
                                     (W / 2 - glut.width / 2, text_mitte - glut.height / 2))
                if start - 0.01 <= t <= stopp + AUSBLENDEN:
                    # Hook steht ab dem ersten Bild ganz da, alle weiteren Texte erscheinen Wort fuer Wort
                    lesen = 0.35 if zwoelf else min(1.1, 0.16 * len(kaesten) + 0.3)     # Stopp: kaum Zeit -> fast sofort
                    fortschritt = 1.0 if start <= 0 else min(1.0, (t - start) / lesen)
                    raus = 1 - _weich((t - stopp) / AUSBLENDEN)
                    if raus > 0.003:
                        k = _wort_fuer_wort(karte, kaesten, fortschritt)
                        if nr == 0:
                            k = _schimmer(k, (t - 0.12) / 1.0)              # Lichtstreif ueber den Hook, sofort
                            if t < 0.5:                                     # Hook kommt sanft heran (Bewegung ab Bild 1)
                                gr = 1.10 - 0.10 * _weich(t / 0.5)
                                k = k.resize((int(k.width * gr), int(k.height * gr)), Image.BILINEAR)
                        # sanft von unten herein, beim Ausblenden ein wenig nach oben
                        hub = 0 if start <= 0 else 26 * (1 - _weich((t - start) / 0.6))
                        hub -= 18 * (1 - raus)
                        medien.aufkleben(bild, _mit_alpha(k, raus),
                                         (W / 2 - k.width / 2, text_mitte - k.height / 2 + hub))
            if t >= end_start:
                medien.aufkleben(bild, _mit_alpha(endkarte, _weich((t - end_start - 0.3) / 0.9) * (1 - weg)), end_pos)
            if rueck > 0.003:                                          # der Hook kommt zurueck wie im ersten Bild
                medien.aufkleben(bild, _mit_alpha(karten[0][0], rueck),
                                 (W / 2 - karten[0][0].width / 2, text_mitte - karten[0][0].height / 2))
            schwarz = 1.0          # keine Schwarzblende: das erste Bild zeigt gleich den Hook
            # Impuls bei jedem neuen Satz: kurzer Lichtblitz in der Farbwelt und ein kleiner Zoom ("Punch")
            if not tiktok:
                neu_seit = min([t - a_ for nr, (a_, _b) in enumerate(plan) if nr and 0 <= t - a_ < 0.4] or [9])
                if neu_seit < 0.4:
                    k_ = 1 - _weich(neu_seit / 0.4)
                    z = 1 + 0.035 * k_
                    bw_, bh_ = int(W / z), int(H / z)
                    bild = bild.crop(((W - bw_) // 2, (H - bh_) // 2, (W - bw_) // 2 + bw_, (H - bh_) // 2 + bh_)).resize((W, H), Image.BILINEAR)
                    bild = Image.blend(bild, Image.new("RGB", (W, H), f1), 0.10 * k_)
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
        if leser is not None:
            leser.kill()
        try:
            os.remove(ton)
        except OSError:
            pass
    return {"sekunden": round(dauer, 1), "bilder": n, **({"echt": echt["id"]} if echt else {})}


def als_bytes(post: dict, tiktok: bool = False) -> bytes:
    with tempfile.TemporaryDirectory() as ordner:
        ziel = os.path.join(ordner, "reel.mp4")
        erstelle(post, ziel, tiktok)
        with open(ziel, "rb") as f:
            return f.read()


# ---------------------------------------------------------------------------
# Diashow: aus den Karussell-Folien eines Feed-Posts ein Reel (fuer Instagram, wo Reels Fremde erreichen)
# ---------------------------------------------------------------------------
DIA_FOLIE, DIA_UEBERGANG, DIA_LETZTE = 2.6, 0.5, 6.0     # Schlussfolie (App-Einladung) in Ruhe lesbar
DIA_ZIEL, DIA_MAX_SCHRITT = 22.0, 5.0


def diashow(post: dict, bilder: list[bytes], ziel: str) -> dict:
    """Folien (1080x1350) nacheinander im Hochformat, sanfter Zoom, weiche Ueberblendung, Goldstaub und Klang."""
    import io
    seed = int(post.get("id") or 1)
    st = medien.stil(post)
    folien = [Image.open(io.BytesIO(b)).convert("RGB") for b in bilder] or [Image.new("RGB", (1080, 1350), (20, 12, 40))]
    breite = 1000
    folien = [f.resize((breite, int(f.height * breite / f.width)), Image.LANCZOS) for f in folien]
    mitte_y = 880                                        # etwas ueber der Mitte (unten liegen die Knoepfe der Apps)
    # Facebook: 15-30 s laufen am besten -> jede Folie bleibt so lange stehen, dass das Ganze ~20 s dauert (Wunsch 10.11.)
    schritt = max(DIA_FOLIE - DIA_UEBERGANG, min(DIA_MAX_SCHRITT, (DIA_ZIEL - DIA_LETZTE) / max(1, len(folien) - 1)))
    starts = [i * schritt for i in range(len(folien))]
    dauer = starts[-1] + DIA_LETZTE
    n = int(round(dauer * FPS))
    grund = medien._verlauf_hintergrund(W, H, st["palette"]).convert("RGB")
    medien.sterne(grund, W, H, seed, True)
    staub = _staub(seed, 40)
    rand = Image.new("RGBA", (breite + 24, folien[0].height + 24), (0, 0, 0, 0))
    ImageDraw.Draw(rand).rounded_rectangle([0, 0, rand.width - 1, rand.height - 1], radius=26,
                                           outline=tuple(medien.PALETTEN[st["palette"]]["akzent"]) + (120,), width=2)
    ffmpeg = ffmpeg_pfad()
    ton = os.path.join(os.path.dirname(os.path.abspath(ziel)) or ".", f".dia-{os.getpid()}-{seed}.raw")
    with open(ton, "wb") as f:
        f.write(musik_fuer(post, dauer + 0.5, starts, seed).tobytes())
    befehl = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
              "-i", "-", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", ton, "-shortest", "-map", "0:v", "-map", "1:a",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
              "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", ziel]
    proz = subprocess.Popen(befehl, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / FPS
            bild = grund.copy()
            dd = ImageDraw.Draw(bild, "RGBA")
            _staub_malen(dd, staub, t, 0.8, (233, 207, 156))
            for k, (folie, s0) in enumerate(zip(folien, starts)):
                ende = s0 + (DIA_LETZTE if k == len(folien) - 1 else schritt + DIA_UEBERGANG)
                if not (s0 - 0.01 <= t <= ende):
                    continue
                rein = 1.0 if k == 0 else _weich((t - s0) / DIA_UEBERGANG)
                zoom = 1.0 + 0.035 * (t - s0) / (ende - s0)
                f = folie if zoom < 1.002 else folie.resize((int(folie.width * zoom), int(folie.height * zoom)), Image.BILINEAR)
                ebene = f.convert("RGBA")
                medien.aufkleben(bild, _mit_alpha(rand, rein), (W / 2 - rand.width / 2, mitte_y - rand.height / 2))
                medien.aufkleben(bild, _mit_alpha(ebene, rein), (W / 2 - f.width / 2, mitte_y - f.height / 2))
            proz.stdin.write(np.asarray(bild, dtype=np.uint8).tobytes())
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


def diashow_bytes(post: dict, bilder: list[bytes]) -> bytes:
    with tempfile.TemporaryDirectory() as ordner:
        ziel = os.path.join(ordner, "dia.mp4")
        diashow(post, bilder, ziel)
        with open(ziel, "rb") as f:
            return f.read()
