"""Tests fuer den Soraya-Agent (Stufe 2). Echte Postgres, Claude/Backend als Attrappe."""
import base64
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://agent@127.0.0.1:55432/agenttest")
os.environ["AGENT_PASSWORT"] = "geheim-test"
os.environ["TAGESPLAN_AUTO"] = "0"
os.environ["ANTHROPIC_API_KEY"] = "sk-test"
sys.path.insert(0, os.environ.get("AGENT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg
import pytest
from fastapi.testclient import TestClient

import claude
import content_agent
import db
import himmel
import main
import research_agent
import tagesplan
import wirkung

AUTH = {"Authorization": "Basic " + base64.b64encode(b"soraya:geheim-test").decode()}
HEUTE = himmel.heute()
SKY = {
    "moon": {"phase": "Zunehmende Sichel", "phase_index": 1, "illumination": 12, "sign": "Sco", "sign_de": "Skorpion"},
    "sun": {"sign": "Lib", "sign_de": "Waage"},
    "retrograde": [{"planet": "Venus", "key": "Venus", "until": (HEUTE + timedelta(days=30)).isoformat()}],
    "retrograde_soon": [{"planet": "Merkur", "key": "Mercury", "from": (HEUTE + timedelta(days=5)).isoformat()}],
    "next_new_moon": (HEUTE + timedelta(days=27)).isoformat() + "T07:02+00:00",
    "next_full_moon": (HEUTE + timedelta(days=2)).isoformat() + "T04:11+00:00",
}


FEED_TEXT = ("Spürst du heute alles ein bisschen lauter? Der Mond wandert durch den Skorpion und macht kleine Dinge "
             "groß. Ein Satz in der Gruppe, eine Nachricht ohne Antwort – alles trifft tiefer als sonst. Das ist kein "
             "Drama, das ist Ehrlichkeit. Nutze den Tag für ein Gespräch, das du schon lange führen willst. Sag es "
             "ruhig, aber sag es. Speichere dir den Post für den Vollmond in zwei Tagen.\n\n"
             "Welches Zeichen bist du? Schreib dein Emoji in die Kommentare 👇")
TAGS = ["#astrologie", "#mondphase", "#horoskop", "#skorpion", "#soraya"]
EN_TEXT = ("Feeling everything a little louder today? The Moon moves through Scorpio and turns small moments into big "
           "ones. A message left on read, one sentence in the group chat – it all lands deeper. That is not drama, it "
           "is honesty. Use the day for the conversation you have been putting off. Say it softly, but say it. Save "
           "this post for the Full Moon in two days.\n\nWhich sign are you? Drop your emoji below 👇")


def tagesplan_antwort(sprache="de"):
    return {"thema": "Vollmond naht", "posts": [
        {"art": "post", "platform": "instagram", "titel": f"Vollmond {sprache}", "untertitel": "U",
         "text": EN_TEXT if sprache == "en" else FEED_TEXT,
         "hashtags": TAGS, "bild_punkte": ["Skorpion: ehrlich sein", "Stier: langsam", "Krebs: Bauchgefühl"],
         "skript": {"hook": "", "szenen": [], "einblendungen": [], "schluss": ""}},
        {"art": "reel", "platform": "tiktok", "titel": "Reel", "untertitel": "U", "text": "Two nights to go. Can you feel it?" if sprache == "en" else "Caption mit Hook. Zwei Nächte noch. Spürst du es?",
         "hashtags": TAGS[:4], "bild_punkte": [],
         "skript": {"hook": "Hook!", "szenen": ["S1", "S2", "S3"], "einblendungen": ["Eins zwei", "Drei vier", "Fünf"],
                    "schluss": "Link in Bio"}},
        {"art": "story", "platform": "instagram", "titel": "Story", "untertitel": "U", "text": "How do you sleep? Reply with 🌙" if sprache == "en" else "Wie schläfst du? Antworte mit 🌙",
         "hashtags": ["#mondphase"], "bild_punkte": [], "skript": {"hook": "", "szenen": [], "einblendungen": [], "schluss": ""}},
    ]}


@pytest.fixture(autouse=True)
def frische_db(monkeypatch):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("drop table if exists soraya_veroeffentlichungen, soraya_medien, soraya_posts, soraya_zielgruppen, soraya_tagesplaene, soraya_einstellungen cascade;")
    db.init_db()
    aufrufe = []

    def fake_frage(system, frage, schema, **kw):
        aufrufe.append({"system": system, "frage": frage, "schema": schema, **kw})
        if "posts" in schema["properties"] and "thema" in schema["properties"]:
            return tagesplan_antwort("en" if "English" in frage else "de")
        if "posts" in schema["properties"]:
            return {"posts": [{"platform": "instagram", "titel": "T", "untertitel": "U", "text": "Hallo",
                               "hashtags": ["#x", "#y"]}] * 5}
        return {"bereich": "B", "wer_sind_sie": "W", "beschaeftigt_sie": ["a"], "wuensche": [], "sprache": [],
                "content_ideen": [], "worauf_achten": [], "luecke_am_markt": [], "unsicher": [], "antwort_auf_frage": ""}
    for modul in (tagesplan, content_agent, research_agent):
        monkeypatch.setattr(modul, "frage_json", fake_frage)
    monkeypatch.setattr(himmel, "hole_himmel", lambda tag=None: SKY)
    yield aufrufe


client = TestClient(main.app)
ECHT_HOLE_HIMMEL = himmel.hole_himmel


# ---------------------------------------------------------------- Grundlagen
def test_alte_tabelle_wird_erweitert():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("drop table soraya_posts cascade;")
        conn.execute("create table soraya_posts (id bigint generated always as identity primary key, platform text not null,"
                     " text text not null, hashtags text, status text not null default 'entwurf',"
                     " created_at timestamptz not null default now());")
        conn.execute("insert into soraya_posts (platform, text, hashtags) values ('instagram', 'alt', '#alt');")
    db.init_db()
    db.init_db()  # zweimal: darf nichts kaputt machen
    alt = db.lade_posts()[0]
    assert alt["text"] == "alt" and alt["sprache"] == "de" and alt["quelle"] == "studio" and alt["art"] == "post"


def test_anmeldung_noetig():
    assert client.get("/health").status_code == 200
    for methode, pfad in (("get", "/tagesplan"), ("post", "/tagesplan"), ("get", "/wirkung"),
                          ("patch", "/content/1"), ("delete", "/content/1"), ("get", "/himmel")):
        assert getattr(client, methode)(pfad).status_code == 401, pfad


# ---------------------------------------------------------------- Content Studio
def test_content_in_sprache(frische_db):
    r = client.post("/content", json={"thema": "Vollmond", "anzahl": 2, "sprache": "hu"}, headers=AUTH)
    assert r.status_code == 200, r.text
    posts = r.json()["posts"]
    assert len(posts) == 2 and all(p["sprache"] == "hu" and p["quelle"] == "studio" and p["titel"] == "T" for p in posts)
    assert posts[0]["hashtags"] == "#x #y"
    assert "magyar" in frische_db[-1]["frage"]


def test_content_filter_und_plan():
    a, b, c = db.speichere_posts([{"text": "a", "sprache": "de"}, {"text": "b", "sprache": "en"}, {"text": "c"}])
    db.aendere_post(a["id"], {"geplant_fuer": HEUTE})
    db.aendere_post(b["id"], {"geplant_fuer": HEUTE + timedelta(days=30)})
    r = client.get(f"/content?von={HEUTE}&bis={HEUTE + timedelta(days=6)}", headers=AUTH).json()["posts"]
    assert {p["text"] for p in r} == {"a", "c"}  # c ohne Datum gehoert zum Einplanen dazu
    r = client.get("/content?sprache=en", headers=AUTH).json()["posts"]
    assert [p["text"] for p in r] == ["b"]
    db.speichere_posts([{"text": f"h{i}"} for i in range(5)], quelle="himmel", geplant_fuer=HEUTE)
    r = client.get("/content?himmel=false&limit=2", headers=AUTH).json()["posts"]
    assert [p["text"] for p in r] == ["c", "b"]  # nur eigene, neueste zuerst
    assert len(client.get("/content?himmel=true", headers=AUTH).json()["posts"]) == 5


def test_post_bearbeiten_status_loeschen():
    (p,) = db.speichere_posts([{"text": "x"}])
    url = f"/content/{p['id']}"
    r = client.patch(url, json={"status": "gepostet", "text": "neu", "geplant_fuer": str(HEUTE)}, headers=AUTH).json()["post"]
    assert r["status"] == "gepostet" and r["gepostet_am"] and r["text"] == "neu" and r["geplant_fuer"] == str(HEUTE)
    r = client.patch(url, json={"status": "freigegeben", "geplant_fuer": None}, headers=AUTH).json()["post"]
    assert r["gepostet_am"] is None and r["geplant_fuer"] is None
    assert client.patch(url, json={"status": "quatsch"}, headers=AUTH).status_code == 400
    assert client.patch(url, json={}, headers=AUTH).status_code == 400
    assert client.patch("/content/999999", json={"text": "x"}, headers=AUTH).status_code == 404
    assert client.delete(url, headers=AUTH).status_code == 200
    assert client.delete(url, headers=AUTH).status_code == 404


# ---------------------------------------------------------------- Himmel
def test_himmel_aufbereitet():
    info = himmel.aufbereiten(SKY, HEUTE, "hu")
    assert info["mond_zeichen"] == "Skorpió" and info["mond_phase"] == "Növő holdsarló"
    assert info["vollmond"]["in_tagen"] == 2 and info["neumond"]["in_tagen"] == 27
    assert info["ruecklaeufig"][0]["planet"] == "Vénusz" and info["bald_ruecklaeufig"][0]["planet"] == "Merkúr"
    text = himmel.als_text(info)
    assert "in 2 Tagen" in text and "Skorpió" in text
    r = client.get("/himmel?sprache=it", headers=AUTH).json()
    assert r["mond_zeichen"] == "Scorpione"


# ---------------------------------------------------------------- Tagesplan
def test_tagesplan_einmal_pro_tag_und_sprache(frische_db):
    r = tagesplan.erstelle("de")
    assert r["status"] == "fertig" and r["posts"] == 3
    posts = db.lade_posts(von=HEUTE, bis=HEUTE)
    assert {p["art"] for p in posts} == {"post", "reel", "story"}
    reel = next(p for p in posts if p["art"] == "reel")
    assert reel["skript"]["hook"] == "Hook!" and reel["meta"]["phase_index"] == 1
    assert next(p for p in posts if p["art"] == "post")["skript"] is None
    assert all(p["quelle"] == "himmel" and p["geplant_fuer"] == HEUTE for p in posts)
    n = len(frische_db)
    assert tagesplan.erstelle("de")["status"] == "schon_da" and len(frische_db) == n  # kein zweiter Claude-Aufruf
    assert "Skorpion" in frische_db[0]["frage"] and "Link in Bio" in frische_db[0]["system"]


def test_tagesplan_kennt_letzte_titel(frische_db):
    db.speichere_posts([{"text": "x", "titel": "Gestern schon da", "sprache": "en"}], quelle="himmel",
                       geplant_fuer=HEUTE - timedelta(days=1))
    tagesplan.erstelle("en")
    assert "Gestern schon da" in frische_db[-1]["frage"] and "English" in frische_db[-1]["frage"]


def test_tagesplan_neu_behaelt_bearbeitete():
    tagesplan.erstelle("de")
    posts = db.lade_posts(von=HEUTE, bis=HEUTE)
    time.sleep(0.01)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # bearbeiteter Entwurf (spaeter geaendert)
        conn.execute("update soraya_posts set text = 'von Hand', aktualisiert = now() + interval '1 minute' where id = %s",
                     (posts[0]["id"],))
    db.aendere_post(posts[1]["id"], {"status": "freigegeben"})
    assert tagesplan.erstelle("de", erzwingen=True)["status"] == "fertig"
    texte = [p["text"] for p in db.lade_posts(von=HEUTE, bis=HEUTE)]
    assert "von Hand" in texte and len(texte) == 5  # 2 behalten + 3 neue


def test_tagesplan_fehler_und_wiederholung(monkeypatch):
    def kaputt(*a, **k):
        raise RuntimeError("Claude weg")
    monkeypatch.setattr(tagesplan, "frage_json", kaputt)
    r = tagesplan.erstelle("it")
    assert r["status"] == "fehler" and "Claude weg" in r["fehler"]
    assert tagesplan.erstelle("it")["status"] == "schon_da"  # nicht sofort erneut (Kosten)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("update soraya_tagesplaene set aktualisiert = now() - interval '31 minutes'")
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: tagesplan_antwort("it"))
    assert tagesplan.erstelle("it")["status"] == "fertig"
    lauf = db.lade_tagesplaene(HEUTE)[0]
    assert lauf["versuche"] == 2 and lauf["himmel"]["mond_zeichen"] == "Scorpione"


def test_tagesplan_hoechstens_drei_versuche(monkeypatch):
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("weg")))
    for _ in range(5):
        tagesplan.erstelle("de")
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute("update soraya_tagesplaene set aktualisiert = now() - interval '31 minutes'")
    assert db.lade_tagesplaene(HEUTE)[0]["versuche"] == 3


def test_tagesplan_knopf_wiederholt_fehler_sofort(monkeypatch):
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Schlüssel ungültig")))
    assert tagesplan.erstelle("de")["status"] == "fehler"
    assert tagesplan.erstelle("de")["status"] == "schon_da"            # Zeitplan wartet
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: tagesplan_antwort())
    assert tagesplan.erstelle("de", manuell=True)["status"] == "fertig"  # Knopf: sofort
    assert tagesplan.erstelle("de", manuell=True)["status"] == "schon_da"  # fertige nicht nochmal


def test_himmel_fuer_anderen_tag(monkeypatch):
    gesehen = []
    def fake_get(url, params=None, timeout=None):
        gesehen.append(params)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ok": True, "data": SKY})
    monkeypatch.setattr(himmel, "hole_himmel", himmel.hole_himmel.__wrapped__ if hasattr(himmel.hole_himmel, "__wrapped__") else ECHT_HOLE_HIMMEL)
    monkeypatch.setattr(himmel.requests, "get", fake_get)
    himmel.hole_himmel(); himmel.hole_himmel(HEUTE); himmel.hole_himmel(HEUTE + timedelta(days=3))
    assert gesehen == [None, None, {"datum": (HEUTE + timedelta(days=3)).isoformat()}]


def test_vorplanen(frische_db, monkeypatch):
    tage_gefragt = []
    monkeypatch.setattr(himmel, "hole_himmel", lambda tag=None: tage_gefragt.append(tag) or SKY)
    r = client.post("/tagesplan/vorplanen", json={"tage": 3, "sprachen": ["en", "de"]}, headers=AUTH).json()
    morgen = HEUTE + timedelta(days=1)
    assert r["gestartet"] and r["von"] == morgen.isoformat() and r["sprachen"] == ["de", "en"]
    for _ in range(80):
        stand = client.get(f"/tagesplan/zeitraum?von={morgen}&bis={HEUTE + timedelta(days=3)}", headers=AUTH).json()
        if len([l for l in stand["laeufe"] if l["status"] == "fertig"]) == 6:
            break
        time.sleep(0.1)
    assert len([l for l in stand["laeufe"] if l["status"] == "fertig"]) == 6
    assert sorted(set(tage_gefragt)) == [morgen, morgen + timedelta(days=1), morgen + timedelta(days=2)]
    assert len(db.lade_posts(von=morgen, bis=morgen + timedelta(days=2))) == 18
    assert not db.lade_posts(von=HEUTE, bis=HEUTE)  # heute bleibt unberuehrt
    # zweimal: alles schon da -> keine weiteren Claude-Aufrufe
    n = len(frische_db)
    client.post("/tagesplan/vorplanen", json={"tage": 3, "sprachen": ["de", "en"]}, headers=AUTH)
    time.sleep(0.5)
    assert len(frische_db) == n
    assert client.get(f"/tagesplan/zeitraum?von={HEUTE}&bis={HEUTE + timedelta(days=90)}", headers=AUTH).status_code == 400


def test_vorplanen_nur_einmal_gleichzeitig():
    assert tagesplan._vorplanen_sperre.acquire(blocking=False)
    try:
        assert tagesplan.vorplanen(2, ["de"]) == {"gestartet": False, "grund": "Vorplanen läuft bereits."}
    finally:
        tagesplan._vorplanen_sperre.release()


def test_links(monkeypatch):
    r = client.get("/links", headers=AUTH).json()
    assert r["post_muster"] == "https://www.sorayaluxuryastroguide.com/?q=p{id}"
    assert r["bio"]["instagram"].endswith("?q=bio-ig") and set(r["bio"]) == {"instagram", "tiktok", "facebook", "linkedin"}
    monkeypatch.setenv("LINK_BASIS", "https://beispiel.at")
    assert client.get("/links", headers=AUTH).json()["bio"]["tiktok"] == "https://beispiel.at/?q=bio-tt"
    assert client.get("/links").status_code == 401


def test_zeitplan(monkeypatch, frische_db):
    monkeypatch.setenv("TAGESPLAN_AUTO", "0")
    assert tagesplan.pruefe_faellige(jetzt_stunde=12) == []
    monkeypatch.setenv("TAGESPLAN_AUTO", "1")
    assert tagesplan.pruefe_faellige(jetzt_stunde=12) == []      # Schalter steht standardmaessig auf aus
    tagesplan.automatik_setzen(True)
    monkeypatch.setenv("TAGESPLAN_SPRACHEN", "it, de ,xx")
    monkeypatch.setenv("TAGESPLAN_STUNDE", "7")
    assert tagesplan.pruefe_faellige(jetzt_stunde=6) == []
    r = tagesplan.pruefe_faellige(jetzt_stunde=7)
    # heute und schon morgen (Zeit zum Pruefen)
    assert [x["sprache"] for x in r] == ["de", "it", "de", "it"] and all(x["status"] == "fertig" for x in r)
    assert all(x["status"] == "schon_da" for x in tagesplan.pruefe_faellige(jetzt_stunde=9))
    # DE: je 1 Aufruf; IT: Testtext ist deutsch -> Qualitaetspruefung -> je 1 Korrekturdurchgang
    assert len(frische_db) == 6 and sum("Probleme" in a["frage"] for a in frische_db) == 2
    assert len(db.lade_posts_zeitraum(HEUTE + timedelta(days=1), HEUTE + timedelta(days=1))) == 6


def test_automatik_schalter(monkeypatch, frische_db):
    monkeypatch.delenv("TAGESPLAN_AUTO", raising=False)
    d = client.get("/tagesplan", headers=AUTH).json()
    assert d["automatisch"] is False and d["automatik_gesperrt"] is False
    assert client.put("/tagesplan/automatik", json={"an": True}, headers=AUTH).json() == {"automatisch": True}
    assert client.get("/tagesplan", headers=AUTH).json()["automatisch"] is True
    assert [x["status"] for x in tagesplan.pruefe_faellige(jetzt_stunde=12)] == ["fertig"] * 8
    assert client.put("/tagesplan/automatik", json={"an": False}, headers=AUTH).json() == {"automatisch": False}
    n = len(frische_db)
    assert tagesplan.pruefe_faellige(jetzt_stunde=12) == [] and len(frische_db) == n
    # Railway-Sperre schlaegt den Schalter
    monkeypatch.setenv("TAGESPLAN_AUTO", "0")
    r = client.put("/tagesplan/automatik", json={"an": True}, headers=AUTH)
    assert r.status_code == 409 and "TAGESPLAN_AUTO" in r.json()["detail"]
    assert client.get("/tagesplan", headers=AUTH).json()["automatik_gesperrt"] is True
    # Datenbankfehler -> lieber aus
    monkeypatch.delenv("TAGESPLAN_AUTO")
    monkeypatch.setattr(db, "lade_einstellung", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("weg")))
    assert tagesplan.automatisch() is False


