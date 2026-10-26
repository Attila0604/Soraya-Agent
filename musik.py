"""
Musik fuer die Reels -- mit echten, aufgenommenen Instrumenten (Fluegel, Konzertharfe, Streicher, Floete,
Vibraphon, Kalimba, Handglocken, Glockenspiel, Shaker) aus zwei gemeinfreien Sammlungen (CC0, siehe
klaenge/QUELLEN.md). Jedes Stueck wird neu komponiert: Tonart, Akkordfolge, Tempo, ein kleines Motiv, das
wiederkehrt, Aufbau (leiser Anfang, volle Mitte, Ausklang), Hall. Vier Stile je nach Format, und durch den
Zufall (seed = Post-ID) klingt jedes Reel anders.

  himmlisch  -- Harfen-Arpeggios, Streicher, Floeten-Melodie, Glocken (Deine Woche, Wissen, Sternzeichen)
  romantisch -- Fluegel mit Melodie, Streicher und Celli (Liebe & Beziehung)
  mystisch   -- Celli-Bordun, Kalimba und Handglocken in einer alten Tonleiter, Floete (Ritual, besondere Tage)
  lofi       -- Vibraphon/Fluegel gedaempft, sanfter Beat mit Shaker, leichtes Band-Leiern (Mitmachen, Rueckblick)

Die Klang-Bank (klaenge/*.opus, gebaut mit tools/klaenge_bauen.py) wird einmal mit ffmpeg gelesen. Tonhoehen
dazwischen entstehen durch Umrechnen der naechsten Aufnahme. Rueckgabe wie reel.klang: int16 [n, 2].
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache

import numpy as np

RATE = 48000

# Akkordfolgen als Stufen (0 = Grundton der Tonart), je Akkord die Toene in Halbtonschritten
DUR_FOLGEN = [
    [(0, 4, 7, 11), (9, 12, 16, 19), (5, 9, 12, 16), (7, 11, 14, 17)],        # Imaj7 vi7 IVmaj7 V
    [(9, 12, 16), (5, 9, 12), (0, 4, 7), (7, 11, 14)],                         # vi IV I V
    [(0, 4, 7, 14), (5, 9, 12, 16), (9, 12, 16, 19), (5, 9, 12, 19)],          # I(add9) IV vi IV
    [(0, 4, 7, 11), (2, 5, 9, 12), (5, 9, 12, 16), (0, 4, 7, 14)],             # Imaj7 ii7 IVmaj7 I
    [(5, 9, 12, 16), (7, 11, 14, 17), (4, 7, 11, 14), (9, 12, 16, 19)],        # IVmaj7 V iii vi
]
MOLL_FOLGEN = [
    [(0, 3, 7, 10), (8, 12, 15), (3, 7, 10, 14), (10, 14, 17)],                # i7 VI III VII
    [(0, 3, 7), (5, 8, 12), (8, 12, 15), (7, 10, 14)],                         # i iv VI v
    [(0, 3, 7, 14), (10, 14, 17), (8, 12, 15, 19), (7, 10, 14, 17)],           # i(add9) VII VI v7
]
MODI = {"dorisch": [0, 2, 3, 5, 7, 9, 10], "phrygisch": [0, 1, 3, 5, 7, 8, 10], "aeolisch": [0, 2, 3, 5, 7, 8, 10],
        "pentatonik": [0, 3, 5, 7, 10]}
GRUNDTOENE = {"C": 130.81, "D": 146.83, "Eb": 155.56, "E": 164.81, "F": 174.61, "G": 196.0, "A": 220.0, "Bb": 233.08}
STIL_NACH_THEMA = {"Liebe & Beziehung": "romantisch", "Ritual": "mystisch", "Mitmachen": "lofi",
                   "Rückblick & Vorschau": "lofi", "Deine Woche": "himmlisch", "Astro-Wissen": "himmlisch",
                   "Sternzeichen im Fokus": "himmlisch"}
STILE = ("himmlisch", "romantisch", "mystisch", "lofi")


def stil_fuer(meta: dict | None) -> str:
    thema = (meta or {}).get("thema") or ""
    if thema.startswith("Großes Ereignis"):
        return "mystisch"
    return STIL_NACH_THEMA.get(thema, "himmlisch")


def _hz(grund: float, halbton: float) -> float:
    return grund * 2 ** (halbton / 12)


# ---------------------------------------------------------------------------
# Werkzeuge: Huellkurven, Filter, Hall
# ---------------------------------------------------------------------------
def _tiefpass(x: np.ndarray, grenze: float, steil: float = 2.0) -> np.ndarray:
    spek = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1 / RATE)
    spek *= (1 / (1 + (f / grenze) ** (2 * steil)))[:, None] if x.ndim == 2 else 1 / (1 + (f / grenze) ** (2 * steil))
    return np.fft.irfft(spek, n=x.shape[0], axis=0).astype(np.float32)


def _hochpass(x: np.ndarray, grenze: float) -> np.ndarray:
    spek = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1 / RATE)
    g = 1 - 1 / (1 + (f / grenze) ** 4)
    spek *= g[:, None] if x.ndim == 2 else g
    return np.fft.irfft(spek, n=x.shape[0], axis=0).astype(np.float32)


def _hall(x: np.ndarray, laenge: float, rng, hell: float = 5000) -> np.ndarray:
    """Stereo-Hall: Faltung mit abklingendem, gefiltertem Rauschen (je Seite eigenes Rauschen = breit)."""
    m = int(laenge * RATE)
    t = np.arange(m) / RATE
    abfall = np.exp(-t * 6.9 / laenge)
    ir = rng.standard_normal((m, 2)).astype(np.float32) * abfall[:, None]
    ir = _tiefpass(ir, hell, 1.0)
    ir[: int(0.012 * RATE)] *= np.linspace(0, 1, int(0.012 * RATE))[:, None]   # kleine Vorverzoegerung
    n = x.shape[0] + m
    groesse = 1 << (n - 1).bit_length()
    aus = np.fft.irfft(np.fft.rfft(x, groesse, axis=0) * np.fft.rfft(ir, groesse, axis=0), groesse, axis=0)[: x.shape[0]]
    return (aus / (np.abs(aus).max() + 1e-9) * np.abs(x).max()).astype(np.float32)


def _platz(buf: np.ndarray, start: float, ton: np.ndarray, pan: float, gain: float) -> None:
    s = int(start * RATE)
    if s >= buf.shape[0] or s + len(ton) <= 0:
        return
    a, e = max(0, s), min(buf.shape[0], s + len(ton))
    stueck = ton[a - s: e - s] * gain
    buf[a:e, 0] += stueck * np.cos(pan * np.pi / 2)
    buf[a:e, 1] += stueck * np.sin(pan * np.pi / 2)


# ---------------------------------------------------------------------------
# Instrumente (je ein Ton als float32-Spur)
# ---------------------------------------------------------------------------
def harfe(f: float, dauer: float = 2.6) -> np.ndarray:
    """Gezupft: Obertoene, hohe klingen schneller ab, weicher Anschlag."""
    t = np.arange(int(dauer * RATE)) / RATE
    ton = np.zeros_like(t)
    for k in range(1, 9):
        if f * k > 9000:
            break
        ton += np.sin(2 * np.pi * f * k * t + k) * np.exp(-t * (1.6 + 1.1 * k)) / k ** 1.15
    ton *= np.minimum(1, t / 0.004)
    return ton.astype(np.float32)


def klavier(f: float, dauer: float = 3.5, staerke: float = 1.0) -> np.ndarray:
    """Weiches Klavier: leicht verstimmte Obertoene (wie Saiten), Hammer-Anschlag, langes Ausklingen."""
    t = np.arange(int(dauer * RATE)) / RATE
    ton = np.zeros_like(t)
    b = 0.0004
    for k in range(1, 11):
        fk = f * k * np.sqrt(1 + b * k * k)
        if fk > 10000:
            break
        amp = (1 / k ** 1.4) * (0.6 + 0.4 * staerke)
        ton += amp * np.sin(2 * np.pi * fk * t) * np.exp(-t * (0.9 + 0.55 * k))
    ton += 0.4 * np.sin(2 * np.pi * f * 1.002 * t) * np.exp(-t * 0.7)            # Schwebung zweier Saiten
    ton *= np.minimum(1, t / 0.003) * (1 - np.exp(-(dauer - t) * 12))
    return ton.astype(np.float32)


def epiano(f: float, dauer: float = 2.8) -> np.ndarray:
    """FM-E-Piano (wie ein Rhodes): Glocke im Anschlag, warmer Ton danach."""
    t = np.arange(int(dauer * RATE)) / RATE
    index = 2.2 * np.exp(-t * 6) + 0.25
    ton = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * t)) * np.exp(-t * 1.3)
    ton += 0.25 * np.sin(2 * np.pi * f * 14 * t) * np.exp(-t * 25)                  # "Tine"-Klick
    ton *= np.minimum(1, t / 0.002) * (1 - np.exp(-(dauer - t) * 10))
    return ton.astype(np.float32)


def glocke(f: float, dauer: float = 3.0) -> np.ndarray:
    t = np.arange(int(dauer * RATE)) / RATE
    ton = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * d) for r, a, d in
              ((1, 1.0, 1.4), (2.0, 0.5, 2.2), (2.76, 0.35, 3.0), (5.4, 0.18, 5.0), (8.9, 0.08, 7.0)))
    return (ton * np.minimum(1, t / 0.002)).astype(np.float32)


def handpan(f: float, dauer: float = 3.2) -> np.ndarray:
    """Weich angeschlagenes Metall: Grundton, Oktave, Quinte darueber; runder als eine Glocke."""
    t = np.arange(int(dauer * RATE)) / RATE
    ton = (np.sin(2 * np.pi * f * t) * np.exp(-t * 1.1) + 0.45 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 1.8)
           + 0.25 * np.sin(2 * np.pi * f * 3 * t) * np.exp(-t * 2.6) + 0.12 * np.sin(2 * np.pi * f * 4.2 * t) * np.exp(-t * 4))
    ton *= np.minimum(1, t / 0.012)
    return ton.astype(np.float32)


def flaeche(freqs: list[float], dauer: float, rng, hell: float = 1600) -> np.ndarray:
    """Warme Flaeche (Streicher/Synth): mehrere leicht verstimmte Saegezaehne je Ton, gefiltert, Stereo."""
    n = int(dauer * RATE)
    t = np.arange(n) / RATE
    aus = np.zeros((n, 2), np.float32)
    for f in freqs:
        for seite, verst in ((0, -0.08), (1, 0.08), (0, 0.03), (1, -0.03)):
            ff = f * 2 ** (verst / 12)
            vib = 0.0025 * np.sin(2 * np.pi * (4.5 + rng.random()) * t + rng.random() * 6)
            phase = 2 * np.pi * ff * t + vib * 40                                # leichtes Vibrato ueber die Phase
            welle = np.zeros(n, np.float32)
            for k in range(1, 12):
                if ff * k > 8000:
                    break
                welle += np.sin(k * phase) / k
            aus[:, seite] += welle
    aus = _tiefpass(aus, hell, 1.5)
    huelle = np.minimum(1, t / 1.4) * np.minimum(1, (dauer - t) / 1.2)
    return (aus * np.clip(huelle, 0, 1)[:, None] / max(1, len(freqs))).astype(np.float32)


def bass(f: float, dauer: float) -> np.ndarray:
    t = np.arange(int(dauer * RATE)) / RATE
    ton = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * f * 2 * t)
    return (ton * np.minimum(1, t / 0.08) * np.minimum(1, (dauer - t) / 0.4)).astype(np.float32)


def kick(dauer: float = 0.45) -> np.ndarray:
    t = np.arange(int(dauer * RATE)) / RATE
    f = 45 + 75 * np.exp(-t * 30)
    return (np.sin(2 * np.pi * np.cumsum(f) / RATE) * np.exp(-t * 9)).astype(np.float32)


def hihat(rng, dauer: float = 0.08) -> np.ndarray:
    x = rng.standard_normal(int(dauer * RATE)).astype(np.float32)
    x = _tiefpass(_hochpass(x, 6000), 10000, 1.5)          # weich, nicht zischend
    return x * np.exp(-np.arange(len(x)) / RATE * 70)


def snare(rng, dauer: float = 0.25) -> np.ndarray:
    t = np.arange(int(dauer * RATE)) / RATE
    rausch = _hochpass(rng.standard_normal(len(t)).astype(np.float32), 1800) * np.exp(-t * 18)
    ton = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return (0.7 * rausch + 0.5 * ton).astype(np.float32)


# ---------------------------------------------------------------------------
# Echte Instrumente aus der Klang-Bank
# ---------------------------------------------------------------------------
KLAENGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "klaenge")


@lru_cache(maxsize=1)
def _index() -> dict:
    with open(os.path.join(KLAENGE, "index.json")) as f:
        return json.load(f)


@lru_cache(maxsize=None)
def _bank(name: str) -> np.ndarray:
    import imageio_ffmpeg
    roh = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", os.path.join(KLAENGE, _index()[name]["datei"]),
                          "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"], capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(roh, np.float32)


def bereit() -> bool:
    try:
        return all(os.path.exists(os.path.join(KLAENGE, v["datei"])) for v in _index().values())
    except Exception:
        return False


def ton(instrument: str, midi: float, dauer: float | None = None, ausklang: float = 0.3) -> np.ndarray:
    """Ein Ton eines echten Instruments: naechste Aufnahme, auf die Tonhoehe umgerechnet, auf Laenge gebracht."""
    noten = _index()[instrument]["noten"]
    n = min(noten, key=lambda k: abs(k["midi"] - midi))
    roh = _bank(instrument)[n["start"]: n["start"] + n["laenge"]]
    faktor = 2 ** ((midi - n["midi"]) / 12)
    if abs(faktor - 1) > 1e-4:
        pos = np.arange(int(len(roh) / faktor)) * faktor
        roh = np.interp(pos, np.arange(len(roh)), roh).astype(np.float32)
    if dauer is not None and len(roh) > int(dauer * RATE):
        roh = roh[: int(dauer * RATE)].copy()
        k = min(len(roh), int(ausklang * RATE))
        roh[-k:] *= np.linspace(1, 0, k) ** 1.5
    return roh


def _hz_midi(grund_midi: float, halbton: float) -> float:
    return grund_midi + halbton


def _lage(ton_h: int, tief: float, hoch: float, grund: float) -> float:
    """Akkordton (Halbtoene ueber dem Grundton) in die gewuenschte Lage legen."""
    m = grund + ton_h
    while m < tief:
        m += 12
    while m > hoch:
        m -= 12
    return m


def _motiv(rng, laenge: int) -> list[tuple[float, int, float]]:
    """Kleines Motiv fuer einen Takt: (Schlag, Richtung, Laenge in Schlaegen). Kehrt in jedem Takt wieder."""
    rhythmen = [[0, 1.5, 2, 3], [0.5, 1, 2.5], [0, 1, 1.5, 2.5], [0, 2, 3, 3.5], [1, 1.5, 2, 3]]
    r = rhythmen[int(rng.integers(len(rhythmen)))][:laenge + 1]
    schritte = [int(rng.choice([-2, -1, -1, 1, 1, 2, 0])) for _ in r]
    return [(b, schritte[i], (r[i + 1] - b) if i + 1 < len(r) else 4 - b) for i, b in enumerate(r)]


def _melodie_toene(akkord, leiter, grund, tief, hoch, start_ton, motiv, rng):
    """Motiv auf den Akkord legen: erster Ton ein Akkordton nahe dem letzten, dann schrittweise in der Tonleiter."""
    kandidaten = sorted({_lage(h % 12, tief, hoch, grund) for h in akkord} |
                        {_lage(h % 12, tief, hoch, grund) + 12 for h in akkord if _lage(h % 12, tief, hoch, grund) + 12 <= hoch})
    aktuell = min(kandidaten, key=lambda m: abs(m - start_ton))
    leiter_toene = sorted({grund + h + 12 * o for h in leiter for o in range(-2, 4) if tief - 2 <= grund + h + 12 * o <= hoch + 2})
    toene = []
    for i, (_, schritt, _) in enumerate(motiv):
        if i > 0 and schritt:
            j = min(range(len(leiter_toene)), key=lambda k: abs(leiter_toene[k] - aktuell))
            aktuell = leiter_toene[max(0, min(len(leiter_toene) - 1, j + schritt))]
        toene.append(aktuell)
    return toene


def _band_leiern(x: np.ndarray, rng) -> np.ndarray:
    """Lofi: ganz leichtes Leiern wie bei einem alten Band (Tonhoehe schwankt um ~0,15 %)."""
    n = x.shape[0]
    t = np.arange(n) / RATE
    pos = (t + 0.0016 * np.sin(2 * np.pi * 0.55 * t + rng.random() * 6) / (2 * np.pi * 0.55)) * RATE
    pos = np.clip(pos, 0, n - 1)
    return np.stack([np.interp(pos, np.arange(n), x[:, c]) for c in range(2)], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# Das Stueck
# ---------------------------------------------------------------------------
STIMMUNG = {   # Tempo, Hall-Laenge, Hall-Anteil
    "himmlisch": (74, 3.4, 0.5), "romantisch": (68, 2.6, 0.38), "mystisch": (62, 4.2, 0.55), "lofi": (80, 1.6, 0.25),
}


def stueck(dauer: float, einsaetze: list[float] | None = None, seed: int = 1, stil: str | None = None) -> np.ndarray:
    rng = np.random.default_rng(int(seed) * 7919 + 13)
    stil = stil if stil in STILE else STILE[int(seed) % len(STILE)]
    n = int(dauer * RATE)
    hallig = np.zeros((n, 2), np.float32)        # wird verhallt
    direkt = np.zeros((n, 2), np.float32)        # Beat, tiefer Bass
    grund = 48 + int(rng.integers(0, 10))        # Tonart C .. A
    moll = stil == "mystisch" or (stil not in ("romantisch",) and rng.random() < 0.3)
    folgen = MOLL_FOLGEN if moll else DUR_FOLGEN
    folge = folgen[int(rng.integers(len(folgen)))]
    leiter = (MODI["dorisch" if rng.random() < 0.5 else "aeolisch"] if moll else [0, 2, 4, 5, 7, 9, 11])
    tempo, hall_s, nass = STIMMUNG[stil]
    schlag = 60 / (tempo + int(rng.integers(-3, 4)))
    takt = 4 * schlag
    takte = int(np.ceil(dauer / takt)) + 1
    motiv = _motiv(rng, 3)
    mel_ton = grund + 19 + (0 if stil != "romantisch" else 5)
    mensch = lambda: float(rng.normal(0, 0.008))        # kleine Ungenauigkeit wie beim Spielen
    staerke = lambda g: g * float(rng.uniform(0.82, 1.0))

    def spiele(buf, zeit, instr, midi, gain, pan=0.5, laenge=None, ausklang=0.3):
        _platz(buf, zeit + mensch(), ton(instr, midi, laenge, ausklang), pan, staerke(gain))

    def streicher(zeit, akkord, laenge, gain, tief=55, hoch=74, celli=True):
        for k, h in enumerate(akkord[:4]):
            m = _lage(h, tief, hoch, grund)
            ts = ton("violinen", m, laenge + 0.9, 0.9)
            ts[: int(0.25 * RATE)] *= np.linspace(0, 1, int(0.25 * RATE)) ** 2      # weich einsetzen
            _platz(hallig, zeit, ts, 0.2 + 0.6 * (k % 2), gain)
        if celli:
            tc = ton("celli", _lage(akkord[0], 36, 50, grund), laenge + 0.9, 0.9)
            tc[: int(0.2 * RATE)] *= np.linspace(0, 1, int(0.2 * RATE))
            _platz(hallig, zeit, tc, 0.45, gain * 1.3)

    for tk in range(takte):
        start = tk * takt
        if start >= dauer:
            break
        akkord = folge[tk % len(folge)]
        letzter = start + takt >= dauer - 0.5
        voll = 0 < tk and not letzter                       # Takt 1 ruhig, dann voll, am Ende Ausklang

        if stil == "himmlisch":
            muster = [0, 1, 2, 3, 4, 3, 2, 1] if tk % 2 == 0 else [0, 2, 1, 3, 2, 4, 3, 2]
            for i, stufe in enumerate(muster):
                h = akkord[stufe % len(akkord)] + 12 * (stufe // len(akkord))
                spiele(hallig, start + i * schlag / 2, "harfe", _lage(h, 55, 79, grund) + (12 if stufe >= len(akkord) else 0),
                       0.30 if i % 4 == 0 else 0.22, 0.3 + 0.4 * (i % 2))
            spiele(hallig, start, "harfe", _lage(akkord[0], 40, 52, grund), 0.32, 0.45)
            streicher(start, akkord, takt, 0.10 if tk == 0 else 0.15, celli=tk > 0)
            if voll:
                toene = _melodie_toene(akkord, leiter, grund, 72, 88, mel_ton, motiv, rng)
                for (b, _, l), m in zip(motiv, toene):
                    spiele(hallig, start + b * schlag, "floete", m, 0.11, 0.6, l * schlag + 0.3, 0.4)
                mel_ton = toene[-1]

        elif stil == "romantisch":
            # linke Hand: Grundton + gebrochener Akkord in Achteln; rechte Hand: Motiv mit Akkord darunter
            bass_m = _lage(akkord[0], 38, 50, grund)
            linke = [bass_m] + [_lage(h, 52, 64, grund) for h in akkord[1:]] + [_lage(akkord[0], 52, 64, grund) + 12]
            for i, stufe in enumerate([0, 1, 2, 3, 1, 2, 3, 2]):
                spiele(hallig, start + i * schlag / 2, "klavier", linke[stufe % len(linke)], 0.26 if i == 0 else 0.16,
                       0.4, takt * 0.9, 0.5)
            if tk > 0 or rng.random() < 0.5:
                toene = _melodie_toene(akkord, leiter, grund, 67, 84, mel_ton, motiv, rng)
                for (b, _, l), m in zip(motiv, toene):
                    spiele(hallig, start + b * schlag, "klavier", m, 0.36, 0.58, l * schlag + 1.2, 0.6)
                mel_ton = toene[-1]
            if tk > 0:
                streicher(start, akkord, takt, 0.09 if not voll else 0.12, 57, 72, celli=voll)

        elif stil == "mystisch":
            if tk % 2 == 0:                                  # Bordun: Celli Grundton + Quinte, lang
                for h in (0, 7):
                    tc = ton("celli", _lage(h, 36, 50, grund), 2 * takt + 1.0, 1.0)
                    tc[: int(0.6 * RATE)] *= np.linspace(0, 1, int(0.6 * RATE))
                    _platz(hallig, start, tc, 0.4 + 0.2 * (h > 0), 0.08)
            pos = 0.0
            while pos < takt:
                h = leiter[int(rng.integers(len(leiter)))]
                instr = "kalimba" if rng.random() < 0.65 else "handglocken"
                spiele(hallig, start + pos, instr, _lage(h, 62 if instr == "kalimba" else 67, 84, grund),
                       0.25 if instr == "kalimba" else 0.14, float(rng.uniform(0.2, 0.8)))
                pos += schlag * float(rng.choice([0.5, 0.5, 1.0, 1.5]))
            if voll and tk % 2 == 1:
                toene = _melodie_toene(akkord, leiter, grund, 69, 84, mel_ton, motiv[:3], rng)
                for (b, _, l), m in zip(motiv[:3], toene):
                    spiele(hallig, start + b * schlag, "floete", m, 0.10, 0.65, l * schlag + 0.6, 0.6)
                mel_ton = toene[-1]

        else:   # lofi
            for i, versatz in ((0, 0.0), (2.5, 0.03)):
                for k, h in enumerate(akkord):
                    spiele(hallig, start + i * schlag + versatz + k * 0.018, "klavier", _lage(h, 55, 70, grund),
                           0.17, 0.4 + 0.06 * k, 1.6 * schlag, 0.4)
            if tk > 0:
                toene = _melodie_toene(akkord, leiter, grund, 70, 86, mel_ton, motiv, rng)
                for (b, _, l), m in zip(motiv, toene):
                    spiele(hallig, start + b * schlag + 0.03, "vibraphon", m, 0.20, 0.62, l * schlag + 0.8, 0.5)
                mel_ton = toene[-1]
            _platz(direkt, start, bass(440 * 2 ** ((_lage(akkord[0], 33, 45, grund) - 69) / 12), takt), 0.5, 0.035)
            if voll:
                for i in range(8):
                    swing = 0.05 if i % 2 else 0.0
                    p = start + i * schlag / 2 + swing
                    if i in (0, 3, 5):
                        _platz(direkt, p, _tiefpass(kick(), 2500), 0.5, 0.07 if i != 3 else 0.04)
                    if i in (2, 6):
                        _platz(direkt, p, _tiefpass(snare(rng), 3500), 0.55, 0.05)
                    _platz(direkt, p + mensch(), ton("shaker", i % 2), 0.65, 0.09 if i % 2 else 0.13)

        if stil != "lofi" and tk > 0:                        # tiefer, weicher Grundton unter allem
            _platz(direkt, start, bass(440 * 2 ** ((_lage(akkord[0], 33, 45, grund) - 69) / 12), takt), 0.5, 0.022)

    # Glocke bei jedem neuen Text, in der Tonart (Glockenspiel hell, Handglocke weich im Wechsel)
    for j, s in enumerate(einsaetze or []):
        h = [0, 4, 7, 9, 12][int(rng.integers(5))] if not moll else [0, 3, 7, 10, 12][int(rng.integers(5))]
        if j % 2 == 0:
            spiele(hallig, s, "glockenspiel", _lage(h, 84, 96, grund), 0.09, 0.3 + 0.4 * (j % 4 == 0))
        else:
            spiele(hallig, s, "handglocken", _lage(h, 76, 88, grund), 0.12, 0.7)

    if stil == "lofi":                                       # leises, dumpfes Knistern
        knistern = np.zeros(n, np.float32)
        orte = rng.integers(0, n, int(dauer * 10))
        knistern[orte] = rng.uniform(-1, 1, len(orte)).astype(np.float32)
        direkt += (_tiefpass(_hochpass(knistern, 1200), 5000, 1.0) * 0.012)[:, None]

    hall = _hall(hallig, hall_s, rng, 7000)
    mix = hallig * (1 - nass * 0.5) + hall * nass + direkt
    if stil == "lofi":
        mix = _band_leiern(_tiefpass(mix, 7000, 1.0), rng)
    mix = _hochpass(mix, 35)
    if stil != "lofi":                                       # etwas "Luft" in den Hoehen (sanfte Anhebung ab ~5 kHz)
        mix = mix + 0.5 * _hochpass(mix, 5000)
    t = np.arange(n) / RATE
    mix *= np.clip(np.minimum(t / 0.4, (dauer - t) / 1.8), 0, 1)[:, None]        # rein und sanft raus
    mix = np.tanh(mix * 1.4) / 1.4                                               # weiche Begrenzung
    rms = float(np.sqrt(np.mean(mix ** 2))) or 1.0
    mix *= min(0.16 / rms, 0.89 / (float(np.abs(mix).max()) or 1.0))            # etwa -16 dB RMS, Spitze < -1 dB
    return (np.clip(mix, -1, 1) * 32767).astype(np.int16)
