"""
Soraya-Agent — Stufe 1
- Content-Agent: schreibt Social-Media-Posts.
- Recherche (Apify): liest Webseiten aus / durchsucht das Netz.
- Zielgruppen-Agent: erstellt Kundenprofile je Bereich.
- Web-Oberflaeche ("Content Studio") unter "/".
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

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
    init_db, speichere_posts, lade_posts,
    speichere_zielgruppe, lade_zielgruppen,
)

app = FastAPI(title="Soraya-Agent", version="0.4")


class ContentAnfrage(BaseModel):
    thema: Optional[str] = None
    anzahl: int = 3


class UrlAnfrage(BaseModel):
    url: str
    anzahl: int = 3


class ZielgruppeAnfrage(BaseModel):
    bereich: str
    land: str = "at"
    # Welche Quellen sollen laufen?
    quellen: list[str] = ["google"]
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


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    try:
        posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl)
        return {"erstellt": len(posts), "posts": speichere_posts(posts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/content-von-url")
def content_von_url(anfrage: UrlAnfrage):
    try:
        text = hole_webseiten_text(anfrage.url)
        posts = erstelle_posts(anzahl=anfrage.anzahl, kontext=text)
        gespeichert = speichere_posts(posts)
        return {
            "quelle": anfrage.url,
            "gelesen_zeichen": len(text),
            "erstellt": len(gespeichert),
            "posts": gespeichert,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/content")
def content_ansehen(limit: int = 50):
    try:
        return {"posts": lade_posts(limit=limit)}
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

        gewaehlt = anfrage.quellen or ["google"]
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