def test_tagesplan_knopf_im_hintergrund():
    r = client.post("/tagesplan", json={"sprachen": ["hu", "en"]}, headers=AUTH).json()
    assert r["gestartet"] == ["en", "hu"]
    for _ in range(50):
        stand = client.get("/tagesplan", headers=AUTH).json()
        if len([l for l in stand["laeufe"] if l["status"] == "fertig"]) == 2:
            break
        time.sleep(0.1)
    assert {l["sprache"] for l in stand["laeufe"] if l["status"] == "fertig"} == {"en", "hu"}
    assert len(stand["posts"]) == 6 and stand["sprachen"] == ["de", "en", "hu", "it"]


# ---------------------------------------------------------------- Wirkung
def test_wirkung(monkeypatch):
    monkeypatch.delenv("AGENT_STATS_TOKEN", raising=False)
    r = client.get("/wirkung", headers=AUTH).json()
    assert r["eingerichtet"] is False and "AGENT_STATS_TOKEN" in r["hinweis"]
    monkeypatch.setenv("AGENT_STATS_TOKEN", "z" * 32)
    gesehen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        gesehen.update(url=url, params=params, headers=headers)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "data": {"tage": [{"datum": "x"}]}}, text="")
    monkeypatch.setattr(wirkung.requests, "get", fake_get)
    r = client.get("/wirkung?tage=14", headers=AUTH).json()
    assert r["eingerichtet"] and r["statistik"]["tage"][0]["datum"] == "x"
    assert gesehen["url"].endswith("/internal/statistik") and gesehen["headers"]["X-Agent-Token"] == "z" * 32
    assert gesehen["params"] == {"tage": 14}
    monkeypatch.setattr(wirkung.requests, "get", lambda *a, **k: SimpleNamespace(status_code=401, json=dict, text=""))
    r = client.get("/wirkung", headers=AUTH).json()
    assert r["eingerichtet"] is False and "passt nicht" in r["hinweis"]


