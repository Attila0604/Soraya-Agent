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
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    speichere_zielgruppe, lade_zielgruppen, lade_tagesplaene, lade_tagesplaene_zeitraum,
)
import himmel
import tagesplan
from sprachen import SPRACHEN, NAMEN, norm
from wirkung import hole_statistik

app = FastAPI(title="Soraya-Agent", version="0.6")

# Ohne Anmeldung erreichbar (Railway-Healthcheck).
OFFENE_PFADE = {"/health"}


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
    if request.url.path in OFFENE_PFADE:
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
    if tagesplan.automatisch():
        tagesplan.zeitplan_starten()
        print(f"[Start] Tagesplan automatisch ab {tagesplan.startstunde()} Uhr: "
              f"{', '.join(tagesplan.sprachen())}", flush=True)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Liest die Oberflaeche aus dashboard.html."""
    pfad = Path(__file__).parent / "dashboard.html"
    return pfad.read_text(encoding="utf-8")


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
        "ab_stunde": tagesplan.startstunde(),
        "sprachen": tagesplan.sprachen(),
        "laeufe": laeufe,
        "posts": posts,
    }


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


@app.get("/wirkung")
def wirkung(tage: int = 30):
    try:
        return {"eingerichtet": True, "statistik": hole_statistik(tage)}
    except LookupError as e:
        return {"eingerichtet": False, "hinweis": str(e)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


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
        zeile = speichere_zielgruppe(titel, profil)

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
        return {"zielgruppen": lade_zielgruppen(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
