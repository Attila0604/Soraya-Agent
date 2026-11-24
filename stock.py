"""
Echte Videos als Reel-Hintergrund (Schritt C, Wunsch Attila 24.11.2026).

Quelle: Pixabay oder Pexels (beide frei auch fuer kommerzielle Nutzung, ohne Namensnennung; nur Motive OHNE erkennbare
Menschen: Mond, Sternenhimmel, Kerzen, Meer, Feuer, Wald, Wolken). Der API-Schluessel steht nur in Railway:
  PIXABAY_API_KEY  -- Pixabay (Pexels gibt seit Nov. 2026 keine neuen Schluessel aus)
  PEXELS_API_KEY   -- Pexels (falls vorhanden); ohne beide Schluessel bleibt alles wie bisher (gezeichnete Szenen)
  STOCK_ANTEIL     -- Anteil der Reels mit echtem Video (Standard 0.5 = jedes zweite), 0 = aus
Die Videos werden in STOCK_DIR (Standard /tmp/soraya-stock) zwischengespeichert.
"""
from __future__ import annotations

import os

import requests

API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"

# Suchbegriffe je Farbwelt (reel.welt) -- bewusst ohne Menschen
SUCHEN = {
    "mitternacht": ["full moon night sky", "moon clouds night"],
    "wasser": ["ocean waves night", "water reflection moonlight"],
    "feuer": ["fire embers dark", "candle flame dark"],
    "erde": ["misty forest", "foggy mountains sunrise"],
    "luft": ["clouds timelapse sky", "starry sky timelapse"],
    "gold": ["candle flame dark", "golden bokeh lights"],
    "rose": ["pink sunset clouds", "rose petals dark"],
    "amethyst": ["milky way night sky", "galaxy stars"],
}
STANDARD = ["starry night sky timelapse", "night sky stars"]


def schluessel() -> str:
    return (os.environ.get("PEXELS_API_KEY") or "").strip()


def pixabay_schluessel() -> str:
    return (os.environ.get("PIXABAY_API_KEY") or "").strip()


def anteil() -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get("STOCK_ANTEIL", "0.5"))))
    except ValueError:
        return 0.5


def soll_echt(seed: int) -> bool:
    """Bekommt dieses Reel ein echtes Video? (fest je Post-ID, damit es beim Neu-Erstellen gleich bleibt)"""
    if not schluessel() and not pixabay_schluessel():
        return False
    return (int(seed) * 37 % 100) < anteil() * 100


def beste_datei(video: dict) -> dict | None:
    """Hochformat-Datei mit 1280..2160 Pixel Hoehe (am liebsten ~1920), sonst die groesste brauchbare."""
    dateien = [f for f in video.get("video_files") or [] if f.get("link") and f.get("height") and f.get("width")]
    hoch = [f for f in dateien if f["height"] > f["width"] and 1280 <= f["height"] <= 2160]
    if hoch:
        return min(hoch, key=lambda f: abs(f["height"] - 1920))
    quer = [f for f in dateien if 720 <= min(f["height"], f["width"]) <= 2160]
    return max(quer, key=lambda f: f["height"]) if quer else None


def suche_pixabay(begriff: str, timeout: float = 15) -> list[dict]:
    """Pixabay-Treffer im selben Aufbau wie Pexels ({"id", "duration", "url", "video_files": [...]})."""
    r = requests.get(PIXABAY_API, params={"key": pixabay_schluessel(), "q": begriff, "video_type": "film",
                                          "safesearch": "true", "per_page": 20}, timeout=timeout)
    r.raise_for_status()
    out = []
    for h in (r.json() or {}).get("hits") or []:
        if (h.get("duration") or 0) < 8:
            continue
        dateien = [{"link": v.get("url"), "width": v.get("width"), "height": v.get("height")}
                   for v in (h.get("videos") or {}).values() if v and v.get("url")]
        out.append({"id": f"pb{h.get('id')}", "duration": h.get("duration"), "url": h.get("pageURL"), "video_files": dateien})
    return out


def suche(begriff: str, timeout: float = 15) -> list[dict]:
    if not schluessel():
        return suche_pixabay(begriff, timeout)
    r = requests.get(API, params={"query": begriff, "orientation": "portrait", "size": "medium", "per_page": 15},
                     headers={"Authorization": schluessel()}, timeout=timeout)
    r.raise_for_status()
    return [v for v in (r.json() or {}).get("videos") or [] if (v.get("duration") or 0) >= 8]


def ordner() -> str:
    pfad = os.environ.get("STOCK_DIR") or "/tmp/soraya-stock"
    os.makedirs(pfad, exist_ok=True)
    return pfad


def fuer_reel(post: dict, farbwelt: str) -> dict | None:
    """{"pfad", "id", "quelle"} eines passenden echten Videos -- oder None (dann gezeichnete Szene).
    Fehler (kein Netz, Limit, nichts gefunden) fuehren nie zum Abbruch."""
    seed = int(post.get("id") or 0)
    if not soll_echt(seed):
        return None
    try:
        begriffe = SUCHEN.get(farbwelt, STANDARD)
        videos = suche(begriffe[seed % len(begriffe)])
        if not videos:
            return None
        v = videos[seed % len(videos)]
        datei = beste_datei(v)
        if not datei:
            return None
        pfad = os.path.join(ordner(), f"stock-{v['id']}-{datei.get('height')}.mp4")
        if not os.path.exists(pfad):
            with requests.get(datei["link"], stream=True, timeout=60) as r:
                r.raise_for_status()
                groesse, tmp = 0, pfad + ".teil"
                with open(tmp, "wb") as f:
                    for stueck in r.iter_content(1 << 16):
                        groesse += len(stueck)
                        if groesse > 60 * 1024 * 1024:          # zu gross -> lieber gezeichnet
                            raise ValueError("Video zu gross")
                        f.write(stueck)
                os.replace(tmp, pfad)
        return {"pfad": pfad, "id": v["id"], "quelle": v.get("url") or "pexels"}
    except Exception as e:  # noqa: BLE001
        print(f"[Stock] kein echtes Video: {type(e).__name__}: {str(e)[:120]}", flush=True)
        return None