# ---------------------------------------------------------------- Zielgruppe
def test_zielgruppe_ohne_frage(monkeypatch):
    monkeypatch.setattr(main, "quelle_websuche", lambda begriffe, land: "Fundstueck")
    r = client.post("/zielgruppe", json={"bereich": "mond", "quellen": ["websuche"]}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert "antwort_auf_frage" not in r.json()["profil"]


def _profil(bereich, wer, worte):
    return {"wer_sind_sie": wer, "beschaeftigt_sie": ["Trennung", "Neuanfang", "Selbstwert", "Familie", "Geld"],
            "sprache": worte, "wuensche": ["Klarheit"], "worauf_achten": ["keine Angst machen"], "content_ideen": ["X"]}


def test_zielgruppe_speichert_land_und_markierung(monkeypatch):
    monkeypatch.setattr(main, "quelle_websuche", lambda begriffe, land: "Fundstueck")
    r = client.post("/zielgruppe", json={"bereich": "mond", "land": "hu", "quellen": ["websuche"]}, headers=AUTH)
    zid = r.json()["id"]
    d = client.get("/zielgruppen", headers=AUTH).json()
    z = d["zielgruppen"][0]
    assert z["land"] == "hu" and z["im_tagesplan"] is False
    # nichts markiert -> das ungarische Profil gilt automatisch nur fuer Ungarisch (nicht fuer fremde Sprachen)
    assert d["im_tagesplan"]["hu"]["id"] == zid and d["im_tagesplan"]["hu"]["automatisch"] is True
    assert "de" not in d["im_tagesplan"]
    r = client.patch(f"/zielgruppen/{zid}", json={"im_tagesplan": True}, headers=AUTH)
    assert r.status_code == 200 and r.json()["zielgruppe"]["im_tagesplan"] is True
    assert client.get("/zielgruppen", headers=AUTH).json()["im_tagesplan"]["hu"]["automatisch"] is False
    assert client.patch("/zielgruppen/999999", json={"im_tagesplan": True}, headers=AUTH).status_code == 404
    assert client.patch(f"/zielgruppen/{zid}", json={}, headers=AUTH).status_code == 422


def test_zielgruppe_je_sprache_nach_land():
    alt = db.speichere_zielgruppe("Allgemein", _profil("A", "Alle", []))
    hu = db.speichere_zielgruppe("Szerelem", _profil("H", "Ungarische Frauen 25-40", []), land="hu")
    at = db.speichere_zielgruppe("Liebe", _profil("L", "Frauen in Wien", []), land="at")
    neu = db.speichere_zielgruppe("Neueste", _profil("N", "N", []), land="us")
    w = tagesplan.zielgruppen_je_sprache()
    # nichts markiert: je Sprache passendes Land, sonst ohne Land, sonst das neueste
    assert {s: x["id"] for s, x in w.items()} == {"de": at["id"], "en": neu["id"], "hu": hu["id"], "it": alt["id"]}
    assert all(x["automatisch"] for x in w.values())
    for z in (hu, at, alt):
        db.setze_zielgruppe_im_tagesplan(z["id"], True)
    w = tagesplan.zielgruppen_je_sprache()
    # passendes Land zuerst, sonst das neueste markierte (at); unmarkiertes "Neueste" nie
    assert w["hu"]["id"] == hu["id"] and w["de"]["id"] == at["id"]
    assert w["en"]["id"] == at["id"] and w["it"]["id"] == at["id"]
    assert not any(x["automatisch"] for x in w.values())


def test_tagesplan_schreibt_fuer_zielgruppe(frische_db):
    z = db.speichere_zielgruppe("Liebe & Beziehung", _profil("L", "Frauen 28-45 nach einer Trennung",
                                ["Bauchgefühl", "toxisch", "loslassen", "Energie", "Seelenverwandter", "Zeichen", "zu viel"]), land="at")
    db.setze_zielgruppe_im_tagesplan(z["id"], True)
    assert tagesplan.erstelle("de")["status"] == "fertig"
    frage = frische_db[-1]["frage"]
    assert "Zielgruppe (Recherche „Liebe & Beziehung“)" in frage and "Frauen 28-45 nach einer Trennung" in frage
    assert "Trennung; Neuanfang; Selbstwert; Familie" in frage and "Geld" not in frage   # hoechstens 4
    assert "Seelenverwandter; Zeichen" in frage and "zu viel" not in frage               # hoechstens 6
    assert "nicht wörtlich zitieren" in frische_db[-1]["system"]
    posts = db.lade_posts(von=HEUTE, bis=HEUTE)
    assert all(p["meta"]["zielgruppe"] == "Liebe & Beziehung" and p["meta"]["phase_index"] == 1 for p in posts)


def test_tagesplan_ohne_zielgruppe_wie_bisher(frische_db, monkeypatch):
    assert tagesplan.erstelle("de")["status"] == "fertig"
    assert "Zielgruppe" not in frische_db[-1]["frage"]
    assert all("zielgruppe" not in p["meta"] for p in db.lade_posts(von=HEUTE, bis=HEUTE))
    # Datenbankfehler beim Profil stoppt den Tagesplan nicht
    monkeypatch.setattr(db, "lade_zielgruppen", lambda limit=50: (_ for _ in ()).throw(RuntimeError("weg")))
    assert tagesplan.erstelle("en")["status"] == "fertig"


# ---------------------------------------------------------------- Bilder, Reels, Wochenpaket
import io as _io
import zipfile as _zip
import paket
import reel
from PIL import Image as _Image


def _warte(fn, bis, sekunden=120):
    ende = time.time() + sekunden
    while time.time() < ende:
        r = fn()
        if bis(r):
            return r
        time.sleep(0.3)
    raise AssertionError(f"Zeitueberschreitung: {r}")


def test_bild_vom_server_mit_zwischenspeicher(monkeypatch):
    tagesplan.erstelle("hu")
    posts = db.lade_posts(von=HEUTE, bis=HEUTE)
    post = next(p for p in posts if p["art"] == "post")
    r = client.get(f"/medien/{post['id']}/bild", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert _Image.open(_io.BytesIO(r.content)).size == (1080, 1350)            # Feed-Post: Feed-Format
    klein = client.get(f"/medien/{post['id']}/bild?klein=true", headers=AUTH)
    assert _Image.open(_io.BytesIO(klein.content)).size == (300, 375) and len(klein.content) < len(r.content)
    story = client.get(f"/medien/{post['id']}/bild?format=story&download=true", headers=AUTH)
    assert _Image.open(_io.BytesIO(story.content)).size == (1080, 1920)
    assert story.headers["content-disposition"].endswith('-post-hu-story.jpg"')
    # zweiter Aufruf kommt aus dem Zwischenspeicher, nach einer Aenderung wird neu gezeichnet
    gezeichnet = []
    echt = paket.medien.bild
    monkeypatch.setattr(paket.medien, "bild", lambda *a, **k: gezeichnet.append(1) or echt(*a, **k))
    assert client.get(f"/medien/{post['id']}/bild", headers=AUTH).content == r.content and not gezeichnet
    client.patch(f"/content/{post['id']}", json={"titel": "Neu"}, headers=AUTH)
    assert client.get(f"/medien/{post['id']}/bild", headers=AUTH).content != r.content and gezeichnet
    assert client.get("/medien/999999/bild", headers=AUTH).status_code == 404
    # geloeschter Post nimmt seine Bilder mit
    client.delete(f"/content/{post['id']}", headers=AUTH)
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        assert c.execute("select count(*) from soraya_medien where post_id = %s", (post["id"],)).fetchone()[0] == 0


def test_reel_video(frische_db):
    tagesplan.erstelle("de")
    posts = db.lade_posts(von=HEUTE, bis=HEUTE)
    r_ = next(p for p in posts if p["art"] == "reel")
    assert client.post(f"/medien/{posts[0]['id'] if posts[0]['art'] != 'reel' else posts[1]['id']}/video",
                       headers=AUTH).status_code == 400
    assert client.get(f"/medien/{r_['id']}/video", headers=AUTH).status_code == 404
    st = client.post(f"/medien/{r_['id']}/video", headers=AUTH).json()
    assert st["status"] == "laeuft"
    st = _warte(lambda: client.get(f"/medien/{r_['id']}/video/stand", headers=AUTH).json(), lambda x: x["status"] != "laeuft")
    assert st["status"] == "fertig", st
    v = client.get(f"/medien/{r_['id']}/video?download=true", headers=AUTH)
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4" and v.content[4:8] == b"ftyp"
    assert v.headers["content-disposition"].endswith('-reel-de.mp4"') and len(v.content) > 100_000
    assert client.post(f"/medien/{r_['id']}/video", headers=AUTH).json()["status"] == "fertig"   # Zwischenspeicher


def test_reel_texte_und_zeitplan():
    p = {"skript": {"hook": "Hook", "einblendungen": ["Eins", "Zwei", "Hook"], "schluss": "Ende"}, "titel": "T"}
    assert reel.texte(p) == (["Hook", "Eins", "Zwei"], "Ende")
    alt = {"skript": {"hook": "Nur Hook", "szenen": ["Kamera schwenkt"]}, "titel": "Titel", "untertitel": "Unter"}
    assert reel.texte(alt)[0] == ["Nur Hook", "Titel", "Unter"]          # Regieanweisungen nie ins Bild
    plan, end_start, dauer = reel.zeitplan(["a b c", "d e f g h i j k", "x"])
    assert all(b > a for a, b in plan) and plan[-1][1] < end_start < dauer and 10 < dauer < 25


def test_tagesplan_fragt_einblendungen(frische_db):
    tagesplan.erstelle("de")
    assert "einblendungen" in frische_db[-1]["schema"]["properties"]["posts"]["items"]["properties"]["skript"]["required"]
    assert "Text-Video" in frische_db[-1]["system"] and "einblendungen" in frische_db[-1]["system"]


def test_wochenpaket(monkeypatch):
    monkeypatch.setattr(reel, "als_bytes", lambda post: b"\x00\x00\x00\x18ftypmp42-fake-video")
    for s in ("de", "hu"):
        tagesplan.erstelle(s)
    morgen = HEUTE + timedelta(days=1)
    tagesplan.erstelle("de", tag=morgen)
    alle = db.lade_posts_zeitraum(HEUTE, morgen)
    assert len(alle) == 9
    for p in alle:
        if p["sprache"] == "de" and p["geplant_fuer"] == HEUTE:
            db.aendere_post(p["id"], {"status": "freigegeben"})
    # nur freigegebene: nichts auf Ungarisch
    leer = client.post("/wochenpaket", json={"von": HEUTE.isoformat(), "sprachen": ["hu"]}, headers=AUTH).json()
    assert leer["status"] == "leer"
    st = client.post("/wochenpaket", json={"von": HEUTE.isoformat(), "tage": 2, "sprachen": ["de", "hu"]}, headers=AUTH).json()
    st = _warte(lambda: client.get(f"/wochenpaket/{st['id']}", headers=AUTH).json(), lambda x: x["status"] != "laeuft")
    assert st["status"] == "fertig" and st["gesamt"] == 3 and st["fertig"] == 3, st
    z = client.get(f"/wochenpaket/{st['id']}/datei", headers=AUTH)
    assert z.headers["content-type"] == "application/zip"
    namen = _zip.ZipFile(_io.BytesIO(z.content)).namelist()
    tag = f"{HEUTE.isoformat()}_"
    assert any(n.endswith("/LIES-MICH.txt") for n in namen) and any(n.endswith("/uebersicht.csv") for n in namen)
    assert any(tag in n and n.endswith("DE_1_Feed-Post.jpg") for n in namen)
    assert any(tag in n and n.endswith("DE_2_Reel.mp4") for n in namen)
    assert any(tag in n and n.endswith("DE_3_Story.jpg") for n in namen) and not any("HU_" in n for n in namen)
    zf = _zip.ZipFile(_io.BytesIO(z.content))
    txt = zf.read(next(n for n in namen if n.endswith("DE_1_Feed-Post.txt"))).decode()
    assert "Text zum Kopieren" in txt and "#astrologie #mondphase" in txt and "?q=p" in txt
    csvtext = zf.read(next(n for n in namen if n.endswith("uebersicht.csv"))).decode("utf-8-sig")
    assert csvtext.count("\n") == 4 and "Feed-Post" in csvtext
    # alle Posts, ohne Videos: Reels als Bild
    st = client.post("/wochenpaket", json={"von": HEUTE.isoformat(), "tage": 2, "nur_freigegebene": False,
                                           "mit_videos": False}, headers=AUTH).json()
    st = _warte(lambda: client.get(f"/wochenpaket/{st['id']}", headers=AUTH).json(), lambda x: x["status"] != "laeuft")
    namen = _zip.ZipFile(_io.BytesIO(client.get(f"/wochenpaket/{st['id']}/datei", headers=AUTH).content)).namelist()
    assert st["gesamt"] == 9 and not any(n.endswith(".mp4") for n in namen) and any(n.endswith("DE_2_Reel.jpg") for n in namen)
    assert client.get("/wochenpaket/gibtsnicht", headers=AUTH).status_code == 404


# ---------------------------------------------------------------- Automatisch posten (Meta simuliert)
from datetime import datetime as _dt, time as _time
from urllib.parse import parse_qs as _pq, urlparse as _up
import meta
import posten


class FakeMeta:
    """Simuliert Graph API, Instagram-API und rupload; merkt sich alle Aufrufe."""
    def __init__(self, fehler_bei=None):
        self.aufrufe = []
        self.fehler_bei = fehler_bei
        self.n = 0
        self.follower = 250
        self.ig_insights_fehler = False

    def _r(self, daten, code=200):
        return SimpleNamespace(status_code=code, json=lambda: daten, text=json.dumps(daten))

    def get(self, url, params=None, timeout=None):
        self.aufrufe.append(("GET", url, dict(params or {})))
        if url.endswith("/oauth/access_token"):
            return self._r({"access_token": "LANG" if (params or {}).get("grant_type") == "fb_exchange_token" else "KURZ"})
        if url.endswith("/me/accounts"):
            return self._r({"data": [{"id": "111", "name": "Andere Seite", "access_token": "X"},
                                     {"id": "123", "name": "Soraya Luxury Astrology", "access_token": "SEITE"}]})
        if url == "https://graph.instagram.com/access_token":
            return self._r({"access_token": "IGLANG", "expires_in": 5184000})
        if url == "https://graph.instagram.com/refresh_access_token":
            return self._r({"access_token": "IGNEU", "expires_in": 5184000})
        if url.endswith("/me"):
            if "followers_count" in (params or {}).get("fields", ""):
                return self._r({"username": "soraya.astro", "followers_count": self.follower, "media_count": 12})
            return self._r({"user_id": "1789", "username": "soraya.astro"})
        if url.endswith("/insights") and "graph.instagram.com" in url:
            if self.ig_insights_fehler == "weg":
                return self._r({"error": {"message": "Unsupported get request. Object with ID '1812' does not exist, cannot be "
                                          "loaded due to missing permissions, or does not support this operation",
                                          "code": 100}}, 400)
            if self.ig_insights_fehler == "wenig":
                return self._r({"error": {"message": "(#10) Not enough viewers for the media to show insights",
                                          "code": 10}}, 400)
            if self.ig_insights_fehler:
                return self._r({"error": {"message": "(#10) Application does not have permission for this action",
                                          "code": 10}}, 400)
            if "views" in params["metric"] and "/M_ALT" in url:
                return self._r({"error": {"message": "(#100) metric views not supported", "code": 100}}, 400)
            werte = {"reach": 840, "likes": 31, "comments": 4, "saved": 7, "shares": 3, "views": 1210, "replies": 1}
            return self._r({"data": [{"name": n, "period": "lifetime", "values": [{"value": werte[n]}]}
                                     for n in params["metric"].split(",")]})
        if (params or {}).get("fields") == "like_count,comments_count":
            return self._r({"like_count": 29, "comments_count": 4, "id": url.rsplit("/", 1)[-1]})
        if "fields" in (params or {}) and params["fields"].startswith("status_code"):
            return self._r({"status_code": "FINISHED"})
        if (params or {}).get("fields") == "followers_count,fan_count":
            return self._r({"followers_count": 77, "fan_count": 70})
        if (params or {}).get("fields", "").startswith("reactions"):
            if "/V9" in url:
                return self._r({"error": {"message": "nicht gefunden"}}, 400)
            return self._r({"reactions": {"summary": {"total_count": 5}}, "comments": {"summary": {"total_count": 2}},
                            "shares": {"count": 1}})
        if (params or {}).get("fields") == "permalink":
            return self._r({"permalink": "https://www.instagram.com/p/ABC/"})
        return self._r({"error": {"message": "unbekannt " + url}}, 400)

    def post(self, url, data=None, files=None, headers=None, timeout=None):
        self.aufrufe.append(("POST", url, data if isinstance(data, dict) else {"bytes": len(data or b"")},
                             files, headers))
        if self.fehler_bei and self.fehler_bei in url:
            return self._r({"error": {"message": "Testfehler", "code": 1}}, 400)
        self.n += 1
        if url == "https://api.instagram.com/oauth/access_token":
            return self._r({"access_token": "IGKURZ", "user_id": 1789})
        if url.endswith("/video_reels") and data.get("upload_phase") == "start":
            return self._r({"video_id": "V9", "upload_url": "https://rupload.facebook.com/video-upload/v24.0/V9"})
        if "rupload" in url or url.endswith("/video_reels") or url.endswith("/photo_stories"):
            return self._r({"success": True, "post_id": "123_S"})
        if url.endswith("/photos"):
            return self._r({"id": f"F{self.n}", "post_id": f"123_{self.n}"})
        if url.endswith("/feed"):
            return self._r({"id": f"123_FEED{self.n}"})
        if url.endswith("/media"):
            return self._r({"id": f"C{self.n}"})
        if url.endswith("/media_publish"):
            return self._r({"id": f"M{self.n}"})
        return self._r({"error": {"message": "unbekannt " + url}}, 400)


@pytest.fixture
def fake_meta(monkeypatch):
    f = FakeMeta()
    monkeypatch.setattr(meta.requests, "get", f.get)
    monkeypatch.setattr(meta.requests, "post", f.post)
    for k, v in {"META_APP_ID": "app1", "META_APP_SECRET": "geheim1", "INSTAGRAM_APP_ID": "ig1",
                 "INSTAGRAM_APP_SECRET": "geheim2", "RAILWAY_PUBLIC_DOMAIN": "agent.example.app"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(reel, "als_bytes", lambda post: b"\x00\x00\x00\x18ftypmp42-video")
    return f


def _verbinde(dienst):
    r = client.get(f"/meta/verbinden/{dienst}", headers=AUTH, follow_redirects=False)
    assert r.status_code == 302
    state = _pq(_up(r.headers["location"]).query)["state"][0]
    return client.get(f"/meta/rueckruf/{dienst}?code=abc&state={state}", headers=AUTH, follow_redirects=False), r


def test_posten_einstellungen_und_ohne_app(monkeypatch):
    for k in ("META_APP_ID", "META_APP_SECRET", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"):
        monkeypatch.delenv(k, raising=False)
    d = client.get("/posten", headers=AUTH).json()
    assert d["einstellungen"]["an"] is False and d["einstellungen"]["sprache"] == "en"
    assert d["einstellungen"]["zeiten"] == {"story": "09:00", "post": "12:30", "reel": "19:00", "reel2": "19:30"}
    assert d["verbindungen"]["facebook"] == {"eingerichtet": False, "verbunden": False, "name": None, "laeuft_ab": None,
                                             "rueckruf_url": d["verbindungen"]["facebook"]["rueckruf_url"]}
    assert client.get("/meta/verbinden/facebook", headers=AUTH, follow_redirects=False).status_code == 409
    r = client.put("/posten/einstellungen", json={"zeiten": {"reel": "20:15"}, "modus": "freigabe", "sprache": "xx"}, headers=AUTH)
    e = r.json()["einstellungen"]
    assert e["zeiten"]["reel"] == "20:15" and e["zeiten"]["story"] == "09:00" and e["modus"] == "freigabe" and e["sprache"] == "en"
    assert client.put("/posten/einstellungen", json={"zeiten": {"post": "25:99"}}, headers=AUTH).status_code == 400


def test_meta_verbinden(fake_meta):
    r, start = _verbinde("facebook")
    assert start.headers["location"].startswith("https://www.facebook.com/v24.0/dialog/oauth?")
    assert "redirect_uri=https%3A%2F%2Fagent.example.app%2Fmeta%2Frueckruf%2Ffacebook" in start.headers["location"]
    assert r.headers["location"] == "/?verbunden=facebook#posten"
    v = client.get("/posten", headers=AUTH)
    assert v.json()["verbindungen"]["facebook"]["name"] == "Soraya Luxury Astrology"
    assert "SEITE" not in v.text and "LANG" not in v.text                      # Zugaenge nie ans Dashboard
    assert meta.zugang("facebook")["seite_id"] == "123"
    r, start = _verbinde("instagram")
    assert start.headers["location"].startswith("https://www.instagram.com/oauth/authorize?")
    assert "instagram_business_content_publish" in _pq(_up(start.headers["location"]).query)["scope"][0]
    assert r.headers["location"] == "/?verbunden=instagram#posten"
    assert meta.zugang("instagram")["konto_id"] == "1789" and meta.zugang("instagram")["token"] == "IGLANG"
    # gefaelschter oder alter state
    r = client.get("/meta/rueckruf/facebook?code=abc&state=facebook.1.x.falsch", headers=AUTH, follow_redirects=False)
    assert "verbindungsfehler=" in r.headers["location"]
    r = client.get("/meta/rueckruf/instagram?error=access_denied&error_description=Abgebrochen", headers=AUTH, follow_redirects=False)
    assert "Abgebrochen" in r.headers["location"]
    # verlaengern kurz vor Ablauf
    z = meta.zugang("instagram"); z["laeuft_ab"] = int(time.time()) + 86400; db.setze_einstellung("meta_instagram", z)
    assert meta.instagram_verlaengern() is True and meta.zugang("instagram")["token"] == "IGNEU"
    assert meta.instagram_verlaengern() is False
    assert client.post("/meta/trennen/facebook", headers=AUTH).status_code == 200
    assert client.get("/posten", headers=AUTH).json()["verbindungen"]["facebook"]["verbunden"] is False


def _um(h, m=0, tag=None):
    return _dt.combine(tag or HEUTE, _time(h, m), tzinfo=himmel.WIEN)


def test_automatisch_posten(fake_meta, frische_db):
    _verbinde("facebook"); _verbinde("instagram")
    tagesplan.erstelle("en"); tagesplan.erstelle("de")
    assert posten.durchlauf(_um(8)) == {"an": False}                      # Hauptschalter aus: nichts
    posten.speichere_einstellungen({"an": True})
    r = posten.durchlauf(_um(8))
    assert r["geplant"] == 6 and r["ausgefuehrt"] == []                   # nur EN: 3 Posts x 2 Plattformen
    vorher = len(fake_meta.aufrufe)
    r = posten.durchlauf(_um(12, 31))
    assert sorted(x["status"] for x in r["ausgefuehrt"]) == ["fertig"] * 4   # Story + Feed-Post
    neu = fake_meta.aufrufe[vorher:]
    fb_fotos = [a for a in neu if a[1].endswith("/123/photos")]
    assert len(fb_fotos) == 2 and any(a[2].get("published") == "false" for a in fb_fotos)
    feed = next(a for a in fb_fotos if "message" in a[2])
    assert "?q=p" in feed[2]["message"] and feed[2]["access_token"] == "SEITE" and feed[3]["source"][2] == "image/jpeg"
    ig = [a for a in neu if a[1].endswith("/1789/media")]
    assert {a[2].get("media_type") for a in ig} == {"STORIES", None}
    bild_url = next(a for a in ig if a[2].get("media_type") is None)[2]["image_url"]
    assert bild_url.startswith("https://agent.example.app/oeffentlich/medien/") and bild_url.endswith(".jpg")
    # Instagram holt das Bild ohne Anmeldung, aber nur mit gueltiger Signatur
    pfad = _up(bild_url).path
    b = client.get(pfad)
    assert b.status_code == 200 and b.headers["content-type"] == "image/jpeg"
    assert client.get(pfad.replace("-feed-", "-story-")).status_code == 404
    assert client.get(pfad[:-8] + "00000000.jpg").status_code == 404
    gepostet = [p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["status"] == "gepostet"]
    assert {p["art"] for p in gepostet} == {"post", "story"}
    # Reel stoppen -> geht nicht raus
    reel_post = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["art"] == "reel")
    client.patch(f"/content/{reel_post['id']}", json={"status": "gestoppt"}, headers=AUTH)
    assert posten.durchlauf(_um(19, 1))["ausgefuehrt"] == []
    termine = client.get("/posten", headers=AUTH).json()["termine"]
    assert sorted(t["status"] for t in termine if t["post_id"] == reel_post["id"]) == ["abgebrochen", "abgebrochen"]
    assert sum(t["status"] == "fertig" for t in termine) == 4
    # "Jetzt posten" (Reel auf Facebook: start -> rupload -> finish)
    client.patch(f"/content/{reel_post['id']}", json={"status": "entwurf"}, headers=AUTH)
    r = client.post("/posten/jetzt", json={"post_id": reel_post["id"], "plattform": "facebook"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["ergebnis"]["url"].endswith("/reel/V9")
    up = next(a for a in fake_meta.aufrufe if "rupload" in a[1])
    assert up[4]["Authorization"] == "OAuth SEITE" and up[4]["offset"] == "0" and up[2]["bytes"] > 10
    fin = [a for a in fake_meta.aufrufe if a[1].endswith("/video_reels") and a[2].get("upload_phase") == "finish"][-1]
    assert fin[2]["video_state"] == "PUBLISHED" and "#" in fin[2]["description"]
    assert client.post("/posten/jetzt", json={"post_id": reel_post["id"], "plattform": "facebook"}, headers=AUTH).status_code == 400
    r = client.post("/posten/jetzt", json={"post_id": reel_post["id"], "plattform": "instagram"}, headers=AUTH)
    ig_reel = [a for a in fake_meta.aufrufe if a[1].endswith("/1789/media")][-1][2]
    assert ig_reel["media_type"] == "REELS" and ig_reel["video_url"].endswith(".mp4") and ig_reel["share_to_feed"] == "true"
    v = client.get(_up(ig_reel["video_url"]).path)
    assert v.status_code == 200 and v.headers["content-type"] == "video/mp4"
    assert db.lade_post(reel_post["id"])["status"] == "gepostet"


def test_posten_fehler_wiederholung_freigabe_verspaetung(monkeypatch, frische_db):
    f = FakeMeta(fehler_bei="/123/photos")
    monkeypatch.setattr(meta.requests, "get", f.get)
    monkeypatch.setattr(meta.requests, "post", f.post)
    for k, v in {"META_APP_ID": "a", "META_APP_SECRET": "b", "INSTAGRAM_APP_ID": "c", "INSTAGRAM_APP_SECRET": "d"}.items():
        monkeypatch.setenv(k, v)
    _verbinde("facebook")
    tagesplan.erstelle("en")
    posten.speichere_einstellungen({"an": True, "plattformen": {"instagram": False}})
    r = posten.durchlauf(_um(12, 31))
    assert [x["status"] for x in r["ausgefuehrt"]] == ["fehler", "fehler"] and "Testfehler" in r["ausgefuehrt"][0]["fehler"]
    assert posten.durchlauf(_um(12, 32))["ausgefuehrt"] == []           # erst nach 15 Minuten wieder
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("update soraya_veroeffentlichungen set aktualisiert = now() - interval '20 minutes'")
    f.fehler_bei = None
    assert [x["status"] for x in posten.durchlauf(_um(12, 50))["ausgefuehrt"]] == ["fertig", "fertig"]
    # Freigabe-Modus: Entwurf wartet, freigegeben geht raus
    posten.speichere_einstellungen({"modus": "freigabe"})
    assert posten.durchlauf(_um(19, 5))["ausgefuehrt"] == []
    reel_post = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "reel")
    db.aendere_post(reel_post["id"], {"status": "freigegeben"})
    assert [x["status"] for x in posten.durchlauf(_um(19, 6))["ausgefuehrt"]] == ["fertig"]
    # mehr als 12 Stunden zu spaet -> verpasst
    tagesplan.erstelle("en", tag=HEUTE + timedelta(days=1))
    posten.speichere_einstellungen({"modus": "auto"})
    posten.durchlauf(_um(8, 0, HEUTE + timedelta(days=1)))
    r = posten.durchlauf(_um(23, 30, HEUTE + timedelta(days=1)))
    termine = db.lade_veroeffentlichungen(_um(0, 0, HEUTE + timedelta(days=1)), _um(23, 59, HEUTE + timedelta(days=1)))
    assert {t["art"]: t["status"] for t in termine}["story"] == "verpasst"
    assert {t["art"]: t["status"] for t in termine}["reel"] == "fertig"


# ---------------------------------------------------------------- Redaktion: Formate, Pruefung, Lernen
import redaktion


def test_wochenthemen_und_ereignisse():
    info = himmel.aufbereiten(SKY, HEUTE, "de")          # Vollmond in 2 Tagen: noch kein Ereignis-Tag
    montag = date(2026, 11, 2)                          # eine Woche ohne Saisonbeginn und Feiertag
    namen = [redaktion.wochenthema(montag + timedelta(days=i), info)["name"] for i in range(7)]
    assert namen == ["Deine Woche", "Mitmachen", "Ritual", "Astro-Wissen", "Ritual", "Mitmachen", "Rückblick & Vorschau"]
    assert redaktion.wochenthema(montag + timedelta(days=2), info)["aufforderung"]["schluessel"] == "partner"
    # die Sternzeichen und die Liebe bleiben als Variante erhalten
    di, mi = redaktion.wochenthema(montag + timedelta(days=1), info), redaktion.wochenthema(montag + timedelta(days=2), info)
    assert di["variante"] == "Sternzeichen-Check" and "Sternzeichen" in di["auftrag"]
    assert mi["variante"] == "Herz-Ritual" and "Liebe" in mi["auftrag"]
    assert "Heutiges Format: Mitmachen (Sternzeichen-Check)" in redaktion.thema_text(redaktion.selbsttest(di, []), "Link in Bio")
    assert redaktion.wochenthema(montag + timedelta(days=4), info).get("variante") is None
    morgen_voll = dict(info, vollmond={"datum": "x", "datum_text": "x", "in_tagen": 1})
    t = redaktion.wochenthema(montag, morgen_voll)
    assert t["name"] == "Großes Ereignis: Vollmond morgen" and t["anlass"] == "Vollmond morgen"


def test_qualitaetspruefung():
    gut = tagesplan_antwort("en")["posts"]
    assert [redaktion.pruefe_post(p, "en") for p in gut] == [[], [], []]
    schlecht = dict(gut[0], text="Guaranteed love und mehr: https://x.y " + "word " * 10, hashtags=["love"],
                    titel="Ein viel zu langer Titel mit sehr vielen Wörtern drin")
    b = redaktion.pruefe_post(schlecht, "en")
    assert any(x.startswith("Heikle Versprechen: guaranteed") for x in b)
    assert any("Link" in x for x in b) and any("Deutsche Wörter" in x and "und" in x for x in b)
    assert any("Überschrift zu lang" in x for x in b) and any("Hashtag" in x for x in b) and any("zu kurz" in x for x in b)
    assert redaktion.schwer(b)
    reel_p = dict(gut[1], skript={"hook": "", "einblendungen": ["eins"], "szenen": [], "schluss": ""})
    rb = redaktion.pruefe_post(reel_p, "en")
    assert "Reel ohne Hook" in rb and "Reel braucht 2 bis 4 Einblendungen" in rb
    assert redaktion.pruefe_post(dict(gut[0], text=FEED_TEXT, titel="Vollmond"), "de") == []   # Deutsch darf Deutsch


def test_tagesplan_format_vorbilder_und_meta(frische_db, monkeypatch):
    vorhanden = db.speichere_posts([{"text": "x", "titel": "Drei Zeichen fühlen es", "sprache": "de", "art": "post"}],
                                   quelle="himmel", geplant_fuer=HEUTE - timedelta(days=3))[0]
    stat = {"quellen": {f"p{vorhanden['id']}": {"schritte": {"besuch": 12}, "konten": 2}, "p999999": {"schritte": {"besuch": 50}},
                        "bio-ig": {"schritte": {"besuch": 80}}}}
    monkeypatch.setattr(redaktion, "_CACHE", {"zeit": time.time(), "daten": stat})
    tagesplan.erstelle("de")
    frage, system = frische_db[-1]["frage"], frische_db[-1]["system"]
    thema = redaktion.wochenthema(HEUTE, himmel.aufbereiten(SKY, HEUTE, "de"))
    assert f"Heutiges Format: {thema['name']}" in frage and thema["aufforderung"]["auftrag"] in frage
    assert "„Drei Zeichen fühlen es“ (post: 12 Besuche, 2 neue Konten)" in frage
    assert "Floskeln" in system and "Hook" in system and "{link_in_bio}" not in system
    posts = sorted(db.lade_posts(von=HEUTE, bis=HEUTE), key=lambda p: p["id"])
    posts = [p for p in posts if p["geplant_fuer"] == HEUTE]
    assert all(p["meta"]["thema"] == thema["name"] and p["meta"]["pruefung"] == [] for p in posts)
    feed = next(p for p in posts if p["art"] == "post")
    assert feed["meta"]["bild_punkte"] == ["Skorpion: ehrlich sein", "Stier: langsam", "Krebs: Bauchgefühl"]
    assert "bild_punkte" not in next(p for p in posts if p["art"] == "story")["meta"]
    assert client.get(f"/medien/{feed['id']}/bild", headers=AUTH).status_code == 200


def test_korrekturdurchgang(monkeypatch):
    aufrufe = []

    def antworten(system, frage, schema, **kw):
        aufrufe.append(frage)
        a = tagesplan_antwort("en")
        if len(aufrufe) == 1:
            a["posts"][0]["text"] = EN_TEXT + " Guaranteed results und mehr!"
        return a
    monkeypatch.setattr(tagesplan, "frage_json", antworten)
    tagesplan.erstelle("en")
    assert len(aufrufe) == 2 and "Guaranteed" not in aufrufe[0] and "guaranteed" in aufrufe[1].lower()
    assert "Deutsche Wörter" in aufrufe[1]
    feed = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "post")
    assert feed["meta"]["pruefung"] == [] and "Guaranteed" not in feed["text"]


def test_befund_sperrt_autopost_bis_freigabe(fake_meta, monkeypatch):
    _verbinde("facebook")
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: dict(tagesplan_antwort("en"), posts=[
        dict(tagesplan_antwort("en")["posts"][0], hashtags=["#x"])] + tagesplan_antwort("en")["posts"][1:]))
    tagesplan.erstelle("en")
    feed = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "post")
    assert feed["meta"]["pruefung"] and "Hashtag" in " ".join(feed["meta"]["pruefung"])
    posten.speichere_einstellungen({"an": True, "plattformen": {"instagram": False}})
    r = posten.durchlauf(_um(12, 40))
    # nur ein Hashtag ist eine Kleinigkeit: Story und Feed-Post gehen beide raus
    assert [x["status"] for x in r["ausgefuehrt"]] == ["fertig", "fertig"]


def test_ernster_befund_sperrt_autopost_bis_freigabe(fake_meta, monkeypatch):
    _verbinde("facebook")
    monkeypatch.setattr(tagesplan, "frage_json", lambda *a, **k: dict(tagesplan_antwort("en"), posts=[
        dict(tagesplan_antwort("en")["posts"][0], text=tagesplan_antwort("en")["posts"][0]["text"] + " Guaranteed luck!")]
        + tagesplan_antwort("en")["posts"][1:]))
    tagesplan.erstelle("en")
    feed = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "post")
    assert redaktion.schwer(feed["meta"]["pruefung"])
    posten.speichere_einstellungen({"an": True, "plattformen": {"instagram": False}})
    r = posten.durchlauf(_um(12, 40))
    assert [x["status"] for x in r["ausgefuehrt"]] == ["fertig"]          # nur die Story; Feed-Post wartet
    client.patch(f"/content/{feed['id']}", json={"status": "freigegeben"}, headers=AUTH)
    assert [x["status"] for x in posten.durchlauf(_um(12, 45))["ausgefuehrt"]] == ["fertig"]


