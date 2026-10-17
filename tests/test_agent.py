"""Tests fuer den Soraya-Agent (Stufe 2). Echte Postgres, Claude/Backend als Attrappe."""
import base64
import json
import os
import sys
import time
from datetime import date, timedelta
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
             "ruhig, aber sag es. Speichere dir den Post für den Vollmond in zwei Tagen.")
TAGS = ["#astrologie", "#mondphase", "#horoskop", "#skorpion", "#soraya"]
EN_TEXT = ("Feeling everything a little louder today? The Moon moves through Scorpio and turns small moments into big "
           "ones. A message left on read, one sentence in the group chat – it all lands deeper. That is not drama, it "
           "is honesty. Use the day for the conversation you have been putting off. Say it softly, but say it. Save "
           "this post for the Full Moon in two days.")


def tagesplan_antwort(sprache="de"):
    return {"thema": "Vollmond naht", "posts": [
        {"art": "post", "platform": "instagram", "titel": f"Vollmond {sprache}", "untertitel": "U",
         "text": EN_TEXT if sprache == "en" else FEED_TEXT,
         "hashtags": TAGS, "bild_punkte": ["Skorpion: ehrlich sein", "Stier: langsam", "Krebs: Bauchgefühl"],
         "skript": {"hook": "", "szenen": [], "einblendungen": [], "schluss": ""}},
        {"art": "reel", "platform": "tiktok", "titel": "Reel", "untertitel": "U", "text": "Two nights to go. Can you feel it?" if sprache == "en" else "Caption mit Hook. Zwei Nächte noch.",
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
    assert r["bio"]["instagram"].endswith("?q=bio-ig") and set(r["bio"]) == {"instagram", "tiktok", "facebook"}
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
    # nichts markiert -> das einzige Profil gilt automatisch fuer alle Sprachen
    assert d["im_tagesplan"]["de"]["id"] == zid and d["im_tagesplan"]["de"]["automatisch"] is True
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
            return self._r({"user_id": "1789", "username": "soraya.astro"})
        if "fields" in (params or {}) and params["fields"].startswith("status_code"):
            return self._r({"status_code": "FINISHED"})
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
    assert d["einstellungen"]["zeiten"] == {"story": "09:00", "post": "12:30", "reel": "19:00"}
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
    montag = HEUTE - timedelta(days=HEUTE.weekday())
    namen = [redaktion.wochenthema(montag + timedelta(days=i), info)["name"] for i in range(7)]
    assert namen == ["Deine Woche", "Sternzeichen im Fokus", "Liebe & Beziehung", "Astro-Wissen", "Ritual",
                     "Mitmachen", "Rückblick & Vorschau"]
    assert redaktion.wochenthema(montag + timedelta(days=2), info)["aufforderung"]["schluessel"] == "partner"
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
    assert "„Drei Zeichen fühlen es“ (post, 12 Besuche, 2 neue Konten)" in frage
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
    assert [x["status"] for x in r["ausgefuehrt"]] == ["fertig"]          # nur die Story; Feed-Post wartet
    # Bearbeiten behebt den Befund -> geht automatisch raus
    p = client.patch(f"/content/{feed['id']}", json={"hashtags": "#astrology #moon #scorpio #horoscope"}, headers=AUTH).json()["post"]
    assert p["meta"]["pruefung"] == []
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
                                                         "label": None, "punkte": []}
    basis = {"phase_index": 1, "beleuchtung": 12, "datum_kurz": "15. Oktober", "mond_phase": "Sichel", "mond_zeichen": "Skorpion"}
    for thema, punkte in (("Sternzeichen im Fokus", ["Skorpion: ehrlich", "Stier: langsam", "Krebs: Bauch"]),
                          ("Ritual", ["Kerze", "Wunsch", "Lesen"]), ("Liebe & Beziehung", []), ("Astro-Wissen", []),
                          ("Mitmachen", [])):
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
    assert "Link below" in fb and "bio" not in fb.lower() and "?q=p7" in fb
    assert "Link in bio" in posten.text_fuer(p, "instagram")
    assert "Link unten" in posten.text_fuer({**p, "sprache": "de", "text": "Dein Horoskop: Link in Bio"}, "facebook")


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
