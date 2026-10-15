"""Startet den Agenten lokal mit Attrappen (kein Claude, kein Railway)."""
import os, sys, time, random
from datetime import timedelta
from types import SimpleNamespace
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://agent@127.0.0.1:55432/agenttest")
os.environ.setdefault("AGENT_PASSWORT", "geheim-test")
os.environ.setdefault("TAGESPLAN_AUTO", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
sys.path.insert(0, os.environ.get("AGENT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    c.execute("drop table if exists soraya_medien, soraya_posts, soraya_zielgruppen, soraya_tagesplaene, soraya_einstellungen cascade;")
import himmel, tagesplan, content_agent, research_agent, wirkung, main, uvicorn
H = himmel.heute()
SKY = {"moon": {"phase_index": int(os.environ.get("PHASE", "1")), "illumination": 12, "sign": "Sco"}, "sun": {"sign": "Lib"},
       "retrograde": [{"planet": "Venus", "key": "Venus", "until": (H + timedelta(days=33)).isoformat()}],
       "retrograde_soon": [], "next_new_moon": (H + timedelta(days=27)).isoformat() + "T07:02+00:00",
       "next_full_moon": (H + timedelta(days=2)).isoformat() + "T04:11+00:00"}
himmel.hole_himmel = lambda tag=None: SKY
TXT = {"de": ("Der Mond sammelt Kraft", "Zwei Tage bis zum Vollmond im Widder", "Der Mond wächst durch den Skorpion und macht Gefühle tiefer als sonst. Nimm dir heute Zeit für ein ehrliches Gespräch – zwei Tage vor dem Vollmond zeigt sich, was wirklich zählt.\n\nDein persönliches Horoskop: Link in Bio ✨"),
       "en": ("The Moon gathers strength", "Two days until the Full Moon", "The waxing Moon in Scorpio deepens every feeling. Make time for an honest talk today.\n\nYour personal horoscope: link in bio ✨"),
       "hu": ("A Hold erőt gyűjt", "Két nap a teliholdig", "A növő Hold a Skorpióban mindent elmélyít. Szánj ma időt egy őszinte beszélgetésre.\n\nA személyes horoszkópod: link a bióban ✨"),
       "it": ("La Luna raccoglie forza", "Due giorni alla Luna piena", "La Luna crescente in Scorpione rende tutto più profondo. Oggi concediti una conversazione sincera.\n\nIl tuo oroscopo personale: link in bio ✨")}
IT_FEHLER = [1]  # erster Lauf fuer IT schlaegt fehl (zeigt Fehlerkasten + "Nochmal versuchen")
AUFRUFE = [0]
def fake_plan(system, frage, schema, **kw):
    AUFRUFE[0] += 1
    time.sleep(1.2 if AUFRUFE[0] <= 5 else 0.12)  # Vorplanen im Test schneller
    lang = next((l for l, w in (("en", "English"), ("hu", "magyar"), ("it", "italiano")) if w in frage), "de")
    if lang == "it" and IT_FEHLER and not os.environ.get("OHNE_FEHLER"):
        IT_FEHLER.pop()
        raise RuntimeError("Der Anthropic-Schlüssel (ANTHROPIC_API_KEY) ist ungültig.")
    t, u, x = TXT[lang]
    return {"thema": t, "posts": [
        {"art": "post", "platform": "instagram", "titel": t, "untertitel": u, "text": x, "hashtags": ["#vollmond", "#skorpion", "#horoskop", "#soraya"],
         "bild_punkte": ["Skorpion: ehrlich sein", "Stier: langsam", "Krebs: Bauchgefühl"] if lang == "de" else [], "skript": {"hook": "", "szenen": [], "schluss": ""}},
        {"art": "reel", "platform": "tiktok", "titel": "Noch 2 Nächte", "untertitel": u, "text": "Zwei Nächte bis zum Vollmond.", "hashtags": ["#astrotok", "#vollmond"],
         "skript": {"hook": "Spürst du es auch?", "szenen": ["Mond über der Stadt", "Text: Mond im Skorpion", "Tagebuch, Kerze"],
                    "einblendungen": ["Der Mond wächst durch den Skorpion", "Gefühle werden tiefer als sonst", "Nimm dir Zeit für ein ehrliches Gespräch"],
                    "schluss": "Dein Horoskop: Link in Bio"}},
        {"art": "story", "platform": "instagram", "titel": "Wie fühlst du dich?", "untertitel": "Vollmond in 2 Tagen", "text": "Umfrage: Schläfst du vor dem Vollmond schlechter? Ja / Nein", "hashtags": ["#mond"], "skript": {"hook": "", "szenen": [], "schluss": ""}}]}
tagesplan.frage_json = fake_plan
content_agent.frage_json = lambda s, f, sc, **k: {"posts": [{"platform": "instagram", "titel": "Venus rückläufig", "untertitel": "Alte Gefühle klopfen an", "text": "Studio-Post zum Thema.", "hashtags": ["#venus", "#astrologie"]}] * 3}
random.seed(4)
def fake_get(url, params=None, headers=None, timeout=None):
    if os.environ.get("OHNE_STATS"):
        return SimpleNamespace(status_code=503, json=dict, text="")
    tage = []
    for i in range(int(params["tage"])):
        d = H - timedelta(days=int(params["tage"]) - 1 - i)
        a = random.randint(0, 9)
        tage.append({"datum": d.isoformat(), "schnellstart_geoeffnet": a + 3, "schnellstart_berechnet": a, "registrieren_geklickt": a // 3,
                     "neue_konten": a // 4, "neue_profile": a // 5, "aktive_nutzer": random.randint(1, 6), "app_starts": random.randint(2, 14),
                     "horoskope": random.randint(0, 5), "analysen": 0, "partner_vergleiche": random.randint(0, 2), "chat_nachrichten": random.randint(0, 4),
                     "einladungen_geteilt": random.randint(0, 1), "einladung_geoeffnet": random.randint(0, 2), "einladung_berechnet": 0, "fehler": 0})
    data = {"von": tage[0]["datum"], "bis": tage[-1]["datum"], "ignoriert": 2, "tage": tage, "aktive_nutzer_zeitraum": 9,
            "sprachen": {"de": 5, "hu": 3, "en": 1},
            "quellen": {"p1": {"schritte": {"besuch": 34, "schnellstart": 9, "register_click": 3}, "konten": 2,
                               "tage": {H.isoformat(): 20, (H - timedelta(days=1)).isoformat(): 14}},
                        "bio-ig": {"schritte": {"besuch": 51, "store_klick": 12}, "konten": 1,
                                   "tage": {(H - timedelta(days=2)).isoformat(): 51}}}, "gesamt": {"konten": 11, "profile": 8, "einladungslinks": 3, "einladungs_nutzungen": 4}}
    return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "data": data}, text="")
wirkung.requests.get = fake_get
os.environ.setdefault("AGENT_STATS_TOKEN", "x" * 32)
import db
db.init_db()
for bereich, land, wer in (("Liebe & Beziehung", "at", "Frauen 28-45 in Österreich, oft nach einer Trennung, suchen Halt und Klarheit."),
                           ("Szerelem és kapcsolat", "hu", "Magyar nők 25-40, akik a párkapcsolatukban keresnek irányt.")):
    db.speichere_zielgruppe(bereich, {"wer_sind_sie": wer, "beschaeftigt_sie": ["Trennung", "Neuanfang"], "wuensche": ["Klarheit"],
                                      "sprache": ["Bauchgefühl", "Energie"], "content_ideen": ["Mond-Rituale"], "worauf_achten": ["keine Angst machen"],
                                      "_quellen": ["websuche"]}, land=land)
uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8790")), log_level="warning")