def test_tagesplan_sprachen_im_dashboard(monkeypatch):
    monkeypatch.delenv("TAGESPLAN_SPRACHEN", raising=False)
    assert client.get("/tagesplan", headers=AUTH).json()["sprachen"] == ["de", "en", "hu", "it"]
    assert client.put("/tagesplan/sprachen", json={"sprachen": ["EN", "xx"]}, headers=AUTH).json() == {"sprachen": ["en"]}
    assert client.get("/tagesplan", headers=AUTH).json()["sprachen"] == ["en"]
    assert client.put("/tagesplan/sprachen", json={"sprachen": []}, headers=AUTH).status_code == 400
    monkeypatch.setenv("TAGESPLAN_AUTO", "1")      # im Test sonst gesperrt
    tagesplan.automatik_setzen(True)
    assert [x["sprache"] for x in tagesplan.pruefe_faellige(jetzt_stunde=12)] == ["en", "en"]


# ---------------------------------------------------------------- Looks je Format
import medien as _medien


def test_looks_je_format():
    z = _medien.zeichen_aus_text
    assert [z("Scorpio: x"), z("Skorpió – y"), z("scorpione"), z("Skorpion"), z("Leone: a"), z("Leo"), z("Leonardo"), z("")] \
        == [7, 7, 7, 7, 4, 4, None, None]
    st = _medien.stil({"art": "post", "sprache": "en", "meta": {"thema": "Sternzeichen im Fokus",
                       "bild_punkte": ["Scorpio: a", "Taurus: b", "Cancer: c"]}})
    assert st["aufbau"] == "zeichen" and st["palette"] == "zeichen" and st["label"] == "Signs in focus"
    st = _medien.stil({"art": "post", "sprache": "hu", "meta": {"thema": "Ritual", "bild_punkte": ["Gyújts gyertyát", "Írj", "Olvasd"]}})
    assert st["aufbau"] == "schritte" and st["palette"] == "ritual" and st["label"] == "Rituálé"
    assert _medien.stil({"art": "post", "meta": {"thema": "Liebe & Beziehung"}})["aufbau"] == "liebe"
    assert _medien.stil({"art": "story", "meta": {"thema": "Liebe & Beziehung"}})["aufbau"] == "mond"
    assert _medien.stil({"art": "post", "meta": {"thema": "Großes Ereignis: Vollmond morgen"}})["layout"] == "ereignis"
    assert _medien.stil({"art": "post", "meta": {}}) == {"layout": "mond", "aufbau": "mond", "palette": "nacht",
                                                         "label": None, "punkte": [], "zeichen": None}
    # eigene Aufbauten je Format: Wochenleiste, Zitat, Umfrage, grosses Zeichen zum Saisonbeginn
    assert _medien.stil({"art": "post", "meta": {"thema": "Deine Woche"}})["aufbau"] == "woche"
    assert _medien.stil({"art": "post", "meta": {"thema": "Rückblick & Vorschau"}})["aufbau"] == "zitat"
    assert _medien.stil({"art": "post", "meta": {"thema": "Mitmachen", "bild_punkte": ["A", "B"]}})["aufbau"] == "umfrage"
    saison = _medien.stil({"art": "post", "meta": {"thema": "Großes Ereignis: Skorpion-Saison beginnt"}})
    assert saison["aufbau"] == "glyphe" and saison["zeichen"] == 7
    assert _medien.mond_am(date(2026, 10, 26))[0] == 4 and _medien.mond_am(date(2026, 11, 9))[0] == 0
    basis = {"phase_index": 1, "beleuchtung": 12, "datum_kurz": "15. Oktober", "mond_phase": "Sichel", "mond_zeichen": "Skorpion"}
    for thema, punkte in (("Sternzeichen im Fokus", ["Skorpion: ehrlich", "Stier: langsam", "Krebs: Bauch"]),
                          ("Ritual", ["Kerze", "Wunsch", "Lesen"]), ("Liebe & Beziehung", []), ("Astro-Wissen", []),
                          ("Mitmachen", []), ("Mitmachen", ["Ja", "Nein", "Vielleicht"]), ("Deine Woche", []),
                          ("Rückblick & Vorschau", []), ("Großes Ereignis: Skorpion-Saison beginnt", [])):
        for f in ("feed", "story"):
            im = _medien.bild({"id": 3, "art": "post", "titel": "T", "untertitel": "U",
                               "meta": basis | {"thema": thema, "bild_punkte": punkte}}, f)
            assert im.size == (1080, 1350 if f == "feed" else 1920)
    # Farbwelt sichtbar verschieden (Liebe roetlicher als Wissen)
    liebe = _medien._verlauf_hintergrund(1080, 1350, "liebe").getpixel((540, 20))
    wissen = _medien._verlauf_hintergrund(1080, 1350, "wissen").getpixel((540, 20))
    assert liebe[0] > wissen[0] and wissen[2] > liebe[2]


def test_reel_wort_fuer_wort_und_medaillon():
    karte, kaesten = reel._textkarte("Scorpio: say what you mean", breite=900, groesse=78, name="cormorant",
                                     farbe="#F6E3B4")
    assert len(kaesten) == 1 + 4 and karte.height > 190          # Kopf (Medaillon) + 4 Woerter
    halb = reel._wort_fuer_wort(karte, kaesten, 0.3)
    voll = reel._wort_fuer_wort(karte, kaesten, 1.0)
    assert voll is karte and sum(halb.getchannel("A").getdata()) < sum(karte.getchannel("A").getdata())
    ohne, k2 = reel._textkarte("Just words here", breite=900, groesse=78, name="cormorant", farbe="#F6E3B4")
    assert len(k2) == 3


# ---------------------------------------------------------------- Claude-Anbindung
class FakeClient:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []
        self.messages = SimpleNamespace(create=self._create("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))

    def _create(self, weg):
        def create(**kw):
            self.aufrufe.append((weg, kw))
            return self.antworten.pop(0)
        return create


def antwort(text, stop="end_turn", **extra):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)], **extra)


def test_claude_strukturiert_mit_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    fake = FakeClient([antwort('{"a": 1}')])
    monkeypatch.setattr(claude, "_client", fake)
    assert claude.frage_json("S", "F", {"type": "object"}, effort="low") == {"a": 1}
    weg, kw = fake.aufrufe[0]
    assert weg == "beta" and kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "thinking" not in kw


