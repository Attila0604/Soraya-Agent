"""
Soraya-Agent — Stufe 2
- Tagesplan: jeden Morgen Posts, Reel-Skript und Story aus dem echten Himmel,
  auf Deutsch, Englisch, Ungarisch und Italienisch.
- Redaktionsplan: Posts planen, bearbeiten, freigeben, als gepostet markieren.
- Content-Agent: schreibt Social-Media-Posts zu einem Thema oder aus einer Webseite.
- Recherche: Websuche (Claude), Reddit, Play Store, Webseiten auslesen.
- Zielgruppen-Agent: erstellt Kundenprofile je Bereich.
- Wirkung: App-Zahlen (Summen pro Tag) aus der astro-engine.
- Web-Oberflaeche ("Content Studio") unter "/", Post-Bilder entstehen dort im Browser.
- Zugangsschutz: Browser-Anmeldung (Benutzer + Passwort aus Railway-Variablen).
"""

import base64
import binascii
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from content_agent import erstelle_posts
from research_agent import analysiere_zielgruppe
from webseite import hole_webseiten_text
from websuche import quelle_websuche
from reddit import quelle_reddit
from playstore import quelle_playstore, quelle_playstore_ids
from bereiche import (
    BEREICHE, begriffe_fuer, playstore_suche_fuer, titel_fuer,
)
from db import (
    init_db, speichere_posts, lade_posts, aendere_post, loesche_post,
    lade_post, lade_veroeffentlichungen, setze_meta, speichere_zielgruppe, lade_zielgruppen, setze_zielgruppe_im_tagesplan, lade_tagesplaene, lade_tagesplaene_zeitraum,
)
import cockpit
import db
import himmel
import linkedin
import pinterest
import meta
import paket
import posten
import redaktion
import tagesplan
import tiktok
from sprachen import SPRACHEN, NAMEN, norm
from wirkung import hole_statistik, links as wirkung_links

app = FastAPI(title="Soraya-Agent", version="0.6")

# Ohne Anmeldung erreichbar (Railway-Healthcheck) -- und die signierten Medien,
# die Instagram beim Posten selbst abholt (ohne gueltige Signatur: 404).
# Die App-Dateien (Manifest, Symbole, Service Worker) laedt der Browser ohne Anmeldung -- sie enthalten nichts Vertrauliches
OFFENE_PFADE = {"/health", "/manifest.webmanifest", "/studio-sw.js", "/studio-icon-192.png", "/studio-icon-512.png"}
OFFENE_PRAEFIXE = ("/oeffentlich/medien/",)


