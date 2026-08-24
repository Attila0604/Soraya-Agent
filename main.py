"""
Soraya-Agent — Stufe 0
Der Content-Agent: schreibt fertige Social-Media-Posts fuer die Soraya-App.
Speicherung in der Railway-eigenen PostgreSQL-Datenbank.

Endpoints:
  GET  /            -> kurzer Status
  GET  /health      -> Health-Check (fuer Railway)
  POST /content     -> neue Posts generieren lassen (und speichern)
  GET  /content     -> alle bisher generierten Posts ansehen
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from content_agent import erstelle_posts
from db import init_db, speichere_posts, lade_posts

app = FastAPI(title="Soraya-Agent", version="0.1")


class ContentAnfrage(BaseModel):
    # Optional: ein Thema vorgeben. Wenn leer, waehlt die KI selbst ein
    # passendes Astro-/Horoskop-Thema fuer Soraya.
    thema: Optional[str] = None
    # Wie viele Posts sollen erstellt werden (Standard 3).
    anzahl: int = 3


@app.on_event("startup")
def beim_start():
    # Tabelle anlegen, falls noch nicht vorhanden.
    try:
        init_db()
    except Exception as e:
        # App startet trotzdem; Fehler wird beim ersten Aufruf sichtbar.
        print(f"[Start] Datenbank noch nicht bereit: {e}")


@app.get("/")
def start():
    return {
        "app": "Soraya-Agent",
        "stufe": 0,
        "agent": "Content-Agent",
        "info": "POST /content um Posts zu erstellen, GET /content um sie anzusehen.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl)
    gespeichert = speichere_posts(posts)
    return {"erstellt": len(gespeichert), "posts": gespeichert}


@app.get("/content")
def content_ansehen(limit: int = 50):
    return {"posts": lade_posts(limit=limit)}
