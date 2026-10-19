"""
Bilder, Reel-Videos und das Wochenpaket

- hole_bild(post, format): JPEG (aus dem Zwischenspeicher, sonst neu gezeichnet)
- video_stand(post) / video_anfordern(post): Reels rendern im Hintergrund (eins nach
  dem anderen, das schont den Server), das Dashboard fragt den Stand ab
- wochenpaket_starten(...): alle Posts eines Zeitraums als ZIP (Bilder, Videos,
  Texte zum Kopieren, Uebersicht) -- zum Einplanen in der Meta Business Suite & Co.

Der Zwischenspeicher (Tabelle soraya_medien) haengt am "Fingerabdruck" eines Posts:
aendert sich Text, Titel oder Mond, wird neu gezeichnet.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import date, timedelta

import db
import medien
import reel
from wirkung import link_basis

BILD_VERSION = "bild-4"
_RENDER = threading.Lock()          # hoechstens ein schwerer Auftrag (Video) gleichzeitig
_VIDEOS: dict[int, dict] = {}
_PAKETE: dict[str, dict] = {}
_SPERRE = threading.Lock()
EXPORT_ORDNER = os.path.join(tempfile.gettempdir(), "soraya-export")
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
ART_NAME = {"post": "Feed-Post", "reel": "Reel", "story": "Story"}


def _fingerabdruck(post: dict, art: str) -> str:
    felder = {k: post.get(k) for k in ("id", "art", "sprache", "titel", "untertitel", "text", "meta", "skript")}
    version = reel.VERSION if art == "reel" else BILD_VERSION
    roh = json.dumps([version, art, felder], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()


def hole_bild(post: dict, format: str | None = None) -> bytes:
    format = format if format in ("feed", "story") else medien.standard_format(post)
    fp = _fingerabdruck(post, format)
    try:
        daten = db.lade_medium(post["id"], format, fp)
    except Exception:
        daten = None
    if daten:
        return daten
    daten = medien.als_bytes(medien.bild(post, format))
    try:
        db.speichere_medium(post["id"], format, fp, "image/jpeg", daten)
    except Exception as e:  # Speichern ist nur ein Zwischenspeicher
        print(f"[Medien] Bild nicht gespeichert: {e}", flush=True)
    return daten


def hole_folie(post: dict, nr: int) -> bytes:
    """Bild nr des Karussells (1 = Titelbild = normales Feed-Bild), mit Zwischenspeicher."""
    if nr <= 1:
        return hole_bild(post, "feed")
    art = f"folie{nr}"
    fp = _fingerabdruck(post, art)
    try:
        daten = db.lade_medium(post["id"], art, fp)
    except Exception:
        daten = None
    if daten:
        return daten
    daten = medien.als_bytes(medien.folie(post, nr))
    try:
        db.speichere_medium(post["id"], art, fp, "image/jpeg", daten)
    except Exception as e:
        print(f"[Medien] Folie nicht gespeichert: {e}", flush=True)
    return daten


def hole_karussell(post: dict) -> list[bytes]:
    """Alle Bilder eines Feed-Posts (ohne Karussell: nur das Titelbild)."""
    return [hole_folie(post, nr) for nr in range(1, medien.anzahl_bilder(post) + 1)]


def vorschau(jpeg: bytes, breite: int = 300) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(jpeg))
    img = img.resize((breite, round(img.height * breite / img.width)), Image.LANCZOS)
    puffer = io.BytesIO()
    img.save(puffer, "JPEG", quality=80, optimize=True)
    return puffer.getvalue()


def hole_video(post: dict) -> bytes | None:
    """Fertiges Video aus dem Zwischenspeicher (oder None)."""
    return db.lade_medium(post["id"], "reel", _fingerabdruck(post, "reel"))


def _rendere_video(post: dict) -> bytes:
    fp = _fingerabdruck(post, "reel")
    vorhanden = db.lade_medium(post["id"], "reel", fp)
    if vorhanden:
        return vorhanden
    with _RENDER:
        daten = reel.als_bytes(post)
    db.speichere_medium(post["id"], "reel", fp, "video/mp4", daten)
    return daten


def video_stand(post: dict) -> dict:
    if hole_video(post):
        return {"status": "fertig"}
    job = _VIDEOS.get(post["id"])
    if job and job.get("fingerabdruck") == _fingerabdruck(post, "reel"):
        return {k: v for k, v in job.items() if k != "fingerabdruck"} | {
            "vergangen_sekunden": int(time.time() - job["start"])}
    return {"status": "keiner"}


def video_anfordern(post: dict) -> dict:
    stand = video_stand(post)
    if stand["status"] in ("fertig", "laeuft"):
        return stand
    fp = _fingerabdruck(post, "reel")
    _VIDEOS[post["id"]] = {"status": "laeuft", "start": time.time(), "fingerabdruck": fp, "erwartet_sekunden": 25}

    def lauf():
        try:
            _rendere_video(post)
            _VIDEOS[post["id"]].update(status="fertig")
        except Exception as e:  # noqa: BLE001 -- Fehler sieht man im Dashboard
            print(f"[Medien] Video {post['id']} fehlgeschlagen: {e}", flush=True)
            _VIDEOS[post["id"]].update(status="fehler", fehler=str(e)[:300])
    threading.Thread(target=lauf, name=f"reel-{post['id']}", daemon=True).start()
    return video_stand(post)


# ---------------------------------------------------------------------------
# Wochenpaket
# ---------------------------------------------------------------------------
def _beschriftung(post: dict) -> str:
    teile = [post.get("text") or ""]
    if post.get("hashtags"):
        teile.append(post["hashtags"])
    return "\n\n".join(t.strip() for t in teile if t and t.strip()) + "\n"


def _textdatei(post: dict) -> str:
    link = f"{link_basis()}?q=p{post['id']}&lang={post.get('sprache') or 'en'}"
    zeilen = [f"{ART_NAME.get(post.get('art'), 'Post')} · {(post.get('platform') or '').title()} · "
              f"{(post.get('sprache') or 'de').upper()} · {post.get('geplant_fuer')}",
              f"Titel: {post.get('titel') or ''}", "",
              "=== Text zum Kopieren ===", _beschriftung(post).rstrip(), "",
              f"Link (für Story-Link-Sticker oder Bio, wird unter „Wirkung“ gezählt): {link}"]
    sk = post.get("skript") or {}
    if post.get("art") == "reel" and (sk.get("hook") or sk.get("szenen")):
        zeilen += ["", "=== Skript (falls du selbst filmen willst) ===", f"Hook: {sk.get('hook') or ''}"]
        zeilen += [f"{i}. {s}" for i, s in enumerate(sk.get("szenen") or [], 1)]
        zeilen.append(f"Schluss: {sk.get('schluss') or ''}")
    return "\n".join(zeilen) + "\n"


LIES_MICH = """Soraya – Wochenpaket
====================