def test_claude_altes_modell_ohne_strukturausgabe(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    fake = FakeClient([antwort('```json\n{"b": 2}\n```')])
    monkeypatch.setattr(claude, "_client", fake)
    assert claude.frage_json("S", "F", {"type": "object"}) == {"b": 2}
    weg, kw = fake.aufrufe[0]
    assert weg == "messages" and "output_config" not in kw and "Schema" in kw["system"]


def test_claude_ablehnung_und_abgeschnitten(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    fake = FakeClient([antwort("", stop="refusal", stop_details=SimpleNamespace(category="cyber")),
                       antwort("{", stop="max_tokens")])
    monkeypatch.setattr(claude, "_client", fake)
    with pytest.raises(RuntimeError, match="abgelehnt.*cyber"):
        claude.frage_json("S", "F", {})
    with pytest.raises(RuntimeError, match="abgeschnitten"):
        claude.frage_json("S", "F", {})
    assert fake.aufrufe[0][0] == "messages"  # Sonnet 5: kein server-seitiger Fallback


def test_claude_websuche_mit_pause(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    fake = FakeClient([antwort("Teil 1", stop="pause_turn"), antwort("Teil 2")])
    monkeypatch.setattr(claude, "_client", fake)
    assert claude.suche_text("S", "F") == "Teil 1\nTeil 2"
    kw = fake.aufrufe[0][1]
    assert kw["tools"][0]["type"] == "web_search_20260209"
    assert fake.aufrufe[1][1]["messages"][-1]["role"] == "assistant"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    fake = FakeClient([antwort("x")])
    monkeypatch.setattr(claude, "_client", fake)
    claude.suche_text("S", "F")
    assert fake.aufrufe[0][1]["tools"][0]["type"] == "web_search_20250305" and "output_config" not in fake.aufrufe[0][1]


def test_claude_ohne_schluessel(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(claude, "_client", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        claude.frage_json("S", "F", {})


def test_facebook_text_ohne_bio():
    p = {"id": 7, "art": "post", "sprache": "en", "text": "Your chart awaits. Link in bio ✨", "hashtags": "#astro"}
    fb = posten.text_fuer(p, "facebook")
    assert "Link below" in fb and "bio" not in fb.lower() and "?q=p7&lang=en" in fb
    assert "Link in bio" in posten.text_fuer(p, "instagram")
    assert "Link unten" in posten.text_fuer({**p, "sprache": "de", "text": "Dein Horoskop: Link in Bio"}, "facebook")
    viele = {**p, "hashtags": "#a1 #b2 #c3 #d4 #e5"}
    assert "#c3" in posten.text_fuer(viele, "facebook") and "#d4" not in posten.text_fuer(viele, "facebook")
    assert "#e5" in posten.text_fuer(viele, "instagram")


def test_instagram_bio_hinweis(monkeypatch):
    monkeypatch.setattr(meta, "zugang", lambda d: {"name": "soraya.astroguide"})
    p = {"id": 7, "art": "post", "sprache": "en", "text": "Your chart awaits. Link in bio ✨", "hashtags": "#astro"}
    ig = posten.text_fuer(p, "instagram")
    assert ig.count("bio") == 1 and "👉 @soraya.astroguide" in ig and ig.index("@soraya") < ig.index("#astro")
    reel = posten.text_fuer({**p, "art": "reel", "sprache": "hu", "text": "Mit hoz a hét?"}, "instagram")
    assert "Ingyenes horoszkóp: link a bióban 👉 @soraya.astroguide" in reel
    assert ig.count("🌐 sorayaluxuryastroguide.com") == 1 and reel.count("sorayaluxuryastroguide.com") == 1
    assert "@soraya" not in posten.text_fuer({**p, "art": "story"}, "instagram")
    fb = posten.text_fuer(p, "facebook")
    assert "@soraya" not in fb and "🔗 Your free horoscope 👉 http" in fb and "?q=p7&lang=en" in fb
    assert "🔗 Ingyenes horoszkóp 👉 http" in posten.text_fuer({**p, "sprache": "hu"}, "facebook")
    assert posten.text_fuer({**p, "text": "Hi @soraya.astroguide"}, "instagram").count("@soraya") == 1
    monkeypatch.setattr(meta, "zugang", lambda d: None)
    assert "Your free horoscope: link in bio" in posten.text_fuer({**p, "text": "Hello"}, "instagram")


def test_wirkung_facebook_reaktionen(monkeypatch, frische_db):
    f = FakeMeta()
    monkeypatch.setattr(meta.requests, "get", f.get)
    monkeypatch.setattr(meta.requests, "post", f.post)
    for k, v in {"META_APP_ID": "a", "META_APP_SECRET": "b"}.items():
        monkeypatch.setenv(k, v)
    assert client.get("/wirkung/facebook", headers=AUTH).json() == {"verbunden": False, "beitraege": []}
    _verbinde("facebook")
    tagesplan.erstelle("en")
    post = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["art"] == "post")
    assert client.post("/posten/jetzt", json={"post_id": post["id"], "plattform": "facebook"}, headers=AUTH).status_code == 200
    d = client.get("/wirkung/facebook", headers=AUTH).json()
    assert d["verbunden"] and len(d["beitraege"]) == 1
    b = d["beitraege"][0]
    assert (b["reaktionen"], b["kommentare"], b["geteilt"]) == (5, 2, 1) and b["post_id"] == post["id"]
    assert d["konto"]["follower"] == 77                                 # Follower der Seite gemerkt (fuers Cockpit)


def test_sprachen_rotation_alle_vier():
    e = {**posten.STANDARD, "sprache": "alle"}
    tage = [HEUTE + timedelta(days=i) for i in range(4)]
    je_tag = [[posten.sprache_fuer(t, a, e) for a in ("story", "post", "reel")] for t in tage]
    assert all(len(set(t)) == 3 for t in je_tag)                      # Story/Feed/Reel: drei verschiedene Sprachen
    alle = [s for t in je_tag for s in t]
    assert {s: alle.count(s) for s in "de en hu it".split()} == {"de": 3, "en": 3, "hu": 3, "it": 3}
    # das zweite Reel bekommt die vierte Sprache: jeden Tag jede Sprache genau einmal
    assert all(sorted(t + [posten.sprache_fuer(d, "reel2", e)]) == ["de", "en", "hu", "it"] for t, d in zip(je_tag, tage))
    assert posten.sprache_fuer(HEUTE, "reel2", {**e, "sprache": "hu"}) == "hu"
    assert posten.benoetigte_sprachen({**e, "sprache": "en"}, tage) == ["en"]
    assert len(posten.benoetigte_sprachen(e, tage[:2])) == 4 or len(posten.benoetigte_sprachen(e, tage[:2])) == 3


def test_planen_mit_rotation(monkeypatch, frische_db):
    for s in ("de", "en", "hu", "it"):
        tagesplan.erstelle(s)
    monkeypatch.setattr(posten, "_aktive_plattformen", lambda e: ["facebook"])
    e = posten.speichere_einstellungen({"sprache": "alle"})
    assert e["sprache"] == "alle"
    jetzt = datetime.now(himmel.WIEN).replace(hour=6, minute=0)
    assert posten.planen(e, jetzt) == 3
    termine = client.get("/posten", headers=AUTH).json()
    heute = {t["art"]: t["sprache"] for t in termine["termine"]}
    assert heute == {k: v for k, v in termine["sprachen_heute"].items() if k != "reel2"} and len(set(heute.values())) == 3
    assert set(termine["sprachen_heute"]) == {"story", "post", "reel", "reel2"}
    posten.speichere_einstellungen({"sprache": "en"})


def test_lernen_punkte_formate_und_vorbilder():
    def post(i, sprache, thema, art="post"):
        return {"id": i, "titel": f"T{i}", "art": art, "sprache": sprache, "meta": {"thema": thema},
                "reaktionen": 0, "kommentare": 0, "geteilt": 0}
    lern = [post(1, "en", "Ritual") | {"reaktionen": 10, "kommentare": 2},
            post(2, "hu", "Ritual") | {"reaktionen": 6},
            post(3, "en", "Astro-Wissen") | {"reaktionen": 1},
            post(4, "de", "Astro-Wissen")]
    stat = {"quellen": {"p4": {"schritte": {"besuch": 4}, "konten": 0}}}
    b = redaktion.bewerte(lambda i: None, statistik=stat, lern_posts=lern)
    assert [e["post"]["id"] for e in b] == [1, 4, 2, 3] and b[1]["punkte"] == 4 * 2
    v = redaktion.gut_angekommen(None, "de", bewertet=b)
    assert v[0].startswith("„T4“ (post, Format Astro-Wissen:") and "EN" in v[1] and len(v) == 3
    erk = redaktion.erkenntnisse(b)
    assert [f["name"] for f in erk["formate"]] == ["Ritual", "Astro-Wissen"]
    t = redaktion.erkenntnis_text(erk)
    assert "Ritual" in t and "Astro-Wissen" in t
    assert redaktion.erkenntnis_text({"formate": erk["formate"][:1]}) == ""
    d = client.get("/wirkung/lernen", headers=AUTH)
    assert d.status_code == 200 and "erkenntnisse" in d.json()


def test_selbsttest_hook_stil_und_aufforderung():
    import random as zufall

    def e(i, stil, auff, punkte, besuche=0, konten=0):
        return {"post": {"id": i, "meta": {"hook_stil": stil, "aufforderung": auff}}, "punkte": punkte,
                "besuche": besuche, "konten": konten}
    namen = [h["schluessel"] for h in redaktion.HOOK_STILE]
    # ohne Messung: Aufforderung bleibt der gewohnte Wechsel, Hook-Stil wird ausprobiert
    t = redaktion.selbsttest(redaktion.wochenthema(HEUTE, {}), [], zufall.Random(1))
    assert t["aufforderung"]["schluessel"] == redaktion.wochenthema(HEUTE, {})["aufforderung"]["schluessel"]
    assert t["hook_stil"]["schluessel"] in namen and t["selbsttest"]["hook_stil"] == "test"
    assert "Hook-Stil heute" in redaktion.thema_text(t, "Link in bio")
    # alle erprobt: meistens die beste, manchmal (neugier) eine andere
    b = [e(i * 10 + k, n, "partner", 30 if n == "szene" else 5) for i, n in enumerate(namen) for k in range(3)]
    wahl = [redaktion.waehle_variante(namen, b, "hook_stil", rnd=zufall.Random(s))["wahl"] for s in range(200)]
    assert 0.7 < wahl.count("szene") / 200 < 0.92 and len(set(wahl)) > 3
    # Aufforderung nach Besuchen/Konten, nicht nach Punkten
    a = [e(i, "frage", k, 50 if k == "chat" else 0, besuche=9 if k == "horoskop" else 1)
         for k in ("mondzeichen", "partner", "horoskop", "chat") for i in range(3)]
    gew = [redaktion.selbsttest(redaktion.wochenthema(HEUTE, {}), a, zufall.Random(s))["aufforderung"]["schluessel"]
           for s in range(100)]
    assert gew.count("horoskop") > 70
    erk = redaktion.erkenntnisse(b + a)
    assert erk["stile"][0]["name"] == "Alltags-Szene" and erk["aufforderungen"]


def test_tagesplan_merkt_selbsttest(frische_db):
    tagesplan.erstelle("en", erzwingen=True)
    posts = [p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["geplant_fuer"] == HEUTE]
    stile = {p["meta"].get("hook_stil") for p in posts}
    assert len(stile) == 1 and stile.pop() in redaktion.HOOK_NAMEN
    assert all(p["meta"].get("aufforderung") in redaktion.AUFFORDERUNG_NAMEN for p in posts)
    assert "Hook-Stil heute" in frische_db[-1]["frage"]


def test_punkte_mit_reichweite_und_facebook_reichweite(monkeypatch):
    assert redaktion.punkte(reichweite=250) == 2 and redaktion.punkte(besuche=1, reichweite=99) == 2
    aufrufe = []

    def get(url, **params):
        aufrufe.append(params.get("metric"))
        if params.get("metric") == "post_media_view":
            return {"data": [{"name": "post_media_view", "values": [{"value": 321}]}]}
        raise meta.MetaFehler("veraltet")
    monkeypatch.setattr(meta, "_get", get)
    assert meta.facebook_reichweite("1_2", "T") == 321 and aufrufe == ["post_impressions_unique", "post_media_view"]
    monkeypatch.setattr(meta, "_get", lambda url, **p: (_ for _ in ()).throw(meta.MetaFehler("kein Recht")))
    assert meta.facebook_reichweite("1_2", "T") is None


def test_emojis_im_bild():
    import numpy as np
    medien = _medien
    teile = medien._teile("Antworte mit 🔥 oder 🌙 ☀️ 1️⃣ 🚗")
    assert [t for t, emoji in teile if emoji] == ["🔥", "🌙", "☀️"]
    assert "🚗" not in "".join(t for t, _ in teile) and "⃣" not in "".join(t for t, _ in teile)
    assert medien.ohne_emojis("Hallo 🌙 du ✨") == "Hallo du"
    post = {"id": 3, "art": "story", "sprache": "de", "titel": "Feuer liegt in der Luft",
            "text": "Heute zählt Mut. Antworte mit 🔥 oder 🌙", "meta": {"thema": "Mitmachen"}}
    img = medien.bild(post, "story")
    assert img.size == (1080, 1920)
    # irgendwo im Fragekasten muss das Orange der Flamme sein (kein leeres Kaestchen)
    px = np.asarray(img.crop((100, 900, 980, 1500)))
    assert ((px[..., 0] > 220) & (px[..., 1] > 90) & (px[..., 1] < 170) & (px[..., 2] < 80)).sum() > 30


def test_zielgruppe_automatisch_nicht_fremdes_land():
    zeilen = [{"id": 1, "bereich": "Szerelem", "land": "hu", "im_tagesplan": False},
              {"id": 2, "bereich": "Liebe", "land": "at", "im_tagesplan": False}]
    w = tagesplan.zielgruppen_je_sprache(zeilen)
    assert set(w) == {"hu", "de"} and w["hu"]["id"] == 1 and w["de"]["id"] == 2


def test_reel_klang():
    import numpy as np
    import reel
    k = reel.klang(6.0, [0.0, 2.0, 4.0], seed=3)
    assert k.shape == (6 * 48000, 2) and k.dtype == np.int16
    spitze = int(np.abs(k.astype(np.int32)).max())
    assert 5000 < spitze < 12000                      # hoerbar, aber leise und ohne Uebersteuern
    assert abs(int(k[0, 0])) < 200 and abs(int(k[-1, 0])) < 200   # sanft rein und raus


FOLIEN = [{"titel": "Scorpio", "text": "Say the honest thing first."}, {"titel": "Taurus", "text": "Slow is fine today."},
          {"titel": "Cancer", "text": "Trust the quiet feeling."}]


def test_anlaesse_saison_vollmond_feiertage():
    import anlaesse
    assert anlaesse.ZEICHEN[anlaesse.zeichenwechsel(date(2026, 10, 23))] == "Skorpion"
    assert anlaesse.zeichenwechsel(date(2026, 10, 24)) is None
    assert anlaesse.vollmond_name(date(2026, 10, 26))[1] == "Hunter's Moon"
    assert anlaesse.vollmond_name(date(2026, 9, 26))[1] == "Harvest Moon"
    assert anlaesse.vollmond_name(date(2026, 12, 24))[1] == "Cold Moon"
    t = redaktion.wochenthema(date(2026, 10, 23), {})
    assert t["name"] == "Großes Ereignis: Skorpion-Saison beginnt" and "Geburtstagssaison" in t["auftrag"]
    t = redaktion.wochenthema(date(2026, 10, 22), {})
    assert t["name"] == "Astro-Wissen" and t["hinweise"] == ["Skorpion-Saison beginnt (morgen)"]
    assert "Außerdem steht an" in redaktion.thema_text(t, "Link in bio")
    t = redaktion.wochenthema(date(2026, 10, 26), {"vollmond": {"datum": "2026-10-26", "in_tagen": 0}})
    assert "Jägermond" in t["name"] and "Hunter's Moon" in t["auftrag"]
    assert redaktion.wochenthema(date(2026, 10, 31), {})["name"] == "Großes Ereignis: Halloween (Samhain)"


def test_karussell_bilder_und_posten(fake_meta, monkeypatch):
    def antwort(*a, **k):
        r = tagesplan_antwort("en")
        r["posts"][0] = dict(r["posts"][0], folien=FOLIEN)
        return r
    monkeypatch.setattr(tagesplan, "frage_json", antwort)
    tagesplan.erstelle("en")
    feed = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "post" and p["sprache"] == "en")
    assert feed["meta"]["folien"] == FOLIEN and _medien.anzahl_bilder(feed) == 5
    assert feed["meta"].get("folge") == 1 or feed["meta"]["thema"].startswith("Großes Ereignis")
    for nr in (2, 5):
        r = client.get(f"/medien/{feed['id']}/folie/{nr}", headers=AUTH)
        assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
    assert client.get(f"/medien/{feed['id']}/folie/6", headers=AUTH).status_code == 404
    _verbinde("facebook")
    assert client.post("/posten/jetzt", json={"post_id": feed["id"], "plattform": "facebook"}, headers=AUTH).status_code == 200
    fotos = [a for a in fake_meta.aufrufe if a[0] == "POST" and a[1].endswith("/photos")]
    beitrag = [a for a in fake_meta.aufrufe if a[0] == "POST" and a[1].endswith("/feed")][-1]
    assert len(fotos) >= 5 and all(f[2].get("published") == "false" for f in fotos[-5:])
    assert sum(k.startswith("attached_media[") for k in beitrag[2]) == 5 and "?q=p" in beitrag[2]["message"]
    # oeffentliche Adresse einer Folie (fuer Instagram) liefert das Bild nur mit passender Signatur
    url = posten.medien_url(feed, 3)
    name = url.rsplit("/", 1)[1]
    assert "-folie3-" in name and posten.oeffentliches_medium(name)[1] == "image/jpeg"
    assert posten.oeffentliches_medium(name.replace("folie3", "folie4")) is None


def test_instagram_karussell(fake_meta):
    _verbinde("instagram")
    r = meta.poste_instagram("post", "Text", "https://x/1.jpg", warten_s=5,
                             medien_urls=["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"])
    medien_aufrufe = [a for a in fake_meta.aufrufe if a[0] == "POST" and a[1].endswith("/media")]
    kinder = [a for a in medien_aufrufe if a[2].get("is_carousel_item") == "true"]
    haupt = [a for a in medien_aufrufe if a[2].get("media_type") == "CAROUSEL"]
    assert len(kinder) == 3 and len(haupt) == 1 and haupt[0][2]["children"].count(",") == 2 and r["id"]


def test_luftiger_text_und_hook_pruefung():
    assert posten._luftig("Hook line\nSecond para.\n\n\n\nThird.") == "Hook line\n\nSecond para.\n\nThird."
    lang = {"art": "post", "titel": "T", "untertitel": "", "hashtags": ["#a", "#b", "#c"],
            "text": " ".join(["word"] * 25) + "\n\n" + " ".join(["more"] * 40)}
    assert any(b.startswith("Erste Zeile zu lang") for b in redaktion.pruefe_post(lang, "en"))


def test_bildunterschrift_wie_von_der_redaktion(monkeypatch):
    monkeypatch.setattr(meta, "zugang", lambda d: {"name": "soraya.astroguide"})
    wand = ("Skorpion, Krebs, Fische – heute trifft es euch. " + "Der Mond zieht alles nach oben, was ihr sonst versteckt. " * 4
            + "Welches Zeichen bist du? Schreib es in die Kommentare 👇 Finde dein Mondzeichen – gratis. Link in Bio ✨")
    t = posten._luftig(wand)
    absaetze = t.split("\n\n")
    assert absaetze[0] == "Skorpion, Krebs, Fische – heute trifft es euch."          # Hook allein, < 125 Zeichen
    assert all(len(a) <= posten.ABSATZ_MAX for a in absaetze)                        # kurze Absaetze
    assert absaetze[-1] == "Finde dein Mondzeichen – gratis. Link in Bio ✨"          # Aufforderung am Ende
    assert absaetze[-2] == "Welches Zeichen bist du? Schreib es in die Kommentare 👇"  # Frage allein
    assert posten._luftig("Ein Satz z. B. so. Zwei.") == "Ein Satz z. B. so.\n\nZwei."   # Abkuerzung bleibt
    ig = posten.text_fuer({"id": 3, "art": "post", "sprache": "de", "text": wand, "hashtags": "#a1 #b2 #c3 #d4 #e5 #f6 #g7"}, "instagram")
    assert "Link in Bio ✨ 👉 @soraya.astroguide" in ig and "#e5" in ig and "#f6" not in ig     # max. 5 Hashtags
    b = redaktion.pruefe_post({"art": "post", "titel": "T", "text": "x " * 50, "hashtags": ["#a"] * 6}, "en")
    assert "6 Hashtags (3 bis 5 sinnvoll)" in b and not redaktion.schwer(b)
    lange_folie = {"art": "post", "titel": "T", "text": "x " * 50, "hashtags": ["#a", "#b", "#c"],
                   "_folien": [{"titel": "F", "text": "eins " * 15}]}
    assert "Folien-Text zu lang (max. 14 Wörter)" in redaktion.pruefe_post(lange_folie, "en")
    assert any(x.startswith("Erste Zeile zu lang") for x in redaktion.pruefe_post(
        {"art": "post", "titel": "T", "hashtags": ["#a", "#b", "#c"], "text": "Wort " * 21 + "Ende. " + "x " * 40}, "en"))


def test_bild_feinschliff():
    # Story mit Antwort-Knoepfen: die Anleitung "Antworte mit ..." steht nicht noch einmal im Bild
    assert _medien.ohne_antwort_anleitung("Der Mond macht alles intensiver. Schläfst du schlechter? Antworte mit 🌙 oder ☀️") \
        == "Der Mond macht alles intensiver. Schläfst du schlechter?"
    # ausgeglichener Umbruch: kein einzelnes Wort allein in der letzten Zeile
    font = _medien.schrift("cormorant", 92)
    z = _medien.ausgleichen(font, "Drei Zeichen, die heute fühlen", 900)
    assert len(z) == 2 and min(len(x) for x in z) >= 10
    assert _medien.datumszeile({"datum_kurz": "20. Okt", "mond_phase": "Zunehmende Sichel"}) == "20. Okt  ·  Zunehmende Sichel"


def test_zeit_vorschlaege():
    from datetime import timezone

    def e(i, stunde, punkte):
        return {"post": {"id": i, "art": "post", "meta": {}, "gepostet": datetime(2026, 10, 1, stunde - 2, 30, tzinfo=timezone.utc)},
                "punkte": punkte, "besuche": 0, "konten": 0}
    b = [e(i, 12, 4) for i in range(3)] + [e(10 + i, 19, 12) for i in range(3)]
    erk = redaktion.erkenntnisse(b)
    v = redaktion.zeit_vorschlaege(erk)
    assert v == [{"art": "post", "stunde": 19, "schnitt": 12.0, "statt": 12, "statt_schnitt": 4.0}]
    assert redaktion.zeit_vorschlaege(redaktion.erkenntnisse(b[:4])) == []


class FakeTikTok:
    def __init__(self):
        self.aufrufe = []
        self.status = []
        self.videos = []
        self.liste_fehler = False

    @staticmethod
    def _r(d, code=200):
        return SimpleNamespace(status_code=code, json=lambda: d, text=json.dumps(d))

    def post(self, url, data=None, json=None, headers=None, timeout=None, params=None):
        self.aufrufe.append(("POST", url, data or json))
        if url.endswith("/oauth/token/"):
            return self._r({"access_token": "TT1", "expires_in": 86400, "refresh_token": "R1",
                            "refresh_expires_in": 31536000, "open_id": "o1",
                            "scope": "user.info.basic,video.upload,video.publish,video.list"})
        if url.endswith("/creator_info/query/"):
            return self._r({"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}})
        if url.endswith("/video/init/"):
            return self._r({"data": {"publish_id": "P1", "upload_url": "https://upload.tiktok/x"}, "error": {"code": "ok"}})
        if url.endswith("/status/fetch/"):
            st = self.status.pop(0) if self.status else {"status": "SEND_TO_USER_INBOX"}
            return self._r({"data": st, "error": {"code": "ok"}})
        if url.endswith("/video/list/"):
            if self.liste_fehler:
                return self._r({"error": {"code": "scope_not_authorized", "message": "video.list"}}, 401)
            return self._r({"data": {"videos": self.videos, "has_more": False, "cursor": 0}, "error": {"code": "ok"}})
        return self._r({"error": {"code": "unknown", "message": url}}, 400)

    def get(self, url, params=None, headers=None, timeout=None):
        self.aufrufe.append(("GET", url, params))
        return self._r({"data": {"user": {"display_name": "Soraya"}}, "error": {"code": "ok"}})

    def put(self, url, data=None, headers=None, timeout=None):
        self.aufrufe.append(("PUT", url, {"bytes": len(data or b""), "range": (headers or {}).get("Content-Range")}))
        return self._r({})


def test_tiktok_verbinden_schalter_und_posten(fake_meta, monkeypatch, frische_db):
    import tiktok
    f = FakeTikTok()
    monkeypatch.setattr(tiktok.requests, "post", f.post)
    monkeypatch.setattr(tiktok.requests, "get", f.get)
    monkeypatch.setattr(tiktok.requests, "put", f.put)
    assert client.get("/tiktok/verbinden", headers=AUTH, follow_redirects=False).status_code == 409   # ohne App
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck"); monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs")
    r = client.get("/tiktok/verbinden", headers=AUTH, follow_redirects=False)
    assert r.status_code == 302 and "tiktok.com/v2/auth/authorize" in r.headers["location"]
    state = _pq(_up(r.headers["location"]).query)["state"][0]
    r = client.get(f"/tiktok/rueckruf?code=abc&state={state}", headers=AUTH, follow_redirects=False)
    assert r.headers["location"].startswith("/?verbunden=tiktok")
    d = client.get("/posten", headers=AUTH).json()
    assert d["verbindungen"]["tiktok"]["verbunden"] and d["verbindungen"]["tiktok"]["name"] == "Soraya"
    assert "token" not in json.dumps(d["verbindungen"]["tiktok"])
    # Standard: TikTok aus -> nichts geplant
    tagesplan.erstelle("en")
    _verbinde("facebook")
    posten.speichere_einstellungen({"an": True, "plattformen": {"instagram": False}})
    posten.durchlauf(_um(8))
    assert not [t for t in db.lade_veroeffentlichungen(_um(0), _um(23)) if t["plattform"] == "tiktok"]
    # einschalten: nur das Reel geht an TikTok, als Entwurf in den Posteingang
    posten.speichere_einstellungen({"plattformen": {"tiktok": True}})
    posten.durchlauf(_um(18, 59))
    tt = [t for t in db.lade_veroeffentlichungen(_um(0), _um(23)) if t["plattform"] == "tiktok"]
    assert len(tt) == 1 and tt[0]["art"] == "reel"
    posten.durchlauf(_um(19, 1))
    assert any(a[1].endswith("/inbox/video/init/") for a in f.aufrufe)
    put = [a for a in f.aufrufe if a[0] == "PUT"][-1]
    assert put[2]["range"].startswith("bytes 0-")
    # direkt: fragt erst die erlaubte Sichtbarkeit ab (ohne Pruefung nur privat)
    tiktok.poste_video(b"video", "Titel", "direkt")
    init = [a for a in f.aufrufe if a[1].endswith("/post/publish/video/init/")][-1]
    assert init[2]["post_info"]["privacy_level"] == "SELF_ONLY"
    # Feed-Post an TikTok geht nicht
    feed = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["art"] == "post")
    assert client.post("/posten/jetzt", json={"post_id": feed["id"], "plattform": "tiktok"}, headers=AUTH).status_code == 400
    assert client.post("/tiktok/trennen", headers=AUTH).status_code == 200
    assert not client.get("/posten", headers=AUTH).json()["verbindungen"]["tiktok"]["verbunden"]


def test_tiktok_token_erneuern(monkeypatch):
    import tiktok
    f = FakeTikTok()
    monkeypatch.setattr(tiktok.requests, "post", f.post)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck"); monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs")
    db.setze_einstellung("tiktok_zugang", {"token": "ALT", "laeuft_ab": int(time.time()) + 60, "refresh": "R0"})
    assert tiktok.gueltiger_token() == "TT1"
    assert f.aufrufe[-1][2]["grant_type"] == "refresh_token" and db.lade_einstellung("tiktok_zugang", {})["refresh"] == "R1"


# ---------------------------------------------------------------- Instagram-Zahlen (Insights)
def test_instagram_zahlen_follower_und_lernen(fake_meta, frische_db):
    _, start = _verbinde("instagram")
    assert "instagram_business_manage_insights" in _pq(_up(start.headers["location"]).query)["scope"][0]
    assert client.get("/posten", headers=AUTH).json()["verbindungen"]["instagram"]["zahlen"] is True
    tagesplan.erstelle("en")
    heute = [p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en"]
    for art in ("post", "story"):
        p = next(x for x in heute if x["art"] == art)
        assert client.post("/posten/jetzt", json={"post_id": p["id"], "plattform": "instagram"}, headers=AUTH).status_code == 200
    d = client.get("/wirkung/instagram", headers=AUTH).json()
    assert d["verbunden"] and d["recht_fehlt"] is False and d["konto"]["follower"] == 250
    feed = next(b for b in d["beitraege"] if b["art"] == "post")
    assert (feed["reaktionen"], feed["kommentare"], feed["gespeichert"], feed["geteilt"], feed["aufrufe"], feed["reichweite"]) == \
        (29, 4, 7, 3, 1210, 840)
    story = next(b for b in d["beitraege"] if b["art"] == "story")
    assert story["aufrufe"] == 1210 and story["reaktionen"] == 0           # Storys: keine Gefaellt-mir-Zahl
    metrik = [a[2]["metric"] for a in fake_meta.aufrufe if a[1].endswith("/insights")]
    assert "reach,views,shares,replies" in metrik and "reach,likes,comments,saved,shares,views" in metrik
    assert "IGLANG" not in json.dumps(d)
    # gemerkt -> fliesst ins Lernen (gespeichert 3 Punkte, je 100 erreicht 1 Punkt)
    lern = {x["id"]: x for x in db.lade_lern_posts(datetime.now(himmel.WIEN) - timedelta(days=1))}
    fid = feed["post_id"]
    assert lern[fid]["gespeichert"] == 7 and lern[fid]["reichweite"] == 840
    b = {e["post"]["id"]: e for e in redaktion.bewerte(lambda i: None, statistik={})}
    assert b[fid]["punkte"] == 29 + 4 * 3 + 3 * 4 + 7 * 3 + 840 // 100
    assert "7 mal gespeichert" in redaktion._details(b[fid])
    # Follower-Verlauf: Zuwachs gegen vor 7 Tagen
    posten.merke_follower(240, HEUTE - timedelta(days=8))
    fake_meta.follower = 262
    assert client.get("/wirkung/instagram", headers=AUTH).json()["konto"] == {
        "follower": 262, "am": HEUTE.isoformat(), "zuwachs_7": 22}


def test_instagram_ohne_insights_recht(fake_meta, frische_db):
    _verbinde("instagram")
    tagesplan.erstelle("en")
    p = next(x for x in db.lade_posts(von=HEUTE, bis=HEUTE) if x["sprache"] == "en" and x["art"] == "post")
    client.post("/posten/jetzt", json={"post_id": p["id"], "plattform": "instagram"}, headers=AUTH)
    # alte Verbindung (vor dem neuen Recht): Gefaellt mir/Kommentare ja, Insights nicht gefragt, Hinweis
    z = meta.zugang("instagram"); z.pop("angefragt"); z.pop("rechte"); db.setze_einstellung("meta_instagram", z)
    assert client.get("/posten", headers=AUTH).json()["verbindungen"]["instagram"]["zahlen"] is False
    vorher = len(fake_meta.aufrufe)
    d = client.get("/wirkung/instagram", headers=AUTH).json()
    assert d["recht_fehlt"] is True and d["beitraege"][0]["reaktionen"] == 29 and "aufrufe" not in d["beitraege"][0]
    assert not [a for a in fake_meta.aufrufe[vorher:] if a[1].endswith("/insights")]
    # Meta gibt zurueck "keine Berechtigung" (Recht in der App nicht hinzugefuegt): merken, nicht mehr fragen
    _verbinde("instagram")
    fake_meta.ig_insights_fehler = True
    d = client.get("/wirkung/instagram", headers=AUTH).json()
    assert d["recht_fehlt"] is True and d["beitraege"][0]["kommentare"] == 4 and "fehler" not in d["beitraege"][0]
    assert meta.zugang("instagram")["insights_fehlt"] is True
    # Die mitgeschickte Freigaben-Liste ist nicht verlaesslich: angefragt reicht, Meta entscheidet beim Abruf
    assert meta.instagram_zahlen_erlaubt({"token": "x", "rechte": ["instagram_business_basic"], "angefragt": meta.IG_SCOPES}) is True
    assert meta.instagram_zahlen_erlaubt({"token": "x", "rechte": ["instagram_business_basic"], "angefragt": meta.IG_SCOPES,
                                          "insights_fehlt": True, "insights_meldung": "(#10) x"}) is False
    # zu wenige Aufrufe ist KEIN fehlendes Recht: kein Hinweis, keine Sperre, nur noch keine Zahlen
    _verbinde("instagram")
    fake_meta.ig_insights_fehler = "wenig"
    d = client.get("/wirkung/instagram", headers=AUTH).json()
    assert d["recht_fehlt"] is False and not meta.zugang("instagram").get("insights_fehlt")
    assert meta.instagram_zahlen_erlaubt({"token": "x", "angefragt": meta.IG_SCOPES, "insights_fehlt": True,
                                          "insights_meldung": "Meta: (#10) Not enough viewers for the media"}) is True
    # abgelaufene Story / geloeschter Beitrag: nur dieser Beitrag ohne Zahlen, kein Rechte-Hinweis
    _verbinde("instagram")
    fake_meta.ig_insights_fehler = "weg"
    d = client.get("/wirkung/instagram", headers=AUTH).json()
    assert d["recht_fehlt"] is False and not meta.zugang("instagram").get("insights_fehlt")
    # unbekannte Kennzahl -> kurze Liste
    fake_meta.ig_insights_fehler = False
    assert meta.instagram_insights("M_ALT", "post", "T") == {"reach": 840, "saved": 7}


def test_zahlen_alle_6_stunden_alle_plattformen(fake_meta, monkeypatch, frische_db):
    _verbinde("instagram")
    tagesplan.erstelle("en")
    p = next(x for x in db.lade_posts(von=HEUTE, bis=HEUTE) if x["sprache"] == "en" and x["art"] == "reel")
    client.post("/posten/jetzt", json={"post_id": p["id"], "plattform": "instagram"}, headers=AUTH)
    monkeypatch.setattr(posten, "_ZAHLEN", {"zuletzt": 0.0})
    assert posten.aktualisiere_zahlen() == 1                       # Facebook nicht verbunden: Instagram trotzdem
    assert posten.aktualisiere_zahlen() == 0                       # nicht oefter als alle 6 Stunden
    z = db.lade_gemerkte_zahlen("instagram", datetime.now(himmel.WIEN) - timedelta(days=1))[0]
    assert (z["aufrufe"], z["gespeichert"], z["reaktionen"]) == (1210, 7, 29)
    assert redaktion.punkte(gespeichert=2) == 6


# ---------------------------------------------------------------- TikTok: Status, Zahlen, Fehlertexte
def test_tiktok_status_zahlen_und_fehler(fake_meta, monkeypatch, frische_db):
    import tiktok
    f = FakeTikTok()
    monkeypatch.setattr(tiktok.requests, "post", f.post)
    monkeypatch.setattr(tiktok.requests, "get", f.get)
    monkeypatch.setattr(tiktok.requests, "put", f.put)
    monkeypatch.setattr(tiktok.time, "sleep", lambda s: None)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck"); monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs")
    # Standard: ohne video.list (Display API gibt es nicht fuer jede App, sonst scheitert das Verbinden)
    assert "video.list" not in tiktok.SCOPES and tiktok.SCOPES == tiktok.SCOPES_BASIS
    monkeypatch.setattr(tiktok, "SCOPES", tiktok.SCOPES_BASIS + ",video.list")   # wie mit TIKTOK_ZAHLEN=1
    r = client.get("/tiktok/verbinden", headers=AUTH, follow_redirects=False)
    assert "video.list" in _pq(_up(r.headers["location"]).query)["scope"][0]
    state = _pq(_up(r.headers["location"]).query)["state"][0]
    client.get(f"/tiktok/rueckruf?code=abc&state={state}", headers=AUTH, follow_redirects=False)
    v = client.get("/posten", headers=AUTH).json()["verbindungen"]["tiktok"]
    assert v["zahlen"] is True and v["laeuft_ab"] > time.time() + 300 * 86400
    # Status: erst in Arbeit, dann fehlgeschlagen -> klarer Fehler
    f.status = [{"status": "PROCESSING_UPLOAD"}, {"status": "FAILED", "fail_reason": "file_format_check_failed"}]
    with pytest.raises(tiktok.TikTokFehler, match="file_format_check_failed"):
        tiktok.poste_video(b"video", "T", "entwurf")
    # direkt veroeffentlicht: TikTok nennt die Video-ID
    f.status = [{"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7444]}]
    assert tiktok.poste_video(b"video", "T", "direkt") == {"id": "7444", "url": "https://www.tiktok.com/@Soraya/video/7444"}
    # verstaendliche Fehlermeldung
    with pytest.raises(tiktok.TikTokFehler, match="5 Entwürfe"):
        tiktok._antwort(SimpleNamespace(status_code=403, json=lambda: {"error": {"code": "spam_risk_too_many_pending_share",
                                                                                   "message": "x"}}, text=""))
    # Zahlen: Reel als Entwurf geschickt, spaeter selbst gepostet -> Zuordnung ueber die Zeit
    tagesplan.erstelle("en")
    reel_post = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["art"] == "reel")
    assert client.post("/posten/jetzt", json={"post_id": reel_post["id"], "plattform": "tiktok"}, headers=AUTH).status_code == 200
    jetzt = int(time.time())
    f.videos = [{"id": "1", "title": "alt", "create_time": jetzt - 9 * 86400, "view_count": 999},
                {"id": "2", "title": "Two nights", "create_time": jetzt + 3600, "view_count": 512, "like_count": 40,
                 "comment_count": 5, "share_count": 2, "share_url": "https://www.tiktok.com/@soraya/video/2"}]
    d = client.get("/wirkung/tiktok", headers=AUTH).json()
    assert d["recht_fehlt"] is False and len(d["beitraege"]) == 1
    b = d["beitraege"][0]
    assert (b["post_id"], b["aufrufe"], b["reaktionen"], b["kommentare"], b["geteilt"]) == (reel_post["id"], 512, 40, 5, 2)
    lern = {x["id"]: x for x in db.lade_lern_posts(datetime.now(himmel.WIEN) - timedelta(days=1))}
    assert lern[reel_post["id"]]["reaktionen"] == 40 and lern[reel_post["id"]]["reichweite"] == 0
    # Recht fehlt (alte Verbindung ohne video.list)
    f.liste_fehler = True
    d = client.get("/wirkung/tiktok", headers=AUTH).json()
    assert d["recht_fehlt"] is True
    assert client.get("/posten", headers=AUTH).json()["verbindungen"]["tiktok"]["zahlen"] is False


def test_tiktok_refresh_abgelaufen_und_im_zeitplan(monkeypatch):
    import tiktok
    f = FakeTikTok()
    monkeypatch.setattr(tiktok.requests, "post", f.post)
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "ck"); monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "cs")
    db.setze_einstellung("tiktok_zugang", {"token": "ALT", "laeuft_ab": int(time.time()) + 60, "refresh": "R0",
                                           "refresh_ab": int(time.time()) - 10})
    with pytest.raises(tiktok.TikTokFehler, match="neu verbinden"):
        tiktok.gueltiger_token()
    db.setze_einstellung("tiktok_zugang", {"token": "ALT", "laeuft_ab": int(time.time()) + 60, "refresh": "R0",
                                           "refresh_ab": int(time.time()) + 999})
    monkeypatch.setattr(tiktok, "_VERSUCHT", {"zuletzt": 0.0})
    assert tiktok.erneuern_wenn_noetig() is True and tiktok.zugang()["token"] == "TT1"
    assert tiktok.erneuern_wenn_noetig() is False                    # frisch: nichts zu tun


# ---------------------------------------------------------------- LinkedIn (persoenliches Profil)
import linkedin


class FakeLinkedIn:
    """Simuliert OAuth, userinfo, Images/Videos/Posts API; alles andere geht an `weiter` (z. B. FakeMeta)."""
    def __init__(self, weiter=None):
        self.aufrufe = []
        self.weiter = weiter
        self.n = 0
        self.alte_version = None          # diese LinkedIn-Version "gibt es nicht"
        self.posts_fehler = 0             # so oft schlaegt /rest/posts fehl
        self.scope = "openid,profile,w_member_social"

    @staticmethod
    def _r(d, code=200, headers=None):
        text = json.dumps(d) if d is not None else ""
        return SimpleNamespace(status_code=code, json=lambda: d, text=text, content=text.encode(), headers=headers or {})

    def post(self, url, data=None, json=None, headers=None, timeout=None, files=None, params=None):
        if "linkedin.com" not in url:
            return self.weiter.post(url, data=data, files=files, headers=headers, timeout=timeout)
        self.aufrufe.append(("POST", url, data or json, headers))
        if url.endswith("/oauth/v2/accessToken"):
            return self._r({"access_token": "LI1", "expires_in": 5184000, "scope": self.scope})
        return self._r({"message": "unbekannt"}, 404)

    def get(self, url, params=None, headers=None, timeout=None):
        if "linkedin.com" not in url:
            return self.weiter.get(url, params=params, timeout=timeout)
        self.aufrufe.append(("GET", url, params, headers))
        if url.endswith("/v2/userinfo"):
            return self._r({"sub": "abc123", "name": "Attila K."})
        return self._r({"message": "unbekannt"}, 404)

    def put(self, url, data=None, headers=None, timeout=None):
        self.aufrufe.append(("PUT", url, {"bytes": len(data or b"")}, headers))
        return self._r(None, 201, {"etag": f"/etag{len(self.aufrufe)}"})

    def request(self, methode, url, headers=None, json=None, timeout=None, params=None):
        self.aufrufe.append((methode, url, json, headers))
        if headers.get("LinkedIn-Version") == self.alte_version:
            return self._r({"status": 426, "code": "NONEXISTENT_VERSION", "message": "Requested version is not active"}, 426)
        assert headers["X-Restli-Protocol-Version"] == "2.0.0" and headers["Authorization"] == "Bearer LI1"
        if url.endswith("/rest/images?action=initializeUpload"):
            self.n += 1
            return self._r({"value": {"uploadUrl": f"https://www.linkedin.com/dms-uploads/img{self.n}",
                                      "image": f"urn:li:image:I{self.n}"}})
        if url.endswith("/rest/videos?action=initializeUpload"):
            g = json["initializeUploadRequest"]["fileSizeBytes"]
            return self._r({"value": {"video": "urn:li:video:V1", "uploadToken": "",
                                      "uploadInstructions": [{"uploadUrl": "https://www.linkedin.com/up/v1", "firstByte": 0,
                                                              "lastByte": g - 1}]}})
        if url.endswith("/rest/videos?action=finalizeUpload"):
            return self._r(None)
        if "/rest/videos/urn" in url:
            return self._r({"status": "AVAILABLE"})
        if url.endswith("/rest/posts"):
            if self.posts_fehler:
                self.posts_fehler -= 1
                return self._r({"message": "Internal error"}, 500)
            return self._r(None, 201, {"x-restli-id": f"urn:li:share:{700 + len(self.aufrufe)}"})
        return self._r({"message": "unbekannt " + url}, 404)


@pytest.fixture
def fake_li(fake_meta, monkeypatch):
    f = FakeLinkedIn(fake_meta)
    for name in ("post", "get", "put", "request"):
        monkeypatch.setattr(linkedin.requests, name, getattr(f, name))
    monkeypatch.setattr(linkedin, "_VERSION", {"gut": None})
    monkeypatch.setattr(posten, "frage_json", lambda *a, **k: {"text": (
        "The Moon in Scorpio asks for honest conversations this week.\n\nWhen emotions run deeper, clarity helps "
        "more than speed. Take ten minutes today for the talk you keep postponing (it is worth it).")})
    return f


def _li_verbinden(f):
    r = client.get("/linkedin/verbinden", headers=AUTH, follow_redirects=False)
    assert r.status_code == 302
    q = _pq(_up(r.headers["location"]).query)
    return client.get(f"/linkedin/rueckruf?code=abc&state={q['state'][0]}", headers=AUTH, follow_redirects=False), q


def test_linkedin_verbinden_und_ablauf(fake_li, monkeypatch):
    assert client.get("/linkedin/verbinden", headers=AUTH, follow_redirects=False).status_code == 409   # ohne App
    v = client.get("/posten", headers=AUTH).json()
    assert v["verbindungen"]["linkedin"]["eingerichtet"] is False and v["einstellungen"]["plattformen"]["linkedin"] is False
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "li-id"); monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "li-geheim")
    r, q = _li_verbinden(fake_li)
    assert q["scope"] == ["openid profile w_member_social"]
    assert q["redirect_uri"] == ["https://agent.example.app/linkedin/rueckruf"]
    assert r.headers["location"] == "/?verbunden=linkedin#posten"
    v = client.get("/posten", headers=AUTH)
    li = v.json()["verbindungen"]["linkedin"]
    assert li["verbunden"] and li["name"] == "Attila K." and not li["bald_ablaufend"] and "LI1" not in v.text
    assert linkedin.zugang()["autor"] == "urn:li:person:abc123"
    # 7 Tage vor Ablauf: Warnung; danach abgelaufen (nicht mehr "verbunden", keine Termine mehr)
    z = linkedin.zugang(); z["laeuft_ab"] = int(time.time()) + 5 * 86400; db.setze_einstellung("linkedin_zugang", z)
    assert linkedin.verbindung()["bald_ablaufend"] is True
    z["laeuft_ab"] = int(time.time()) - 10; db.setze_einstellung("linkedin_zugang", z)
    assert linkedin.verbindung()["abgelaufen"] is True and linkedin.verbindung()["verbunden"] is False
    with pytest.raises(linkedin.LinkedInFehler, match="neu verbinden"):
        linkedin.poste("post", "Hallo", bild=b"jpg")
    # ohne "Share on LinkedIn": klare Meldung
    fake_li.scope = "openid,profile"
    r, _ = _li_verbinden(fake_li)
    assert "Share+on+LinkedIn" in r.headers["location"] or "Share%20on%20LinkedIn" in r.headers["location"]
    assert client.post("/linkedin/trennen", headers=AUTH).status_code == 200
    assert client.get("/posten", headers=AUTH).json()["verbindungen"]["linkedin"]["verbunden"] is False


