"""
Soraya-Agent — Stufe 0/1
- Content-Agent: schreibt Social-Media-Posts fuer die Soraya-App.
- Recherche (Apify): liest eine Webseite aus und schreibt Posts daraus.
Speicherung in der Railway-eigenen PostgreSQL-Datenbank.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from content_agent import erstelle_posts
from apify import hole_webseiten_text
from db import init_db, speichere_posts, lade_posts

app = FastAPI(title="Soraya-Agent", version="0.2")


class ContentAnfrage(BaseModel):
    thema: Optional[str] = None
    anzahl: int = 3


class UrlAnfrage(BaseModel):
    url: str
    anzahl: int = 3


@app.on_event("startup")
def beim_start():
    try:
        init_db()
    except Exception as e:
        print(f"[Start] Datenbank noch nicht bereit: {e}")


@app.get("/")
def start():
    return {
        "app": "Soraya-Agent",
        "stufe": "0/1",
        "agenten": ["Content-Agent", "Recherche (Apify)"],
        "info": "POST /content oder POST /content-von-url ; GET /content zum Ansehen.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    try:
        posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl)
        gespeichert = speichere_posts(posts)
        return {"erstellt": len(gespeichert), "posts": gespeichert}
    except Exception as e:
        # Echten Grund im Klartext zurueckgeben (statt anonymem 500)
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