Pro Tag ein Ordner, darin pro Sprache:
  1 Feed-Post  -> Bild (.jpg) + Text (.txt); als Karussell mehrere Bilder (_1, _2, ...),
                  in dieser Reihenfolge hochladen
  2 Reel       -> Video (.mp4, mit ruhiger Klangfläche) + Text (.txt); in Instagram/TikTok
                  kannst du einen Trend-Sound darüberlegen
  3 Story      -> Bild (.jpg) + Text (.txt), z. B. mit Umfrage-Sticker

So planst du die Woche in der Meta Business Suite (business.facebook.com):
  Planer -> Beitrag erstellen -> Bild/Video hochladen -> Text aus der .txt einfügen
  -> Datum und Uhrzeit wählen -> Planen. Für Reels: "Reel erstellen".

uebersicht.csv zeigt alle Posts auf einen Blick (öffnet sich in Excel).
Nach dem Posten im Dashboard auf "Gepostet" setzen, dann zählt "Wirkung" richtig.
"""


def _paket_bauen(job: dict, posts: list[dict], von: date, bis: date) -> None:
    os.makedirs(EXPORT_ORDNER, exist_ok=True)
    pfad = os.path.join(EXPORT_ORDNER, f"{job['id']}.zip")
    wurzel = f"Soraya-Woche_{von.isoformat()}_bis_{bis.isoformat()}"
    uebersicht = io.StringIO()
    tabelle = csv.writer(uebersicht, delimiter=";")
    tabelle.writerow(["Datum", "Wochentag", "Sprache", "Art", "Plattform", "Status", "Titel", "Datei"])
    with zipfile.ZipFile(pfad, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{wurzel}/LIES-MICH.txt", LIES_MICH)
        for i, p in enumerate(posts):
            tag = p["geplant_fuer"]
            ordner = f"{wurzel}/{tag.isoformat()}_{WOCHENTAGE[tag.weekday()]}"
            nr = {"post": 1, "reel": 2, "story": 3}.get(p.get("art"), 4)
            name = f"{(p.get('sprache') or 'de').upper()}_{nr}_{ART_NAME.get(p.get('art'), 'Post')}"
            job["schritt"] = f"{tag.strftime('%d.%m.')} {(p.get('sprache') or 'de').upper()} {ART_NAME.get(p.get('art'), 'Post')}"
            if p.get("art") == "reel" and job["mit_videos"]:
                datei = f"{ordner}/{name}.mp4"
                z.writestr(datei, _rendere_video(p), compress_type=zipfile.ZIP_STORED)
            elif p.get("art") == "post" and medien.anzahl_bilder(p) > 1:
                for i, daten in enumerate(hole_karussell(p), start=1):
                    datei = f"{ordner}/{name}_{i}.jpg"
                    z.writestr(datei, daten, compress_type=zipfile.ZIP_STORED)
                datei = f"{ordner}/{name}_1.jpg"
            else:
                datei = f"{ordner}/{name}.jpg"
                z.writestr(datei, hole_bild(p), compress_type=zipfile.ZIP_STORED)
            z.writestr(f"{ordner}/{name}.txt", _textdatei(p))
            tabelle.writerow([tag.isoformat(), WOCHENTAGE[tag.weekday()], (p.get("sprache") or "de").upper(),
                              ART_NAME.get(p.get("art"), "Post"), p.get("platform") or "", p.get("status") or "",
                              p.get("titel") or "", datei.split("/", 1)[1]])
            job["fertig"] = i + 1
        z.writestr(f"{wurzel}/uebersicht.csv", "﻿" + uebersicht.getvalue())
    job.update(status="fertig", datei=pfad, dateiname=f"{wurzel}.zip", ende=time.time(),
               groesse_mb=round(os.path.getsize(pfad) / 1e6, 1))


def _aufraeumen() -> None:
    jetzt = time.time()
    for jid, job in list(_PAKETE.items()):
        if jetzt - job["start"] > 3 * 3600:
            if job.get("datei") and os.path.exists(job["datei"]):
                os.remove(job["datei"])
            _PAKETE.pop(jid, None)


def wochenpaket_starten(von: date, tage: int, sprachen: list[str], status: list[str], mit_videos: bool = True) -> dict:
    _aufraeumen()
    tage = max(1, min(int(tage), 14))
    bis = von + timedelta(days=tage - 1)
    posts = db.lade_posts_zeitraum(von, bis, sprachen=sprachen or None, status=status or None)
    if not posts:
        return {"status": "leer", "von": von, "bis": bis}
    with _SPERRE:
        if any(j["status"] == "laeuft" for j in _PAKETE.values()):
            raise RuntimeError("Es wird gerade schon ein Paket erstellt.")
        job = {"id": uuid.uuid4().hex[:12], "status": "laeuft", "start": time.time(), "gesamt": len(posts),
               "fertig": 0, "schritt": "", "mit_videos": mit_videos,
               "videos": sum(1 for p in posts if p.get("art") == "reel") if mit_videos else 0}
        _PAKETE[job["id"]] = job

    def lauf():
        try:
            _paket_bauen(job, posts, von, bis)
        except Exception as e:  # noqa: BLE001
            print(f"[Paket] Fehler: {e}", flush=True)
            job.update(status="fehler", fehler=str(e)[:300], ende=time.time())
    threading.Thread(target=lauf, name=f"paket-{job['id']}", daemon=True).start()
    return paket_stand(job["id"])


def paket_stand(job_id: str) -> dict | None:
    job = _PAKETE.get(job_id)
    if not job:
        return None
    return {k: job.get(k) for k in ("id", "status", "gesamt", "fertig", "schritt", "videos", "fehler",
                                    "dateiname", "groesse_mb")} | {
        "vergangen_sekunden": int((job.get("ende") or time.time()) - job["start"])}


def paket_datei(job_id: str) -> tuple[str, str] | None:
    job = _PAKETE.get(job_id)
    if not job or job["status"] != "fertig" or not os.path.exists(job.get("datei") or ""):
        return None
    return job["datei"], job["dateiname"]