def test_linkedin_posten_bild_karussell_reel(fake_li, monkeypatch, frische_db):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "li-id"); monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "li-geheim")
    _li_verbinden(fake_li)
    fake_li.alte_version = linkedin.versionen()[0]          # erste Version "gibt es nicht" -> naechste
    tagesplan.erstelle("en")
    heute = {p["art"]: p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en"}
    # Story: nicht auf LinkedIn
    assert client.post("/posten/jetzt", json={"post_id": heute["story"]["id"], "plattform": "linkedin"}, headers=AUTH).status_code == 400
    # Feed-Post (Karussell) -> Mehrbild-Beitrag
    r = client.post("/posten/jetzt", json={"post_id": heute["post"]["id"], "plattform": "linkedin"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["ergebnis"]["url"].startswith("https://www.linkedin.com/feed/update/urn:li:share:")
    post = [a for a in fake_li.aufrufe if a[1].endswith("/rest/posts")][-1]
    assert post[3]["LinkedIn-Version"] == linkedin.versionen()[1]
    body = post[2]
    assert body["author"] == "urn:li:person:abc123" and body["visibility"] == "PUBLIC" and body["lifecycleState"] == "PUBLISHED"
    n = paket.medien.anzahl_bilder(heute["post"])
    if n > 1:
        assert len(body["content"]["multiImage"]["images"]) == n
    else:
        assert body["content"]["media"]["id"].startswith("urn:li:image:")
    puts = [a for a in fake_li.aufrufe if a[0] == "PUT"]
    assert puts and puts[0][3]["Authorization"] == "Bearer LI1"
    # Text: sachlich umgeschrieben, Link klickbar mit Kennung und Sprache, hoechstens 3 Hashtags, geschuetzte Zeichen
    t = body["commentary"]
    assert t.startswith("The Moon in Scorpio") and "\\(it is worth it\\)" in t
    assert f"https://www.sorayaluxuryastroguide.com/?q=p{heute['post']['id']}&lang=en" in t
    assert t.count("{hashtag|\\#|") == 3 and "bio" not in t.lower()
    assert db.lade_post(heute["post"]["id"])["meta"]["linkedin_text"].startswith("The Moon")   # gemerkt
    # Reel -> Video (Upload in Teilen, Abschluss, warten bis verarbeitet)
    r = client.post("/posten/jetzt", json={"post_id": heute["reel"]["id"], "plattform": "linkedin"}, headers=AUTH)
    assert r.status_code == 200, r.text
    fin = next(a for a in fake_li.aufrufe if a[1].endswith("finalizeUpload"))
    assert fin[2]["finalizeUploadRequest"]["uploadedPartIds"] and fin[2]["finalizeUploadRequest"]["video"] == "urn:li:video:V1"
    body = [a for a in fake_li.aufrufe if a[1].endswith("/rest/posts")][-1][2]
    assert body["content"]["media"]["id"] == "urn:li:video:V1"


def test_linkedin_im_zeitplan_mit_wiederholung(fake_li, monkeypatch, frische_db):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "li-id"); monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "li-geheim")
    monkeypatch.setenv("LINKEDIN_KI", "0")                  # ohne KI: nur aufgeraeumt
    _li_verbinden(fake_li)
    tagesplan.erstelle("en")
    posten.speichere_einstellungen({"an": True, "plattformen": {"facebook": False, "instagram": False}})
    posten.durchlauf(_um(8))
    assert not [t for t in db.lade_veroeffentlichungen(_um(0), _um(23)) if t["plattform"] == "linkedin"]   # Standard aus
    posten.speichere_einstellungen({"plattformen": {"linkedin": True}})
    posten.durchlauf(_um(8))
    li = [t for t in db.lade_veroeffentlichungen(_um(0), _um(23)) if t["plattform"] == "linkedin"]
    assert sorted(t["art"] for t in li) == ["post", "reel"]                      # keine Story
    fake_li.posts_fehler = 1
    r = posten.durchlauf(_um(12, 31))
    assert r["ausgefuehrt"][0]["status"] == "fehler" and "Internal error" in r["ausgefuehrt"][0]["fehler"]
    # nach 15 Minuten der zweite Versuch
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("update soraya_veroeffentlichungen set aktualisiert = now() - interval '20 minutes' where plattform = 'linkedin'")
    r = posten.durchlauf(_um(12, 50))
    assert [x["status"] for x in r["ausgefuehrt"]] == ["fertig"]
    feed = next(t for t in db.lade_veroeffentlichungen(_um(0), _um(23)) if t["plattform"] == "linkedin" and t["art"] == "post")
    assert feed["status"] == "fertig" and feed["versuche"] == 2 and feed["extern_id"].startswith("urn:li:share:")
    text = [a for a in fake_li.aufrufe if a[1].endswith("/rest/posts")][-1][2]["commentary"]
    assert "✨" not in text and "?q=p" in text
    posten.speichere_einstellungen({"an": False})


def test_linkedin_text_und_versionen():
    assert linkedin.little_text("Hallo (Test) #astro #3 a_b https://x.com/?q=p1&lang=en") == \
        "Hallo \\(Test\\) {hashtag|\\#|astro} \\#3 a\\_b https://x.com/?q=p1&lang=en"
    assert linkedin.versionen(date(2026, 1, 15)) == ["202511", "202510", "202509", "202508"]
    p = {"id": 5, "sprache": "de", "art": "post", "meta": {"linkedin_text": "Sachlich."}, "text": "x", "hashtags": "#a #b #c #d"}
    assert posten.text_fuer(p, "linkedin") == ("Sachlich.\n\nDein persönliches Horoskop, kostenlos: "
                                              "https://www.sorayaluxuryastroguide.com/?q=p5&lang=de\n\n#a #b #c")
    assert posten._li_regelbasiert("Der Mond ✨ wächst.\n\nDein Horoskop: Link in Bio 🔮", "de") == "Der Mond wächst.\n\nDein Horoskop: Link unten"


# ---------------------------------------------------------------- Mehr Wirkung: zweites Reel, Kommentar-Frage, Storys
def _vier_eintraege(sprache="en"):
    d = tagesplan_antwort(sprache)
    d["posts"].append({"art": "reel", "platform": "tiktok", "titel": "Quick sign check", "untertitel": "U",
                       "text": "Scorpio, Cancer, Pisces: today hits different.", "hashtags": TAGS[:4], "bild_punkte": [],
                       "folien": [],
                       "skript": {"hook": "Three signs feel it first", "szenen": ["S1", "S2"],
                                  "einblendungen": ["Scorpio: says it out loud", "Pisces: finally rests"],
                                  "schluss": "Which one are you?"}})
    return d


def test_zweites_reel_tagesplan_und_posten(monkeypatch, frische_db):
    aufrufe = []
    monkeypatch.setattr(tagesplan, "frage_json", lambda s, f, sch, **k: aufrufe.append(1) or _vier_eintraege("en"))
    assert tagesplan.erstelle("en")["posts"] == 4 and len(aufrufe) == 1        # beide Reels aus EINEM Aufruf
    assert "genau vier Einträge" in tagesplan.SYSTEM_PROMPT and "ZWEITES Reel" in tagesplan.SYSTEM_PROMPT
    posts = [p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en"]
    reels = sorted((p for p in posts if p["art"] == "reel"), key=lambda p: p["id"])
    assert len(reels) == 2 and "reel_nr" not in reels[0]["meta"] and reels[1]["meta"]["reel_nr"] == 2
    assert [posten.platz(p) for p in reels] == ["reel", "reel2"]
    # das Model hat beim zweiten Reel die Kommentar-Frage vergessen -> der Agent ergaenzt genau eine
    assert reels[1]["text"].count("\n\n") == 1 and redaktion.hat_kommentar_frage(reels[1]["text"])
    assert reels[1]["meta"]["pruefung"] == []
    # Posten: eigene Uhrzeit fuers zweite Reel, LinkedIn nur das erste, TikTok beide
    monkeypatch.setattr(posten, "_aktive_plattformen", lambda e: ["facebook", "tiktok", "linkedin"])
    e = posten.speichere_einstellungen({"sprache": "en", "zeiten": {"story": "06:00", "post": "18:00", "reel": "09:00"}})
    assert e["zeiten"] == {"story": "06:00", "post": "18:00", "reel": "09:00", "reel2": "19:30"}
    posten.planen(e, _um(5))
    t = [x for x in db.lade_veroeffentlichungen(_um(0), _um(23, 59)) if x["post_id"] in (reels[0]["id"], reels[1]["id"])]
    erstes = {(x["plattform"], x["geplant_um"].astimezone(himmel.WIEN).strftime("%H:%M")) for x in t if x["post_id"] == reels[0]["id"]}
    zweites = {(x["plattform"], x["geplant_um"].astimezone(himmel.WIEN).strftime("%H:%M")) for x in t if x["post_id"] == reels[1]["id"]}
    assert erstes == {("facebook", "09:00"), ("tiktok", "09:00"), ("linkedin", "09:00")}
    assert zweites == {("facebook", "19:30"), ("tiktok", "19:30")}
    assert {x["reel_nr"] for x in t if x["post_id"] == reels[1]["id"]} == {2}
    assert posten.speichere_einstellungen({"zeiten": {"reel2": "20:45"}})["zeiten"]["reel2"] == "20:45"
    # Wochenpaket: zwei Reels, zwei verschiedene Dateinamen
    assert main._dateiname(reels[1], "mp4").startswith(f"soraya-{HEUTE}-reel2-en")
    posten.speichere_einstellungen({"zeiten": {"story": "09:00", "post": "12:30", "reel": "19:00", "reel2": "19:30"}})


def test_kommentar_frage_vier_sprachen():
    for s in ("de", "en", "hu", "it"):
        assert len(redaktion.KOMMENTAR_FRAGEN[s]) >= 5
        for f in redaktion.KOMMENTAR_FRAGEN[s]:
            assert redaktion.hat_kommentar_frage("Hook zuerst. " + f), f          # jede Frage wird wiedererkannt
            if s != "de":
                assert not redaktion._DEUTSCH_IN_FREMD.search(f), f
    text = "Your Moon is loud today.\n\nSay the thing softly.\n\nFind your Moon sign free – link in bio ✨"
    neu = redaktion.mit_kommentar_frage(text, "en", "x")
    absaetze = neu.split("\n\n")
    assert len(absaetze) == 4 and absaetze[-1].startswith("Find your Moon sign") and absaetze[2] in redaktion.KOMMENTAR_FRAGEN["en"]
    assert redaktion.mit_kommentar_frage(neu, "en", "y") == neu                    # nie doppelt
    # Aufforderung im selben Absatz wie der Text
    neu = redaktion.mit_kommentar_frage("Mond im Skorpion. Sag es ruhig. Dein Mondzeichen gratis: Link in Bio", "de", "a")
    assert neu.split("\n\n")[-1] == "Dein Mondzeichen gratis: Link in Bio" and neu.count("\n\n") == 2
    # schon eine Frage am Ende -> nichts anhaengen; Hook-Frage allein zaehlt nicht
    assert redaktion.mit_kommentar_frage("Hook. Welches Zeichen bist du?", "de") == "Hook. Welches Zeichen bist du?"
    assert redaktion.mit_kommentar_frage("Bist du müde?", "de", "z") != "Bist du müde?"
    # Mitmachen mit A/B/C im Bild: nach dem Buchstaben fragen
    assert redaktion.kommentar_frage("hu", antworten=3) == "A, B vagy C? Írd meg a betűdet kommentben 👇"
    assert redaktion.kommentar_frage("it", antworten=2).startswith("A o B?")
    # Qualitaetspruefung: Hinweis, kein schwerer Befund
    b = redaktion.pruefe_post({"art": "reel", "titel": "T", "text": "Only one line here.", "hashtags": TAGS,
                               "skript": {"hook": "H", "einblendungen": ["a", "b"]}}, "en")
    assert any(x.startswith("Frage zum Kommentieren fehlt") for x in b) and not redaktion.schwer(b)
    assert not any("Kommentieren" in x for x in redaktion.pruefe_post({"art": "story", "titel": "T", "text": "Kurz und gut, oder?"}, "de"))


def test_kommentar_frage_beim_posten(monkeypatch):
    monkeypatch.setattr(posten, "_instagram_name", lambda: "soraya.astroguide")
    p = {"id": 7, "art": "post", "sprache": "it", "hashtags": "#astrologia #luna #oroscopo",
         "text": "La Luna è in Scorpione.\n\nDi' la verità con calma.\n\nIl tuo oroscopo gratis: link in bio",
         "meta": {"thema": "Mitmachen", "bild_punkte": ["Sì", "No", "Forse"]}}
    ig = posten.text_fuer(p, "instagram")
    teile = ig.split("\n\n")
    assert teile[2] == "A, B o C? Scrivi la tua lettera nei commenti 👇"
    assert teile[3].startswith("Il tuo oroscopo gratis: link in bio 👉 @soraya.astroguide") and teile[-1] == "#astrologia #luna #oroscopo"
    fb = posten.text_fuer(p, "facebook")
    assert fb.count("Scrivi la tua lettera") == 1 and fb.index("Scrivi la tua") < fb.index("?q=p7")
    story = {**p, "art": "story", "text": "Come dormi? Rispondi con 🌙", "meta": {}}
    assert "commenti" not in posten.text_fuer(story, "instagram")
    reel = {"id": 8, "art": "reel", "sprache": "de", "text": "Zwei Nächte bis Vollmond.", "hashtags": "#a #b #c"}
    t = posten.text_fuer(reel, "tiktok")
    assert t.split("\n\n")[1] in redaktion.KOMMENTAR_FRAGEN["de"] and t.endswith("#a #b #c")


def test_storys_messen_solange_sie_leben(fake_meta, frische_db):
    _verbinde("instagram")
    tagesplan.erstelle("en")
    story = next(p for p in db.lade_posts(von=HEUTE, bis=HEUTE) if p["sprache"] == "en" and p["art"] == "story")
    assert client.post("/posten/jetzt", json={"post_id": story["id"], "plattform": "instagram"}, headers=AUTH).status_code == 200
    jetzt = datetime.now(himmel.WIEN)
    # vor 2 Stunden: noch nicht faellig; nicht gemessen -> zaehlt nicht als 0
    assert posten.miss_storys(jetzt + timedelta(minutes=30)) == 0
    lern = {x["id"]: x for x in db.lade_lern_posts(jetzt - timedelta(days=1))}
    assert lern[story["id"]]["gemessen"] is False
    b = redaktion.bewerte(lambda i: None, statistik={})
    assert redaktion.nicht_gemessen(b) == {"story": 1} and redaktion.erkenntnisse(b, min_posts=1)["arten"] == []
    # nach gut 2 Stunden: gemessen (Reichweite 840 -> 8 Punkte, 1 Antwort -> 3, 3x geteilt -> 12)
    vorher = len(fake_meta.aufrufe)
    assert posten.miss_storys(jetzt + timedelta(hours=2, minutes=5)) == 1
    assert any(a[1].endswith("/insights") for a in fake_meta.aufrufe[vorher:])
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:     # so tun, als waere die Messung um 2 h gewesen
        c.execute("update soraya_veroeffentlichungen set zahlen_am = aktualisiert + interval '2 hours 5 minutes' "
                  "where post_id = %s", (story["id"],))
    assert posten.miss_storys(jetzt + timedelta(hours=3)) == 0                    # zweimal nicht
    assert posten.miss_storys(jetzt + timedelta(hours=20, minutes=5)) == 1          # zweite Messung kurz vor Ablauf
    assert posten.miss_storys(jetzt + timedelta(hours=25)) == 0                     # abgelaufen: nicht mehr fragen
    lern = {x["id"]: x for x in db.lade_lern_posts(jetzt - timedelta(days=1))}
    assert lern[story["id"]]["gemessen"] is True and lern[story["id"]]["kommentare"] == 1
    e = {x["post"]["id"]: x for x in redaktion.bewerte(lambda i: None, statistik={})}[story["id"]]
    assert e["punkte"] == 840 // 100 + 1 * 3 + 3 * 4 and redaktion.erkenntnisse([e], min_posts=1)["arten"][0]["name"] == "story"


def test_erkenntnis_text_mit_heutigem_format():
    erk = {"formate": [{"name": "Mitmachen", "posts": 3, "schnitt": 5.0}, {"name": "Ritual", "posts": 3, "schnitt": 4.0},
                       {"name": "Astro-Wissen", "posts": 2, "schnitt": 3.0},
                       {"name": "Sternzeichen im Fokus", "posts": 3, "schnitt": 2.0}]}
    t = redaktion.erkenntnis_text(erk, "Mitmachen")
    assert "Heute ist Mitmachen dran" in t and "Schwächer" not in t
    t = redaktion.erkenntnis_text(erk, "Deine Woche")
    assert "Sternzeichen im Fokus" not in t                   # altes Format steht nicht mehr im Wochenplan


def test_tiktok_selbst_hochgeladen_ueber_titel():
    import tiktok
    reels = [{"post_id": 7, "titel": "Scorpio Season: 3 Changes"}, {"post_id": 8, "titel": "Kurz"}]
    liste = [{"id": "v1", "title": "Scorpio Season: 3 Changes Scorpio season just started, and i…", "create_time": 1792780000,
              "share_url": "https://tiktok/v1", "view_count": 90, "like_count": 1, "comment_count": 0, "share_count": 0},
             {"id": "v2", "title": "", "create_time": 1792700000, "view_count": 247}]
    z = tiktok.zuordnen_nach_titel(reels, liste)
    assert len(z) == 1 and z[0]["post_id"] == 7 and z[0]["aufrufe"] == 90 and z[0]["reaktionen"] == 1
    # in der App gepostet: Text nur in video_description
    z2 = tiktok.zuordnen_nach_titel(reels, [{"id": "v3", "title": "", "video_description": "Scorpio Season: 3 Changes ✨ #astro",
                                             "view_count": 5}])
    assert len(z2) == 1 and z2[0]["post_id"] == 7 and z2[0]["aufrufe"] == 5
    # zu kurze Titel werden nicht geraten
    assert tiktok.zuordnen_nach_titel([{"post_id": 8, "titel": "Kurz"}], [{"id": "x", "title": "Kurz und gut"}]) == []


def test_tiktok_konto_nur_mit_stats_recht(monkeypatch):
    import tiktok
    monkeypatch.setattr(tiktok, "zugang", lambda: {"token": "t", "rechte": ["user.info.basic"]})
    assert tiktok.konto() is None
    monkeypatch.setattr(tiktok, "zugang", lambda: {"token": "t", "rechte": ["user.info.basic", "user.info.stats"]})
    monkeypatch.setattr(tiktok, "gueltiger_token", lambda: "t")
    monkeypatch.setattr(tiktok, "_get_mit", lambda tok, pfad, **kw: {"data": {"user": {"follower_count": 12, "likes_count": 3, "video_count": 2}}})
    assert tiktok.konto() == {"follower": 12, "likes": 3, "videos": 2}


# ---------------------------------------------------------------- Zahlen-Cockpit (Wirkung)
import cockpit


def _gepostet(titel, art, tag, zahlen, thema="Ritual", stil="frage"):
    """Post mit Veroeffentlichungen (je Plattform gemerkte Zahlen) am Tag `tag` um 12 Uhr."""
    p = db.speichere_posts([{"art": art, "titel": titel, "text": "x"}], quelle="tagesplan", geplant_fuer=tag,
                           meta={"thema": thema, "hook_stil": stil})[0]
    um = datetime.combine(tag, _time(12), tzinfo=himmel.WIEN)
    for pl, z in zahlen.items():
        zid = db.plane_veroeffentlichung(p["id"], pl, um, zurueckgeben=True)
        db.setze_veroeffentlichung(zid, "fertig", extern_id=f"{pl}{p['id']}", url=f"https://x/{pl}")
        if z is not None:
            db.speichere_zahlen(p["id"], pl, z.get("r", 0), z.get("k", 0), z.get("g", 0), reichweite=z.get("reach"),
                                gespeichert=z.get("s"), aufrufe=z.get("views"))
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            c.execute("update soraya_veroeffentlichungen set aktualisiert = %s where id = %s", (um, zid))
    return p["id"]


def _stat_fake(monkeypatch, tage_werte, quellen=None):
    monkeypatch.setenv("AGENT_STATS_TOKEN", "z" * 32)
    gefragt = []

    def fake_get(url, params=None, headers=None, timeout=None):
        gefragt.append(params["tage"])
        tage = [{"datum": (HEUTE - timedelta(days=i)).isoformat(), **tage_werte(i)} for i in range(params["tage"])][::-1]
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "data": {"tage": tage, "quellen": quellen or {}}}, text="")
    monkeypatch.setattr(wirkung.requests, "get", fake_get)
    return gefragt


