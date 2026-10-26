"""
Baut die Klang-Bank fuer musik.py aus echten Instrument-Aufnahmen (einmalig, nicht auf dem Server).

Quellen (beide CC0 = gemeinfrei, auch kommerziell frei, keine Namensnennung noetig):
  Versilian Community Sample Library  https://github.com/sgossner/VCSL
  VSCO 2 Community Edition            https://github.com/sgossner/VSCO-2-CE

Je Instrument wird jede Note mono auf 48 kHz gebracht, die Stille am Anfang entfernt, gekuerzt, ausgeblendet,
auf gleiche Lautstaerke gebracht und mit Luecken hintereinander in eine Opus-Datei geschrieben
(klaenge/<instrument>.opus); klaenge/index.json merkt sich je Note Startpunkt und Laenge.

  python3 tools/klaenge_bauen.py /pfad/zu/vcsl /pfad/zu/vsco
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

import numpy as np

RATE = 48000
LUECKE = int(0.25 * RATE)
ZIEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "klaenge")
NOTEN = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}

# Name: (Quelle, Muster, hoechstens Sekunden, tiefste/hoechste Note als MIDI, Bitrate)
INSTRUMENTE = {
    "klavier": ("vcsl", "Chordophones/Zithers/Grand Piano, Kawai/Sustains/GPiano_sus_*_v2_rr1_Player.wav", 6.0, 40, 96, "72k"),
    "harfe": ("vcsl", "Chordophones/Composite Chordophones/Concert Harp/KSHarp_*_mf*.wav", 4.5, 40, 100, "64k"),
    "vibraphon": ("vcsl", "Idiophones/Struck Idiophones/Vibraphone/Soft Mallets/*_v1_*.wav", 5.0, 0, 127, "56k"),
    "kalimba": ("vcsl", "Idiophones/Plucked Idiophones/Kalimba, Tanzania/*.wav", 3.0, 48, 127, "56k"),
    "handglocken": ("vcsl", "Idiophones/Struck Idiophones/Hand Chimes/*.wav", 4.0, 0, 127, "56k"),
    "glockenspiel": ("vcsl", "Idiophones/Struck Idiophones/Glockenspiel/glock_soft_*.wav", 3.0, 0, 127, "56k"),
    "shaker": ("vcsl", "Idiophones/Struck Idiophones/Shaker, Small/Mid_ShakerDouble_*_rr1.wav", 0.45, None, None, "48k"),
    "violinen": ("vsco", "Strings/Violin Section/susVib/*_v1.wav", 7.0, 0, 127, "64k"),
    "celli": ("vsco", "Strings/Cello Section/susvib/*_v1_1.wav", 7.0, 36, 127, "64k"),
    "floete": ("vsco", "Woodwinds/Flute/susvib/*_v1_1.wav", 6.0, 0, 127, "56k"),
}


# Die Dateinamen zaehlen die Oktaven unterschiedlich (meist C3 = eingestrichenes C); gemessen nachgeprueft
OKTAVE = {"harfe": 0}


def tonhoehe(x: np.ndarray, fmin: float = 60, fmax: float = 4200) -> float:
    """Grundton in Hz (YIN-Verfahren) aus einem Stueck kurz nach dem Anschlag."""
    seg = x[int(0.1 * RATE): int(0.1 * RATE) + 4096].astype(np.float64)
    w = len(seg) // 2
    taus = np.arange(int(RATE / fmax), int(RATE / fmin))
    d = np.array([np.sum((seg[:w] - seg[t:t + w]) ** 2) for t in taus])
    cm = d * np.arange(1, len(d) + 1) / (np.cumsum(d) + 1e-12)
    unter = np.where(cm < 0.15)[0]
    i = int(unter[0]) if len(unter) else int(np.argmin(cm))
    while i + 1 < len(cm) and cm[i + 1] < cm[i]:
        i += 1
    return RATE / taus[i]


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def note_aus_name(name: str) -> int | None:
    m = re.search(r"_([A-G]#?)(-?\d)_", name + "_")
    if not m:
        return None
    return 12 * (int(m.group(2)) + 1) + NOTEN[m.group(1)]


def lade(pfad: str, laenge: float) -> np.ndarray:
    roh = subprocess.run([ffmpeg(), "-v", "error", "-i", pfad, "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(roh, np.float32).copy()
    # Stille am Anfang weg (relativ zur Spitze, die Aufnahmen sind unterschiedlich laut), 3 ms Luft lassen
    erster = int(np.argmax(np.abs(x) > np.abs(x).max() * 0.03))
    x = x[max(0, erster - int(0.003 * RATE)):][: int(laenge * RATE)]
    aus = min(len(x), int(0.35 * RATE))
    x[-aus:] *= np.linspace(1, 0, aus) ** 2
    return x


def main(vcsl: str, vsco: str) -> None:
    os.makedirs(ZIEL, exist_ok=True)
    index = {}
    for name, (quelle, muster, laenge, tief, hoch, rate) in INSTRUMENTE.items():
        dateien = sorted(glob.glob(os.path.join(vcsl if quelle == "vcsl" else vsco, muster)))
        teile, noten, pos = [], [], 0
        for i, d in enumerate(dateien):
            midi = note_aus_name(os.path.basename(d))
            if tief is not None and (midi is None or not tief <= midi + OKTAVE.get(name, 12) <= hoch):
                continue
            x = lade(d, laenge)
            if tief is not None:
                midi += OKTAVE.get(name, 12)
                gemessen = 69 + 12 * np.log2(tonhoehe(x) / 440)
                if abs(gemessen - midi) <= (0.7 if name == "kalimba" else 0.25):
                    midi = round(float(gemessen), 2)      # Feinstimmung der Aufnahme mitnehmen
                elif name == "kalimba":
                    continue                              # Kalimba-Zungen ohne klaren Ton weglassen
            # gleiche Lautstaerke: Effektivwert der ersten halben Sekunde
            kopf = x[: RATE // 2]
            x *= 0.12 / (float(np.sqrt(np.mean(kopf ** 2))) or 1.0)
            x *= min(1.0, 0.95 / (float(np.abs(x).max()) or 1.0))
            noten.append({"midi": midi if tief is not None else i, "start": pos, "laenge": len(x)})
            teile += [x, np.zeros(LUECKE, np.float32)]
            pos += len(x) + LUECKE
        alles = np.concatenate(teile)
        datei = os.path.join(ZIEL, f"{name}.opus")
        subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "-",
                        "-c:a", "libopus", "-b:a", rate, "-application", "audio", datei],
                       input=alles.astype(np.float32).tobytes(), check=True)
        index[name] = {"datei": f"{name}.opus", "noten": sorted(noten, key=lambda n: n["midi"])}
        print(f"{name:13s} {len(noten):3d} Noten  {len(alles) / RATE:6.1f} s  {os.path.getsize(datei) // 1024:5d} KB")
    with open(os.path.join(ZIEL, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
