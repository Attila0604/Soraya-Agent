"""
Musik fuer die Reels -- selbst erzeugt (keine fremde Musik, keine Lizenzfragen), aber wie echte Stuecke aufgebaut:
Tonart, Akkordfolge, Tempo, mehrere Instrumente, Hall. Vier Stile je nach Format, und durch den Zufall (seed =
Post-ID) klingt jedes Reel anders: andere Tonart, andere Folge, anderes Muster.

  himmlisch  -- Harfen-Arpeggios ueber einer warmen Flaeche, tiefer Grundton, Sternenglocken (Deine Woche, Wissen)
  romantisch -- weiches Klavier mit Streicherflaeche (Liebe & Beziehung)
  mystisch   -- Bordun, Handpan-artige Toene in einer alten Tonleiter, Luft (Ritual, besondere Tage)
  lofi       -- warmes E-Piano, sanfter Beat, leises Knistern (Mitmachen, Rueckblick)

Nur numpy: Filter und Hall laufen ueber die FFT (die Stuecke sind kurz). Rueckgabe wie reel.klang: int16 [n, 2].
"""

from __future__ import annotations

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
# Das Stueck
# ---------------------------------------------------------------------------
def stueck(dauer: float, einsaetze: list[float] | None = None, seed: int = 1, stil: str | None = None) -> np.ndarray:
    rng = np.random.default_rng(int(seed) * 7919 + 13)
    stil = stil if stil in STILE else STILE[int(seed) % len(STILE)]
    n = int(dauer * RATE)
    trocken = np.zeros((n, 2), np.float32)        # wird verhallt
    direkt = np.zeros((n, 2), np.float32)         # trocken (Bass, Beat)
    grund_name = list(GRUNDTOENE)[int(rng.integers(len(GRUNDTOENE)))]
    grund = GRUNDTOENE[grund_name]
    moll = stil == "mystisch" or (stil != "romantisch" and rng.random() < 0.35)
    folge = (MOLL_FOLGEN if moll else DUR_FOLGEN)[int(rng.integers(len(MOLL_FOLGEN if moll else DUR_FOLGEN)))]
    tempo = {"himmlisch": 72, "romantisch": 66, "mystisch": 60, "lofi": 78}[stil] + int(rng.integers(-4, 5))
    schlag = 60 / tempo
    takt = 4 * schlag
    takte = int(np.ceil(dauer / takt)) + 1

    for tk in range(takte):
        akkord = folge[tk % len(folge)]
        start = tk * takt
        toene = [_hz(grund, h) for h in akkord]
        # Flaeche (alle Stile, bei lofi leiser)
        if start < dauer:
            fl = flaeche([f for f in toene], min(takt + 1.4, dauer - start + 0.5), rng,
                         hell={"himmlisch": 1900, "romantisch": 1400, "mystisch": 1100, "lofi": 1200}[stil])
            g = {"himmlisch": 0.16, "romantisch": 0.2, "mystisch": 0.14, "lofi": 0.09}[stil]
            s = int(start * RATE)
            e = min(n, s + len(fl))
            trocken[s:e] += fl[: e - s] * g
        # Bass: Grundton eine Oktave tiefer
        _platz(direkt, start, bass(_hz(grund, akkord[0] - 12), takt), 0.5, 0.11 if stil != "lofi" else 0.14)

        if stil == "himmlisch":                   # Harfen-Arpeggio in Achteln, aufwaerts und wieder ab
            muster = [0, 1, 2, 3, 2, 1, 2, 3] if rng.random() < 0.5 else [0, 2, 1, 3, 2, 3, 1, 2]
            for i, stufe in enumerate(muster):
                h = akkord[stufe % len(akkord)] + 12 * (1 + (stufe >= len(akkord)))
                _platz(trocken, start + i * schlag / 2, harfe(_hz(grund, h)), 0.3 + 0.4 * (i % 2), 0.07)
        elif stil == "romantisch":                 # Klavier: Akkord in Vierteln, oben eine kleine Melodie
            for i in range(4):
                for k, h in enumerate(akkord[:3]):
                    _platz(trocken, start + i * schlag + k * 0.012, klavier(_hz(grund, h), 2.4, 0.5), 0.45, 0.035)
            mel = sorted(akkord)[-1] + 12
            for i, d in enumerate([0, 2, -1, 0][: 2 + int(rng.integers(3))]):
                _platz(trocken, start + (0.5 + i * 1.5) * schlag, klavier(_hz(grund, mel + d), 3.2, 1.0), 0.6, 0.06)
        elif stil == "mystisch":                   # Handpan in einer alten Tonleiter, frei im Rhythmus
            leiter = MODI["dorisch" if rng.random() < 0.5 else "phrygisch"]
            pos = 0.0
            while pos < takt:
                h = leiter[int(rng.integers(len(leiter)))] + 12 * int(rng.integers(1, 3))
                _platz(trocken, start + pos, handpan(_hz(grund, h)), float(rng.uniform(0.25, 0.75)), 0.08)
                pos += schlag * float(rng.choice([0.5, 1.0, 1.0, 1.5]))
        else:                                      # lofi: E-Piano-Akkorde leicht verschleppt + Beat
            for i, versatz in ((0, 0.0), (2.5, 0.0)):
                for k, h in enumerate(akkord):
                    _platz(trocken, start + i * schlag + versatz + k * 0.02, epiano(_hz(grund, h + 12)), 0.4 + 0.07 * k, 0.05)
            for i in range(8):                     # Beat erst ab dem 2. Takt (Hook bleibt ruhig)
                if tk == 0:
                    break
                swing = 0.04 if i % 2 else 0.0
                p = start + i * schlag / 2 + swing
                if i in (0, 5):
                    _platz(direkt, p, kick(), 0.5, 0.33)
                if i in (2, 6):
                    _platz(direkt, p, _tiefpass(snare(rng), 5000), 0.55, 0.07)
                _platz(direkt, p, hihat(rng), 0.62, 0.014 if i % 2 else 0.009)

    # Sternenglocke bei jedem neuen Text (wie bisher, jetzt in der Tonart)
    leiter = MODI["pentatonik"] if moll else [0, 2, 4, 7, 9]
    for j, s in enumerate(einsaetze or []):
        h = leiter[int(rng.integers(len(leiter)))] + 24
        _platz(trocken, s, glocke(_hz(grund, h)), 0.3 if j % 2 else 0.7, 0.05)

    # Textur: lofi knistert leise, mystisch hat etwas "Luft"
    if stil == "lofi":
        knistern = np.zeros(n, np.float32)
        orte = rng.integers(0, n, int(dauer * 14))
        knistern[orte] = rng.uniform(-1, 1, len(orte)).astype(np.float32)
        knistern = _tiefpass(_hochpass(knistern, 1500), 6000, 1.0)
        direkt += (knistern * 0.015)[:, None]
    if stil == "mystisch":
        luft = _tiefpass(rng.standard_normal((n, 2)).astype(np.float32), 900, 1.0)
        luft *= (0.5 + 0.5 * np.sin(2 * np.pi * 0.11 * np.arange(n) / RATE))[:, None]
        trocken += luft * 0.04

    hall = _hall(trocken, {"himmlisch": 3.2, "romantisch": 2.4, "mystisch": 4.0, "lofi": 1.4}[stil], rng)
    nass = {"himmlisch": 0.55, "romantisch": 0.35, "mystisch": 0.6, "lofi": 0.25}[stil]
    mix = trocken * (1 - nass * 0.5) + hall * nass + direkt
    mix = _hochpass(mix, 35)
    t = np.arange(n) / RATE
    mix *= np.clip(np.minimum(t / 0.6, (dauer - t) / 1.6), 0, 1)[:, None]        # rein und sanft raus
    mix = np.tanh(mix * 1.6) / 1.6                                                 # weiche Begrenzung
    rms = float(np.sqrt(np.mean(mix ** 2))) or 1.0
    mix *= min(0.16 / rms, 0.89 / (float(np.abs(mix).max()) or 1.0))              # etwa -16 dB RMS, Spitze < -1 dB
    return (np.clip(mix, -1, 1) * 32767).astype(np.int16)