def test_cockpit_kennzahlen_vergleich_top_und_tabelle(monkeypatch, frische_db):
    cockpit.leeren()
    # dieser Zeitraum (7 Tage): 2 Posts, davor: 1 Post
    a = _gepostet("Ritual-Reel", "reel", HEUTE - timedelta(days=1),
                  {"instagram": {"r": 40, "k": 5, "g": 3, "s": 10, "reach": 900, "views": 1500},
                   "tiktok": {"r": 100, "k": 8, "g": 2, "views": 2000}})
    b = _gepostet("Feed", "post", HEUTE - timedelta(days=3), {"facebook": {"r": 10, "k": 1, "g": 0},       # ohne Reichweite
                                                               "instagram": None})                       # noch nicht gemessen
    _gepostet("Alt", "post", HEUTE - timedelta(days=9), {"instagram": {"r": 20, "reach": 1000}})
    _gepostet("Zu alt", "post", HEUTE - timedelta(days=20), {"instagram": {"r": 99, "reach": 9999}})
    gefragt = _stat_fake(monkeypatch, lambda i: {"schnellstart_berechnet": 2, "gratis_tests": 3 if i < 7 else 0,
                                                   "neue_konten": 1 if i < 7 else 0},
                         {f"p{b}": {"schritte": {"besuch": 6}, "konten": 1,
                                    "tage": {(HEUTE - timedelta(days=2)).isoformat(): 5, (HEUTE - timedelta(days=8)).isoformat(): 4}}})
    d = client.get("/wirkung/cockpit?tage=7", headers=AUTH).json()
    assert gefragt == [14] and d["statistik"] == "ok" and d["von"] == (HEUTE - timedelta(days=6)).isoformat()
    k = {x["schluessel"]: x for x in d["kpis"]}
    # Erreicht: Reichweite, sonst Aufrufe (TikTok 2000); Facebook ohne Reichweite = 0
    assert k["erreicht"]["wert"] == 900 + 2000 and k["erreicht"]["vorher"] == 1000 and k["erreicht"]["aenderung"] == 190
    assert k["reaktionen"]["wert"] == (40 + 5 + 3 + 10) + (100 + 8 + 2) + (10 + 1) and k["reaktionen"]["vorher"] == 20
    assert k["besuche"]["wert"] == 5 and k["besuche"]["vorher"] == 4 and k["besuche"]["aenderung"] == 25
    assert k["konten"]["wert"] == 7 and k["konten"]["vorher"] == 0 and k["konten"]["aenderung"] is None   # neutral
    # Tabelle: eine Zeile je Post, Spalten je Plattform; "noch nicht gemessen" bleibt leer statt 0
    zeilen = {z["id"]: z for z in d["beitraege"]}
    assert set(zeilen) == {a, b}
    tt = zeilen[a]["plattformen"]["tiktok"]
    assert {k: tt[k] for k in ("erreicht", "reaktionen", "url", "aufrufe", "gefaellt", "kommentare")} == \
        {"erreicht": 2000, "reaktionen": 110, "url": "https://x/tiktok", "aufrufe": 2000, "gefaellt": 100, "kommentare": 8}
    assert tt["gepostet"].startswith((HEUTE - timedelta(days=1)).isoformat()) and tt["zahlen_am"]
    assert zeilen[b]["plattformen"]["instagram"]["erreicht"] is None and zeilen[b]["plattformen"]["facebook"]["erreicht"] == 0
    assert zeilen[b]["besuche"] == 6 and zeilen[b]["konten"] == 1 and zeilen[b]["punkte"] == 6 * 2 + 15 + 10 + 3
    assert [t["id"] for t in d["top"]] == sorted([a, b], key=lambda i: -zeilen[i]["punkte"])
    # Trichter: Erreicht -> Besuche ist der schwaechste Schritt
    t = d["trichter"]
    assert [s["wert"] for s in t["stufen"]] == [2900, 5, 21, 7] and t["schwach"] == "besuche" and "klicken" in t["hinweis"]
    assert t["stufen"][2]["quote"] == 420.0 and not t["stufen"][2].get("schwach")    # ueber 100 % nie "schwach"
    # Verlauf: Erreicht am Posting-Tag, Besuche je Tag
    v = {x["datum"]: x for x in d["verlauf"]}
    assert len(v) == 7 and v[(HEUTE - timedelta(days=1)).isoformat()]["erreicht"] == 2900
    assert v[(HEUTE - timedelta(days=2)).isoformat()]["besuche"] == 5 and v[(HEUTE - timedelta(days=3)).isoformat()]["posts"] == 1
    # nichts verbunden -> keine Follower-Zeile
    assert d["follower"] == [] and len(d["lernen"]["saetze"]) == 3
    # Auswertung fuer die Unterreiter: Reichweite je Plattform und Tag, ehrlich "zu wenig Daten" bei 2 Posts
    an = d["analyse"]
    pt = {x["datum"]: x for x in an["plattform_tage"]}
    assert pt[(HEUTE - timedelta(days=1)).isoformat()]["instagram"] == 900 and pt[(HEUTE - timedelta(days=1)).isoformat()]["tiktok"] == 2000
    assert an["gemessen"] == 2 and an["erkennt"][-1]["id"] == "duenn" and "zu wenig Daten" in an["erkennt"][-1]["text"]
    assert {z["plattform"] for z in an["plattformen"]["zeilen"]} == {"facebook", "instagram", "tiktok"}
    assert an["plattformen"]["post_link_besuche"] == 6 and d["zeiten"]["reel"] == "19:00"
    assert [s["name"] for s in an["zeiten"]["eingestellt"]] == ["Story", "Feed-Post", "Reel", "2. Reel"]
    assert len(an["stile"]) == len(redaktion.HOOK_NAMEN) and all(x["sicherheit"] == "wenig" for x in an["stile"])
    assert an["sprachen"] == [] and an["trichter_vorher"]["stufen"][0]["wert"] == 1000
    assert zeilen[b]["punkte_teile"][0] == {"name": "Neue Konten", "anzahl": 1, "punkte": 15}
    # zwischengespeichert: kein zweiter Engine-Aufruf
    client.get("/wirkung/cockpit?tage=7", headers=AUTH)
    assert gefragt == [14]
    cockpit.leeren()
    client.get("/wirkung/cockpit?tage=30", headers=AUTH)
    assert gefragt[-1] == 60