def _anmeldung_ok(kopfzeile: str) -> bool:
    """Prueft die Browser-Anmeldung (HTTP Basic) gegen die Railway-Variablen."""
    if not kopfzeile.lower().startswith("basic "):
        return False
    try:
        roh = base64.b64decode(kopfzeile[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    benutzer, _, passwort = roh.partition(":")
    soll_benutzer = os.environ.get("AGENT_BENUTZER", "soraya")
    soll_passwort = os.environ.get("AGENT_PASSWORT", "")
    # timing-sicherer Vergleich; beide Vergleiche laufen immer
    benutzer_ok = secrets.compare_digest(benutzer.encode(), soll_benutzer.encode())
    passwort_ok = secrets.compare_digest(passwort.encode(), soll_passwort.encode())
    return benutzer_ok and passwort_ok


@app.middleware("http")
async def zugangsschutz(request: Request, call_next):
    """Alles ausser OFFENE_PFADE verlangt eine Anmeldung (auch /docs)."""
    if request.url.path in OFFENE_PFADE or request.url.path.startswith(OFFENE_PRAEFIXE):
        return await call_next(request)

    # Ohne gesetztes Passwort bleibt der Agent gesperrt statt offen.
    if not os.environ.get("AGENT_PASSWORT"):
        return JSONResponse(
            status_code=503,
            content={"detail": "Zugangsschutz nicht eingerichtet: Bitte AGENT_PASSWORT "
                               "in Railway unter Variables setzen."},
        )

    if not _anmeldung_ok(request.headers.get("authorization", "")):
        return JSONResponse(
            status_code=401,
            content={"detail": "Anmeldung erforderlich."},
            headers={"WWW-Authenticate": 'Basic realm="Soraya-Agent", charset="UTF-8"'},
        )

    return await call_next(request)


class ContentAnfrage(BaseModel):
    thema: Optional[str] = None
    anzahl: int = 3
    sprache: str = "de"


class UrlAnfrage(BaseModel):
    url: str
    anzahl: int = 3
    sprache: str = "de"


class PostAenderung(BaseModel):
    text: Optional[str] = None
    hashtags: Optional[str] = None
    titel: Optional[str] = None
    untertitel: Optional[str] = None
    status: Optional[str] = None
    platform: Optional[str] = None
    geplant_fuer: Optional[date] = None


class TagesplanAnfrage(BaseModel):
    sprachen: list[str] = []
    neu: bool = False


class VorplanAnfrage(BaseModel):
    tage: int = 7
    sprachen: list[str] = []


class ZielgruppeAnfrage(BaseModel):
    bereich: str
    land: str = "at"
    # Welche Quellen sollen laufen?
    quellen: list[str] = ["websuche"]
    # Eigene Vorgaben — wenn gesetzt, ersetzen sie die vordefinierten
    eigene_begriffe: list[str] = []
    eigene_playstore: str = ""
    eigene_app_ids: list[str] = []
    eigene_frage: str = ""


@app.on_event("startup")
def beim_start():
    try:
        init_db()
    except Exception as e:
        print(f"[Start] Datenbank noch nicht bereit: {e}")
    try:
        if posten.wunsch_zeiten_einmal():
            print("[Start] Posting-Zeiten einmalig gesetzt: 05:00 / 12:00 / 21:00", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[Start] Posting-Zeiten nicht gesetzt: {e}", flush=True)
    posten.zeitplan_starten()
    print(f"[Start] Automatisch posten ist {'AN' if posten.einstellungen()['an'] else 'AUS'}", flush=True)
    if tagesplan.gesperrt():
        print("[Start] Tagesplan-Automatik gesperrt (TAGESPLAN_AUTO=0)", flush=True)
        return
    # Der Zeitplan fragt bei jedem Durchlauf den Schalter im Dashboard ab
    tagesplan.zeitplan_starten()
    print(f"[Start] Tagesplan-Automatik ist {'AN' if tagesplan.automatisch() else 'AUS'} "
          f"(ab {tagesplan.startstunde()} Uhr: {', '.join(tagesplan.sprachen())})", flush=True)


# ---------------------------------------------------------------------------
# Content Studio als App (PWA): am Handy "Zum Startbildschirm" / "App installieren"
# ---------------------------------------------------------------------------
_SYMBOLE: dict = {}


def _studio_symbol(groesse: int) -> bytes:
    if groesse not in _SYMBOLE:
        import io
        from PIL import Image, ImageDraw
        import medien
        bild = Image.new("RGB", (groesse, groesse), (11, 14, 26))
        schein = medien.radial(groesse, groesse, groesse / 2, groesse * 0.45, 0, groesse / 2, groesse * 0.45, groesse * 0.55,
                               [(0, "#2a1650", 1.0), (1, "#0b0e1a", 1.0)])
        bild.paste(schein.convert("RGB"))
        z = medien.portal(int(groesse * 0.52))
        bild.paste(z, (int((groesse - z.width) / 2), int(groesse * 0.42 - z.height / 2)), z)
        # "STUDIO" darunter -- damit es am Handy nicht mit der Soraya-App verwechselt wird
        medien.gesperrt(ImageDraw.Draw(bild), "STUDIO", groesse / 2, groesse * 0.8, medien.schrift("cinzel", groesse * 0.085),
                        groesse * 0.02, (231, 211, 161))
        puffer = io.BytesIO()
        bild.save(puffer, "PNG")
        _SYMBOLE[groesse] = puffer.getvalue()
    return _SYMBOLE[groesse]


@app.get("/studio-icon-192.png")
def studio_icon_192():
    return Response(_studio_symbol(192), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/studio-icon-512.png")
def studio_icon_512():
    return Response(_studio_symbol(512), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/manifest.webmanifest")
def studio_manifest():
    return JSONResponse({
        "name": "Soraya Content Studio", "short_name": "Content Studio", "id": "/", "start_url": "/", "scope": "/",
        "display": "standalone", "background_color": "#0B0E1A", "theme_color": "#0B0E1A", "lang": "de",
        "icons": [{"src": "/studio-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                  {"src": "/studio-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]},
        media_type="application/manifest+json")


@app.get("/studio-sw.js")
def studio_sw():
    # bewusst ohne Zwischenspeicher: immer der aktuelle Stand vom Server (nur damit sich die App installieren laesst)
    js = ("self.addEventListener('install', e => self.skipWaiting());\n"
          "self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));\n"
          "self.addEventListener('fetch', e => {});\n")
    return Response(js, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Liest die Oberflaeche aus dashboard.html."""
    pfad = Path(__file__).parent / "dashboard.html"
    # nie aus dem Zwischenspeicher: nach einem Update sieht man sofort die neue Oberflaeche (auch als installierte App)
    return HTMLResponse(pfad.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/bereiche")
def bereiche():
    return {"bereiche": [{"schluessel": k, "titel": v["titel"]} for k, v in BEREICHE.items()]}


@app.get("/sprachen")
def sprachen_liste():
    return {"sprachen": [{"code": s, "name": NAMEN[s]} for s in SPRACHEN]}


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    try:
        posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl, sprache=norm(anfrage.sprache))
        return {"erstellt": len(posts), "posts": speichere_posts(posts, quelle="studio")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/content-von-url")
def content_von_url(anfrage: UrlAnfrage):
    try:
        text = hole_webseiten_text(anfrage.url)
        posts = erstelle_posts(anzahl=anfrage.anzahl, kontext=text, sprache=norm(anfrage.sprache))
        gespeichert = speichere_posts(posts, quelle="url")
        return {
            "quelle": anfrage.url,
            "gelesen_zeichen": len(text),
            "erstellt": len(gespeichert),
            "posts": gespeichert,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/content")
def content_ansehen(limit: int = 50, von: Optional[date] = None, bis: Optional[date] = None,
                    sprache: Optional[str] = None, status: Optional[str] = None,
                    himmel: Optional[bool] = None):
    try:
        return {"posts": lade_posts(limit=limit, von=von, bis=bis, himmel=himmel,
                                    sprache=norm(sprache) if sprache else None, status=status or None)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/content/{post_id}")
def content_aendern(post_id: int, aenderung: PostAenderung):
    try:
        zeile = aendere_post(post_id, aenderung.model_dump(exclude_unset=True))
        # nach dem Bearbeiten neu pruefen (Befunde sperren das automatische Posten bis zur Freigabe)
        if zeile and zeile.get("quelle") == "himmel" and (zeile.get("meta") or {}).get("pruefung") is not None:
            befunde = redaktion.pruefe_post(zeile, zeile.get("sprache") or "de")
            setze_meta(post_id, "pruefung", befunde)
            zeile["meta"] = {**(zeile.get("meta") or {}), "pruefung": befunde}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not zeile:
        raise HTTPException(status_code=404, detail="Post nicht gefunden.")
    return {"post": zeile}


@app.delete("/content/{post_id}")
def content_loeschen(post_id: int):
    try:
        if not loesche_post(post_id):
            raise HTTPException(status_code=404, detail="Post nicht gefunden.")
        return {"geloescht": post_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------- Bilder, Reels, Wochenpaket
def _post_oder_404(post_id: int) -> dict:
    try:
        post = lade_post(post_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not post:
        raise HTTPException(status_code=404, detail="Post nicht gefunden.")
    return post


def _dateiname(post: dict, endung: str, format: str = "") -> str:
    tag = str(post.get("geplant_fuer") or post.get("created_at") or "")[:10]
    teile = ["soraya", tag, posten.platz(post), post.get("sprache") or "de"] + ([format] if format else [])
    return "-".join(t for t in teile if t) + "." + endung


@app.get("/medien/{post_id}/bild")
def medien_bild(post_id: int, format: Optional[str] = None, download: bool = False, klein: bool = False):
    post = _post_oder_404(post_id)
    try:
        daten = paket.hole_bild(post, format)
        if klein:      # Vorschaubild fuer Listen im Dashboard
            daten = paket.vorschau(daten)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bild konnte nicht erstellt werden: {e}")
    kopf = {"Cache-Control": "private, max-age=120" if klein else "no-store"}
    if download:
        kopf["Content-Disposition"] = f'attachment; filename="{_dateiname(post, "jpg", format or "")}"'
    return Response(daten, media_type="image/jpeg", headers=kopf)


@app.get("/medien/{post_id}/folie/{nr}")
def medien_folie(post_id: int, nr: int, download: bool = False, klein: bool = False):
    """Bild nr des Karussells (1 = Titelbild)."""
    post = _post_oder_404(post_id)
    if not 1 <= nr <= paket.medien.anzahl_bilder(post):
        raise HTTPException(status_code=404, detail="Diese Folie gibt es nicht.")
    try:
        daten = paket.hole_folie(post, nr)
        if klein:
            daten = paket.vorschau(daten, 220)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Folie konnte nicht erstellt werden: {e}")
    kopf = {"Cache-Control": "private, max-age=120" if klein else "no-store"}
    if download:
        kopf["Content-Disposition"] = f'attachment; filename="{_dateiname(post, "jpg", f"folie{nr}")}"'
    return Response(daten, media_type="image/jpeg", headers=kopf)


@app.get("/medien/{post_id}/video/stand")
def medien_video_stand(post_id: int):
    return paket.video_stand(_post_oder_404(post_id))


@app.post("/medien/{post_id}/video")
def medien_video_starten(post_id: int):
    post = _post_oder_404(post_id)
    if post.get("art") != "reel":
        raise HTTPException(status_code=400, detail="Videos gibt es nur für Reels.")
    return paket.video_anfordern(post)


@app.get("/medien/{post_id}/video")
def medien_video(post_id: int, download: bool = False):
    post = _post_oder_404(post_id)
    daten = paket.hole_video(post)
    if not daten:
        raise HTTPException(status_code=404, detail="Video ist noch nicht erstellt.")
    kopf = {"Cache-Control": "no-store", "Accept-Ranges": "none"}
    if download:
        kopf["Content-Disposition"] = f'attachment; filename="{_dateiname(post, "mp4")}"'
    return Response(daten, media_type="video/mp4", headers=kopf)


class PaketAnfrage(BaseModel):
    von: date
    tage: int = 7
    sprachen: list[str] = []
    nur_freigegebene: bool = True
    mit_videos: bool = True


@app.post("/wochenpaket")
def wochenpaket_starten(anfrage: PaketAnfrage):
    sprachen = [s for s in SPRACHEN if s in {norm(x) for x in anfrage.sprachen if x.strip()}]
    status = ["freigegeben", "gepostet"] if anfrage.nur_freigegebene else []
    try:
        return paket.wochenpaket_starten(anfrage.von, anfrage.tage, sprachen, status, anfrage.mit_videos)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/wochenpaket/{job_id}")
def wochenpaket_stand(job_id: str):
    stand = paket.paket_stand(job_id)
    if not stand:
        raise HTTPException(status_code=404, detail="Paket nicht gefunden (Server neu gestartet?).")
    return stand


@app.get("/wochenpaket/{job_id}/datei")
def wochenpaket_datei(job_id: str):
    datei = paket.paket_datei(job_id)
    if not datei:
        raise HTTPException(status_code=404, detail="Paket ist nicht (mehr) da.")
    return FileResponse(datei[0], media_type="application/zip", filename=datei[1])


# ---------------------------------------------------------------- Automatisch posten
@app.get("/posten/tiktok-texte")
def posten_tiktok_texte(tage: int = 3):
    """Texte fuer die TikTok-Entwuerfe (TikTok uebernimmt bei Entwuerfen keinen Text)."""
    return {"texte": posten.tiktok_texte(max(1, min(tage, 14)))}


@app.get("/posten")
def posten_ansehen():
    try:
        jetzt = datetime.now(himmel.WIEN)
        termine = lade_veroeffentlichungen(jetzt - timedelta(days=2), jetzt + timedelta(days=2))
        return {"einstellungen": posten.einstellungen(), "verbindungen": posten.verbindungen(),
                "termine": termine, "tagesplan_auto": tagesplan.automatisch(),
                "tagesplan_sprachen": tagesplan.sprachen(), "jetzt": jetzt,
                "sprachen_heute": {a: posten.sprache_fuer(jetzt.date(), a, posten.einstellungen()) for a in posten.ARTEN},
                "benoetigt": posten.benoetigte_sprachen(posten.einstellungen(), [jetzt.date(), jetzt.date() + timedelta(days=1)])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PostenEinstellungen(BaseModel):
    an: Optional[bool] = None
    sprache: Optional[str] = None
    modus: Optional[str] = None
    tiktok_modus: Optional[str] = None
    zeiten: Optional[dict] = None
    plattformen: Optional[dict] = None
    sprache_pl: Optional[dict] = None


@app.put("/posten/einstellungen")
def posten_einstellen(neu: PostenEinstellungen):
    try:
        return {"einstellungen": posten.speichere_einstellungen(neu.model_dump(exclude_none=True))}
    except ValueError:
        raise HTTPException(status_code=400, detail="Uhrzeit bitte als HH:MM, z. B. 09:00.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class JetztPosten(BaseModel):
    post_id: int
    plattform: str


@app.post("/posten/jetzt")
def posten_jetzt(anfrage: JetztPosten):
    try:
        return {"ergebnis": posten.jetzt_posten(anfrage.post_id, anfrage.plattform)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/meta/verbinden/{dienst}")
def meta_verbinden(dienst: str):
    if dienst not in ("facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unbekannt.")
    try:
        return RedirectResponse(meta.anmelde_url(dienst), status_code=302)
    except meta.MetaFehler as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/meta/rueckruf/{dienst}")
def meta_rueckruf(dienst: str, code: Optional[str] = None, state: Optional[str] = None,
                  error_description: Optional[str] = None, error: Optional[str] = None):
    try:
        if dienst not in ("facebook", "instagram"):
            raise meta.MetaFehler("Unbekannter Dienst.")
        if not code:
            raise meta.MetaFehler(error_description or error or "Verbindung abgebrochen.")
        meta.pruefe_state(dienst, state or "")
        (meta.verbinde_facebook if dienst == "facebook" else meta.verbinde_instagram)(code.split("#")[0])
        return RedirectResponse(f"/?verbunden={dienst}#posten", status_code=302)
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/?verbindungsfehler={quote(str(e)[:300])}#posten", status_code=302)


@app.post("/meta/trennen/{dienst}")
def meta_trennen(dienst: str):
    if dienst not in ("facebook", "instagram"):
        raise HTTPException(status_code=404, detail="Unbekannt.")
    meta.trennen(dienst)
    return {"getrennt": dienst}


@app.get("/tiktok/verbinden")
def tiktok_verbinden():
    try:
        return RedirectResponse(tiktok.anmelde_url(), status_code=302)
    except tiktok.TikTokFehler as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/tiktok/rueckruf")
def tiktok_rueckruf(code: Optional[str] = None, state: Optional[str] = None,
                    error_description: Optional[str] = None, error: Optional[str] = None):
    try:
        if not code:
            raise tiktok.TikTokFehler(error_description or error or "Verbindung abgebrochen.")
        meta.pruefe_state("tiktok", state or "")
        tiktok.verbinde(code)
        return RedirectResponse("/?verbunden=tiktok#posten", status_code=302)
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/?verbindungsfehler={quote(str(e)[:300])}#posten", status_code=302)


@app.post("/tiktok/trennen")
def tiktok_trennen():
    tiktok.trennen()
    return {"getrennt": "tiktok"}


@app.get("/pinterest/verbinden")
def pinterest_verbinden():
    try:
        return RedirectResponse(pinterest.anmelde_url(), status_code=302)
    except pinterest.PinterestFehler as e:
        from urllib.parse import quote
        return RedirectResponse(f"/?verbindungsfehler={quote(str(e)[:300])}#posten", status_code=302)


@app.get("/pinterest/rueckruf")
def pinterest_rueckruf(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    try:
        if not code:
            raise pinterest.PinterestFehler(error or "Verbindung abgebrochen.")
        meta.pruefe_state("pinterest", state or "")
        pinterest.verbinde(code)
        return RedirectResponse("/?verbunden=pinterest#posten", status_code=302)
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/?verbindungsfehler={quote(str(e)[:300])}#posten", status_code=302)


@app.post("/pinterest/trennen")
def pinterest_trennen():
    pinterest.trennen()
    return {"getrennt": "pinterest"}


@app.get("/linkedin/verbinden")
def linkedin_verbinden():
    try:
        return RedirectResponse(linkedin.anmelde_url(), status_code=302)
    except linkedin.LinkedInFehler as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/linkedin/rueckruf")
def linkedin_rueckruf(code: Optional[str] = None, state: Optional[str] = None,
                      error_description: Optional[str] = None, error: Optional[str] = None):
    try:
        if not code:
            raise linkedin.LinkedInFehler(error_description or error or "Verbindung abgebrochen.")
        meta.pruefe_state("linkedin", state or "")
        linkedin.verbinde(code)
        return RedirectResponse("/?verbunden=linkedin#posten", status_code=302)
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/?verbindungsfehler={quote(str(e)[:300])}#posten", status_code=302)


@app.post("/linkedin/trennen")
def linkedin_trennen():
    linkedin.trennen()
    return {"getrennt": "linkedin"}


@app.get("/oeffentlich/medien/{name}")
def oeffentliche_medien(name: str):
    try:
        datei = posten.oeffentliches_medium(name)
    except Exception:
        datei = None
    if not datei:
        raise HTTPException(status_code=404, detail="Nicht gefunden.")
    return Response(datei[0], media_type=datei[1], headers={"Cache-Control": "public, max-age=3600"})


@app.get("/himmel")
def himmel_heute(sprache: str = "de"):
    try:
        return himmel.aufbereiten(himmel.hole_himmel(), himmel.heute(), norm(sprache))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/tagesplan")
def tagesplan_ansehen(datum: Optional[date] = None):
    tag = datum or himmel.heute()
    try:
        laeufe = lade_tagesplaene(tag)
        posts = [p for p in lade_posts(limit=200, von=tag, bis=tag) if p.get("geplant_fuer") == tag]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "datum": tag,
        "automatisch": tagesplan.automatisch(),
        "automatik_gesperrt": tagesplan.gesperrt(),
        "ab_stunde": tagesplan.startstunde(),
        "sprachen": tagesplan.sprachen(),
        "laeufe": laeufe,
        "posts": posts,
    }


class AutomatikAnfrage(BaseModel):
    an: bool


class SprachenAnfrage(BaseModel):
    sprachen: list[str]


@app.put("/tagesplan/sprachen")
def tagesplan_sprachen(anfrage: SprachenAnfrage):
    try:
        return {"sprachen": tagesplan.sprachen_setzen(anfrage.sprachen)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/tagesplan/automatik")
def tagesplan_automatik(anfrage: AutomatikAnfrage):
    if tagesplan.gesperrt():
        raise HTTPException(status_code=409, detail="In Railway ist TAGESPLAN_AUTO=0 gesetzt. "
                                                    "Entferne die Variable, dann wirkt der Schalter.")
    try:
        return {"automatisch": tagesplan.automatik_setzen(anfrage.an)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tagesplan")
def tagesplan_starten(anfrage: TagesplanAnfrage):
    liste = [norm(s) for s in anfrage.sprachen if s.strip()] or tagesplan.sprachen()
    liste = [s for s in SPRACHEN if s in liste]
    tagesplan.erstelle_im_hintergrund(liste, erzwingen=anfrage.neu)
    return {"gestartet": liste, "neu": anfrage.neu}


@app.post("/tagesplan/vorplanen")
def tagesplan_vorplanen(anfrage: VorplanAnfrage):
    """Ab morgen die naechsten Tage vorplanen (Hintergrund). Fertige Tage werden uebersprungen."""
    liste = [norm(s) for s in anfrage.sprachen if s.strip()] or tagesplan.sprachen()
    return tagesplan.vorplanen(anfrage.tage, [s for s in SPRACHEN if s in liste])


@app.get("/tagesplan/zeitraum")
def tagesplan_zeitraum(von: date, bis: date):
    """Stand der Tagesplaene je Tag und Sprache (fuer die Wochenansicht)."""
    if (bis - von).days > 62:
        raise HTTPException(status_code=400, detail="Zeitraum höchstens 2 Monate.")
    try:
        return {"laeufe": lade_tagesplaene_zeitraum(von, bis), "sprachen": tagesplan.sprachen()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/links")
def links_ansehen():
    """Post- und Bio-Links, mit denen gemessen wird, was welcher Post bringt."""
    return wirkung_links()


@app.get("/wirkung")
def wirkung(tage: int = 30):
    try:
        return {"eingerichtet": True, "statistik": hole_statistik(tage)}
    except LookupError as e:
        return {"eingerichtet": False, "hinweis": str(e), "stand": getattr(e, "stand", "agent_fehlt")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/wirkung/facebook")
def wirkung_facebook(tage: int = 30):
    """Reaktionen auf die zuletzt geposteten Facebook-Beitraege."""
    if not meta.verbindungen()["facebook"]["verbunden"]:
        return {"verbunden": False, "beitraege": []}
    try:
        seit = datetime.now(himmel.WIEN) - timedelta(days=max(1, min(tage, 90)))
        beitraege = meta.facebook_reaktionen(db.lade_gepostete("facebook", seit))
        posten.merke_facebook(beitraege)
        posten.facebook_follower_merken()
        cockpit.leeren()
        return {"verbunden": True, "beitraege": beitraege, "konto": posten.follower_stand("facebook_follower"),
                "abruf": posten.abruf_stand().get("facebook")}
    except Exception as e:
        posten.merke_abruf("facebook", 0, 1, str(e))
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/wirkung/instagram")
def wirkung_instagram(tage: int = 30):
    """Instagram: Follower und Zahlen der zuletzt geposteten Beitraege (holt frisch und merkt sie)."""
    if not meta.verbindungen()["instagram"]["verbunden"]:
        return {"verbunden": False, "beitraege": []}
    seit = datetime.now(himmel.WIEN) - timedelta(days=max(1, min(tage, 90)))
    try:
        r = posten.zahlen_instagram(seit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"verbunden": True, "recht_fehlt": r["recht_fehlt"], "konto": posten.follower_stand(),
            "meldung": (meta.zugang("instagram") or {}).get("insights_meldung") if r["recht_fehlt"] else None,
            "beitraege": r["beitraege"]}


@app.get("/wirkung/tiktok")
def wirkung_tiktok(tage: int = 30):
    """TikTok: Aufrufe, Gefaellt mir, Kommentare, Teilen der Reels (video.list, ohne Audit)."""
    v = tiktok.verbindung()
    if not v["verbunden"]:
        return {"verbunden": False, "beitraege": []}
    if not v.get("zahlen"):
        return {"verbunden": True, "recht_fehlt": True, "beitraege": []}
    seit = datetime.now(himmel.WIEN) - timedelta(days=max(1, min(tage, 90)))
    try:
        beitraege = posten.zahlen_tiktok(seit)
        return {"verbunden": True, "recht_fehlt": False, "beitraege": beitraege,
                "konto": posten.follower_stand("tiktok_follower"), "gefunden": posten._TIKTOK_STAND.get("gefunden")}
    except Exception as e:
        if not tiktok.verbindung().get("zahlen"):
            return {"verbunden": True, "recht_fehlt": True, "beitraege": []}
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/wirkung/cockpit")
def wirkung_cockpit(tage: int = 7):
    """Zahlen-Cockpit: Kennzahlen mit Vergleich, Follower, beste Posts, Trichter, Lernen, Tabelle, Verlauf."""
    try:
        return cockpit.cockpit(tage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/wirkung/wochenbericht")
def wirkung_wochenbericht():
    """Kurzer Bericht ueber die letzte Woche fuer „Heute“ (ohne Claude)."""
    try:
        return cockpit.wochenbericht()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WochenberichtGesehen(BaseModel):
    woche: str


@app.post("/wirkung/wochenbericht/gesehen")
def wirkung_wochenbericht_gesehen(anfrage: WochenberichtGesehen):
    try:
        cockpit.wochenbericht_gesehen(anfrage.woche)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.get("/wirkung/lernen")
def wirkung_lernen():
    """Was der Tagesplan aus der Wirkung lernt: beste Posts, Formate, Arten, Sprachen."""
    try:
        bewertet = redaktion.bewerte(db.lade_post)
        erk = redaktion.erkenntnisse(bewertet)
        beste = [{"id": e["post"]["id"], "titel": e["post"].get("titel"), "art": e["post"].get("art"),
                  "sprache": e["post"].get("sprache"), "format": (e["post"].get("meta") or {}).get("thema"),
                  "punkte": e["punkte"], "details": redaktion._details(e)} for e in bewertet[:5] if e["punkte"] > 0]
        return {"beste": beste, "erkenntnisse": erk, "hinweis": redaktion.erkenntnis_text(erk),
                "gemessen": len(redaktion.gemessen(bewertet)), "nicht_gemessen": redaktion.nicht_gemessen(bewertet),
                "zeiten": redaktion.zeit_vorschlaege(erk)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/zielgruppe")
def zielgruppe_erforschen(anfrage: ZielgruppeAnfrage):
    """Recherchiert einen Bereich in mehreren Quellen und erstellt ein Kundenprofil."""
    try:
        titel = titel_fuer(anfrage.bereich)

        # Eigene Eingaben haben Vorrang vor den vordefinierten Mustern
        begriffe = [b.strip() for b in anfrage.eigene_begriffe if b.strip()] \
            or begriffe_fuer(anfrage.bereich)
        playstore_suche = anfrage.eigene_playstore.strip() \
            or playstore_suche_fuer(anfrage.bereich)
        app_ids = [a.strip() for a in anfrage.eigene_app_ids if a.strip()]

        gewaehlt = anfrage.quellen or ["websuche"]
        teile, geklappt, fehlgeschlagen = [], [], {}

        def hole(name, fn):
            if name not in gewaehlt:
                return
            print(f"[Recherche] Starte Quelle: {name}", flush=True)
            try:
                text = fn()
                if text and text.strip():
                    teile.append(f"\n\n===== QUELLE: {name.upper()} =====\n{text}")
                    geklappt.append(name)
                    print(f"[Recherche] {name}: {len(text)} Zeichen erhalten", flush=True)
                else:
                    fehlgeschlagen[name] = "keine Ergebnisse"
                    print(f"[Recherche] {name}: KEINE ERGEBNISSE", flush=True)
            except Exception as e:
                fehlgeschlagen[name] = str(e)[:300]
                print(f"[Recherche] {name}: FEHLER -> {e}", flush=True)

        hole("websuche", lambda: quelle_websuche(begriffe, land=anfrage.land))
        hole("reddit", lambda: quelle_reddit(begriffe))
        hole("playstore", lambda: (
            quelle_playstore_ids(app_ids) if app_ids
            else quelle_playstore(playstore_suche)
        ))

        recherche = "".join(teile)
        if not recherche.strip():
            raise RuntimeError(
                "Keine Quelle hat Daten geliefert. Details: " + str(fehlgeschlagen)
            )

        profil = analysiere_zielgruppe(
            titel, recherche, eigene_frage=anfrage.eigene_frage.strip()
        )
        profil["_quellen"] = geklappt
        profil["_gesucht"] = begriffe
        zeile = speichere_zielgruppe(titel, profil, land=anfrage.land)

        return {
            "bereich": titel,
            "gesucht": begriffe,
            "quellen_ok": geklappt,
            "quellen_fehler": fehlgeschlagen,
            "gefunden_zeichen": len(recherche),
            "profil": profil,
            "id": zeile.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/zielgruppen")
def zielgruppen_ansehen(limit: int = 20):
    try:
        zeilen = lade_zielgruppen(limit=limit)
        # welches Profil der Tagesplan je Sprache gerade nutzt (auch ohne Markierung)
        return {"zielgruppen": zeilen, "im_tagesplan": tagesplan.zielgruppen_je_sprache()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ZielgruppeAenderung(BaseModel):
    im_tagesplan: bool


@app.patch("/zielgruppen/{zielgruppe_id}")
def zielgruppe_aendern(zielgruppe_id: int, aenderung: ZielgruppeAenderung):
    try:
        zeile = setze_zielgruppe_im_tagesplan(zielgruppe_id, aenderung.im_tagesplan)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not zeile:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden.")
    return {"zielgruppe": zeile}