def test_tiktok_selbst_gepostet_zaehlt_ueberall(monkeypatch, frische_db):
    """Selbst hochgeladenes Reel (kein TikTok-Termin) bekommt seine Zahlen; eigene Videos ohne Soraya-Post
    zaehlen bei Erreicht, Reaktionen, Reichweite pro Tag und Plattformen mit."""
    import tiktok
    cockpit.leeren()
    monkeypatch.delenv("AGENT_STATS_TOKEN", raising=False)
    tag = HEUTE - timedelta(days=1)
    reel = db.speichere_posts([{"art": "reel", "titel": "Scorpio Season: 3 Changes", "text": "x"}], quelle="tagesplan",
                              geplant_fuer=tag, meta={"thema": "Ritual"})[0]
    um = int(datetime.combine(tag, _time(18), tzinfo=himmel.WIEN).timestamp())
    videos = [{"id": "71", "title": "", "video_description": "Scorpio Season: 3 Changes ✨ #astro", "create_time": um,
               "share_url": "https://tiktok/71", "view_count": 300, "like_count": 9, "comment_count": 2, "share_count": 1},
              {"id": "72", "title": "Mein eigenes Video", "create_time": um + 3600, "view_count": 150, "like_count": 4,
               "comment_count": 0, "share_count": 0}]
    db.setze_einstellung(tiktok.SCHLUESSEL, {"token": "t", "rechte": ["video.list"]})
    monkeypatch.setattr(tiktok, "zahlen_erlaubt", lambda z: True)
    monkeypatch.setattr(tiktok, "videos", lambda n=20: videos)
    monkeypatch.setattr(tiktok, "konto", lambda: None)
    monkeypatch.setattr(tiktok, "verbindung", lambda: {"verbunden": True, "zahlen": True})
    zeilen = posten.zahlen_tiktok(datetime.now(himmel.WIEN) - timedelta(days=14))
    assert [(z["post_id"], z["aufrufe"]) for z in zeilen] == [(reel["id"], 300)]
    # jetzt gibt es einen fertigen TikTok-Eintrag mit Zahlen; ein zweiter Abruf passt ueber die Video-ID
    g = db.lade_gemerkte_zahlen("tiktok", datetime.now(himmel.WIEN) - timedelta(days=14))
    assert len(g) == 1 and g[0]["extern_id"] == "71" and g[0]["aufrufe"] == 300 and g[0]["reaktionen"] == 9
    videos[0]["view_count"] = 420
    assert [z["aufrufe"] for z in posten.zahlen_tiktok(datetime.now(himmel.WIEN) - timedelta(days=14))] == [420]
    assert len(db.lade_gemerkte_zahlen("tiktok", datetime.now(himmel.WIEN) - timedelta(days=14))) == 1
    gemerkt = {v["id"]: v for v in posten.tiktok_videos()}
    assert gemerkt["71"]["post_id"] == reel["id"] and gemerkt["72"]["post_id"] is None and gemerkt["72"]["aufrufe"] == 150
    # Cockpit: Reel (420) + eigenes Video (150)
    d = client.get("/wirkung/cockpit?tage=7", headers=AUTH).json()
    k = {x["schluessel"]: x for x in d["kpis"]}
    assert k["erreicht"]["wert"] == 420 + 150 and k["reaktionen"]["wert"] == (9 + 2 + 1) + 4
    assert d["verbunden"]["tiktok"] is True
    pt = {x["datum"]: x for x in d["analyse"]["plattform_tage"]}
    assert pt[tag.isoformat()]["tiktok"] == 570
    pv = {z["plattform"]: z for z in d["analyse"]["plattformen"]["zeilen"]}
    assert pv["tiktok"]["posts"] == 1 and pv["tiktok"]["videos_extra"] == 1 and pv["tiktok"]["erreicht"] == 570
    assert {x["datum"]: x for x in d["verlauf"]}[tag.isoformat()]["erreicht"] == 570
    assert [z["plattformen"]["tiktok"]["erreicht"] for z in d["beitraege"]] == [420]


def test_plattformen_verbunden_auch_ohne_zahlen():
    import auswertung
    tage = [HEUTE - timedelta(days=i) for i in range(6, -1, -1)]
    pv = auswertung.plattform_vergleich([], {}, tage, verbunden=["tiktok"])
    assert [(z["plattform"], z["erreicht"], z["anteil_erreicht"]) for z in pv["zeilen"]] == [("tiktok", 0, None)]


def test_cockpit_ohne_statistik_und_ohne_posts(monkeypatch, frische_db):
    cockpit.leeren()
    monkeypatch.delenv("AGENT_STATS_TOKEN", raising=False)
    d = client.get("/wirkung/cockpit?tage=90", headers=AUTH).json()
    assert d["tage"] == 90 and d["statistik"] == "nicht_verbunden"
    k = {x["schluessel"]: x for x in d["kpis"]}
    assert k["erreicht"]["wert"] == 0 and k["erreicht"]["aenderung"] is None and k["besuche"]["wert"] is None
    assert d["top"] == [] and d["beitraege"] == [] and d["trichter"]["schwach"] is None
    assert "zu wenig Daten" in d["trichter"]["hinweis"] and d["lernen"]["duenn"]
    assert d["lernen"]["saetze"][0]["text"].startswith("Noch zu wenig Daten")
    assert client.get("/wirkung/cockpit?tage=5", headers=AUTH).json()["tage"] == 7       # nur 7/30/90


def test_cockpit_follower_nur_verbundene(monkeypatch, frische_db):
    cockpit.leeren()
    monkeypatch.delenv("AGENT_STATS_TOKEN", raising=False)
    db.setze_einstellung("meta_instagram", {"token": "t", "konto_id": "1"})
    posten.merke_follower(100, HEUTE - timedelta(days=7))
    posten.merke_follower(112, HEUTE)
    posten.merke_follower(50, HEUTE, "tiktok_follower")                  # TikTok nicht verbunden -> ausgeblendet
    d = cockpit.cockpit(7)
    assert d["follower"] == [{"plattform": "instagram", "follower": 112, "zuwachs_7": 12, "am": HEUTE.isoformat()}]
    db.setze_einstellung("meta_facebook", {"token": "t", "seite_id": "5"})
    cockpit.leeren()
    assert [f["plattform"] for f in cockpit.cockpit(7)["follower"]] == ["facebook", "instagram"]
    assert cockpit.cockpit(7)["follower"][0]["follower"] is None          # verbunden, noch nie gemessen


def test_lern_saetze_mehr_weniger_test():
    def e(i, thema, punkte, stil="frage"):
        return {"post": {"id": i, "art": "post", "meta": {"thema": thema, "hook_stil": stil}}, "punkte": punkte, "gemessen": True}
    b = [e(1, "Ritual", 40), e(2, "Ritual", 30), e(3, "Rückblick", 5), e(4, "Rückblick", 7)]
    s = {x["art"]: x["text"] for x in cockpit.lern_saetze(b)["saetze"]}
    assert "„Ritual“" in s["mehr"] and "Ø 35 Punkte" in s["mehr"] and "„Rückblick“" in s["weniger"] and "Ø 6 Punkte" in s["weniger"]
    assert s["test"].startswith("Anfang „") and "bisher 0 von 3" in s["test"]
    nah = [e(1, "Ritual", 10), e(2, "Ritual", 10), e(3, "Mitmachen", 9), e(4, "Mitmachen", 9.5)]
    assert "Nichts fällt deutlich ab" in cockpit.lern_saetze(nah)["saetze"][1]["text"]
    assert cockpit._komma(4.25) == "4,2" or cockpit._komma(4.25) == "4,3"
    alle = [e(i * 10 + k, "Ritual", 5 + i, st) for i, st in enumerate(redaktion.HOOK_NAMEN) for k in range(3)]
    alle += [{"post": {"id": 900 + i, "art": "post", "meta": {"aufforderung": a}}, "punkte": 1, "gemessen": True}
             for i, a in enumerate(list(redaktion.AUFFORDERUNG_NAMEN) * 3)]
    r = cockpit.lern_saetze(alle)
    assert r["saetze"][2]["text"].startswith("Soraya bleibt meist beim Anfang") and r["test_kurz"].startswith("weiter den Anfang")


def test_wochenbericht_ab_montag_bis_weggeklickt(monkeypatch, frische_db):
    cockpit.leeren()
    montag = HEUTE - timedelta(days=HEUTE.weekday())
    _gepostet("Bester der Woche", "reel", montag - timedelta(days=3), {"instagram": {"r": 50, "reach": 1200}})
    _gepostet("Davor", "post", montag - timedelta(days=10), {"instagram": {"r": 5, "reach": 1000}})
    _stat_fake(monkeypatch, lambda i: {"neue_konten": 1})
    w = client.get("/wirkung/wochenbericht", headers=AUTH).json()
    assert w["zeigen"] and w["von"] == (montag - timedelta(days=7)).isoformat() and w["bis"] == (montag - timedelta(days=1)).isoformat()
    assert w["zahlen"].startswith("1.200 erreicht (+20 %)") and "7 neue Konten" in w["zahlen"]
    assert w["bester"]["titel"] == "Bester der Woche" and w["test"]
    assert client.post("/wirkung/wochenbericht/gesehen", json={"woche": "kaputt"}, headers=AUTH).status_code == 400
    assert client.post("/wirkung/wochenbericht/gesehen", json={"woche": w["woche"]}, headers=AUTH).status_code == 200
    assert client.get("/wirkung/wochenbericht", headers=AUTH).json()["zeigen"] is False
    # naechste Woche: neuer Bericht erscheint wieder (auch wenn es nicht Montag ist)
    w2 = cockpit.wochenbericht(heute=montag + timedelta(days=9))
    assert w2["woche"] != w["woche"]
    monkeypatch.delenv("AGENT_STATS_TOKEN", raising=False)                 # ohne Daten: keine Karte
    assert cockpit.wochenbericht(heute=montag + timedelta(days=70))["zeigen"] is False


import auswertung


def _p(i, platz, stunde, erreicht, punkte, tag=None, sprache="en", fmt="Ritual", stil="frage", pl="instagram"):
    tag = tag or HEUTE - timedelta(days=i % 6)
    return {"id": i, "titel": f"Post {i}", "art": "reel" if platz.startswith("reel") else platz, "platz": platz,
            "stunde": stunde, "tag": tag, "erreicht": erreicht, "punkte": punkte, "gemessen": True, "format": fmt,
            "hook_stil": stil, "aufforderung": "partner", "sprache": sprache, "besuche": 0,
            "plattformen": {pl: {"erreicht": erreicht, "reaktionen": punkte}}}


def _auswerten(posts, kpis=None, trichter=None, zeiten=None, verlaeufe=None):
    tage = [HEUTE - timedelta(days=i) for i in range(29, -1, -1)]
    kpis = kpis or [{"schluessel": "erreicht", "wert": 0, "vorher": None, "aenderung": None}]
    tr = trichter or cockpit.trichter({})
    return auswertung.auswerten(posts, tage=tage, quellen={"bio-tt": {"tage": {HEUTE.isoformat(): 7}}}, kpis=kpis,
                                trichter=tr, trichter_vorher=tr, follower_verlaeufe=verlaeufe or {},
                                zeiten=zeiten or {"story": "09:00", "post": "12:30", "reel": "19:00", "reel2": "19:30"})


def test_auswertung_soraya_erkennt():
    posts = ([_p(i, "reel", 9, 900, 30, pl="tiktok") for i in range(4)] + [_p(10 + i, "reel", 19, 300, 10) for i in range(3)]
             + [_p(20 + i, "post", 12, 200, 5, fmt="Rückblick", sprache="de") for i in range(3)])
    a = _auswerten(posts, kpis=[{"schluessel": "erreicht", "wert": 5000, "vorher": 2500, "aenderung": 100},
                                {"schluessel": "besuche", "wert": 40, "vorher": 20, "aenderung": 100}],
                   trichter=cockpit.trichter({"erreicht": 5000, "besuche": 40, "gratis": 2, "konten": 0}),
                   verlaeufe={"instagram": {(HEUTE - timedelta(days=40)).isoformat(): 1, HEUTE.isoformat(): 4}})
    k = {x["id"]: x for x in a["erkennt"]}
    assert len(a["erkennt"]) <= 5 and [x["gewicht"] for x in a["erkennt"]] == sorted((x["gewicht"] for x in a["erkennt"]), reverse=True)
    assert "duenn" not in k
    assert k["arten"]["text"] == "Reels erreichen 3,2× mehr Menschen als Feed-Posts" and k["arten"]["zahl"] == "3,2×"
    # Reels um 9 besser als um 19 -> Vorschlag zum Übernehmen (nur ausfuellen, nie speichern)
    z = k["zeit-reel"]
    assert z["text"] == "Reels um 9 Uhr laufen besser als um 19 Uhr" and z["aktion"]["zeit"] == "09:00" and z["aktion"]["platz"] == "reel"
    assert k["landing"]["text"].startswith("Besuche steigen, aber kaum Gratis-Tests") and k["landing"]["zahl"] == "5 %"
    assert k["trend"]["zahl"] == "+100 %"
    # weitere Bausteine der Unterreiter
    assert a["plattformen"]["zeilen"][-1]["plattform"] == "tiktok" and a["plattformen"]["zeilen"][-1]["besuche"] == 7
    assert [s["name"] for s in a["sprachen"]] == ["Englisch", "Deutsch"]
    zellen = {(c["tag"], c["slot"]): c for c in a["zeiten"]["zellen"]}
    assert sum(c["posts"] for c in zellen.values()) == 10 and a["zeiten"]["eingestellt"][2]["slot"] == 4
    assert a["formate"][0]["name"] == "Ritual" and a["formate"][0]["sicherheit"] == "gut"
    assert a["follower"][0]["zuwachs"] == 3 and a["follower"][0]["punkte"][0]["davor"]
    stile = {s["schluessel"]: s for s in a["stile"]}
    assert stile["frage"]["posts"] == 10 and stile["zahl"]["posts"] == 0 and stile["zahl"]["sicherheit"] == "wenig"
    # eingestellte Zeit liegt schon im besten Fenster -> kein Übernehmen
    b = _auswerten(posts, zeiten={"reel": "09:30", "post": "12:30"})
    assert {x["id"]: x for x in b["erkennt"]}["zeit-reel"]["aktion"] is None
    # Ausreisser
    c = _auswerten([_p(i, "post", 12, 300, 4) for i in range(6)] + [_p(9, "post", 12, 3000, 40, fmt="Mitmachen")])
    aus = {x["id"]: x for x in c["erkennt"]}["ausreisser"]
    assert aus["post_id"] == 9 and "Format Mitmachen" in aus["text"] and aus["zahl"] == "4,4×"


def test_auswertung_wenig_daten_ehrlich():
    a = _auswerten([_p(1, "story", 9, 12, 0), _p(2, "post", 12, 30, 1)])
    assert [x["id"] for x in a["erkennt"]] == ["duenn"] and a["erkennt"][0]["zahl"] == "2"
    assert all(not g["genug"] for g in a["arten"]) and a["zeiten"]["beste"] == []
    leer = _auswerten([])
    assert leer["erkennt"][0]["detail"].startswith("0 gemessene Posts") and leer["arten"] == [] and leer["formate"] == []
