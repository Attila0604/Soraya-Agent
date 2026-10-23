"""Startet den Agenten lokal mit Attrappen (kein Claude, kein Railway)."""
import os, sys, time, random
from datetime import datetime, timedelta
from types import SimpleNamespace
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://agent@127.0.0.1:55432/agenttest")
os.environ.setdefault("AGENT_PASSWORT", "geheim-test")
os.environ.setdefault("TAGESPLAN_AUTO", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
sys.path.insert(0, os.environ.get("AGENT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import psycopg
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    c.execute("drop table if exists soraya_veroeffentlichungen, soraya_medien, soraya_posts, soraya_zielgruppen, soraya_tagesplaene, soraya_einstellungen cascade;")
import himmel, tagesplan, content_agent, research_agent, wirkung, main, uvicorn
H = himmel.heute()
SKY = {"moon": {"phase_index": int(os.environ.get("PHASE", "1")), "illumination": 12, "sign": "Sco"}, "sun": {"sign": "Lib"},
       "retrograde": [{"planet": "Venus", "key": "Venus", "until": (H + timedelta(days=33)).isoformat()}],
       "retrograde_soon": [], "next_new_moon": (H + timedelta(days=27)).isoformat() + "T07:02+00:00",
       "next_full_moon": (H + timedelta(days=2)).isoformat() + "T04:11+00:00"}
himmel.hole_himmel = lambda tag=None: SKY
TXT = {"de": ("Der Mond sammelt Kraft", "Zwei Tage bis zum Vollmond im Widder", "Der Mond wächst durch den Skorpion und macht Gefühle tiefer als sonst. Nimm dir heute Zeit für ein ehrliches Gespräch.\n\nDein persönliches Horoskop: Link in Bio ✨"),
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
        {"art": "story", "platform": "instagram", "titel": "Wie fühlst du dich?", "untertitel": "Vollmond in 2 Tagen", "text": "Umfrage: Schläfst du vor dem Vollmond schlechter? Ja / Nein", "hashtags": ["#mond"], "skript": {"hook": "", "szenen": [], "schluss": ""}},
        {"art": "reel", "platform": "tiktok", "titel": "Drei Zeichen spüren es", "untertitel": u, "text": "Skorpion, Krebs, Fische: heute zuerst.", "hashtags": ["#astrotok", "#sternzeichen"],
         "skript": {"hook": "Drei Zeichen spüren es zuerst", "szenen": ["Mond", "Kerze"],
                    "einblendungen": ["Skorpion: sagt es endlich laut", "Fische: darf heute ruhen"], "schluss": "Welches bist du?"}}]}
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
# Instagram (DEMO_KANAELE=1): Follower und Zahlen je Beitrag
def fake_instagram(url, params):
    if url.endswith("/me"):
        return {"username": "soraya.astroguide", "followers_count": 1243, "media_count": 58}
    mid = url.split("/")[-2] if url.endswith("/insights") else url.rsplit("/", 1)[-1]
    n = int("".join(ch for ch in mid if ch.isdigit()) or 1)
    if url.endswith("/insights"):
        werte = {"reach": 420 * n, "views": 610 * n, "saved": 6 * n, "shares": 2 * n, "likes": 18 * n, "comments": 3 * n, "replies": 1}
        return {"data": [{"name": k, "values": [{"value": werte[k]}]} for k in params["metric"].split(",")]}
    return {"like_count": 18 * n, "comments_count": 3 * n}
def router_get(url, params=None, headers=None, timeout=None):
    if "graph.instagram.com" in url:
        d = fake_instagram(url, params or {})
        return SimpleNamespace(status_code=200, json=lambda: d, text="")
    return fake_get(url, params=params, headers=headers, timeout=timeout)
wirkung.requests.get = router_get
os.environ.setdefault("AGENT_STATS_TOKEN", "x" * 32)
import db
db.init_db()
if os.environ.get("DEMO_KANAELE"):
    import meta, posten
    for k in ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
              "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        os.environ[k] = "demo"
    jetzt = int(time.time())
    db.setze_einstellung("meta_instagram", {"konto_id": "1789", "name": "soraya.astroguide", "token": "demo", "verbunden": jetzt,
                                            "laeuft_ab": jetzt + 50 * 86400, "angefragt": meta.IG_SCOPES})
    db.setze_einstellung("tiktok_zugang", {"token": "demo", "laeuft_ab": jetzt + 86400, "refresh": "r", "refresh_ab": jetzt + 300 * 86400,
                                           "name": "soraya.astroguide", "rechte": ["user.info.basic", "video.upload", "video.publish"]})
    db.setze_einstellung("linkedin_zugang", {"token": "demo", "laeuft_ab": jetzt + 5 * 86400, "autor": "urn:li:person:x", "name": "Attila Kovacs"})
    posten.speichere_einstellungen({"plattformen": {"facebook": False, "linkedin": True, "tiktok": True}})
    posten.merke_follower(1180, H - timedelta(days=8))
    tagesplan.erstelle("en")
    for i, p in enumerate(db.lade_posts(von=H, bis=H)):
        if p["sprache"] != "en":
            continue
        zid = db.plane_veroeffentlichung(p["id"], "instagram", datetime.now(himmel.WIEN), zurueckgeben=True)
        db.setze_veroeffentlichung(zid, "fertig", extern_id=f"IG{i + 1}", url="https://www.instagram.com/p/demo/")
for bereich, land, wer in (("Liebe & Beziehung", "at", "Frauen 28-45 in Österreich, oft nach einer Trennung, suchen Halt und Klarheit."),
                           ("Szerelem és kapcsolat", "hu", "Magyar nők 25-40, akik a párkapcsolatukban keresnek irányt.")):
    db.speichere_zielgruppe(bereich, {"wer_sind_sie": wer, "beschaeftigt_sie": ["Trennung", "Neuanfang"], "wuensche": ["Klarheit"],
                                      "sprache": ["Bauchgefühl", "Energie"], "content_ideen": ["Mond-Rituale"], "worauf_achten": ["keine Angst machen"],
                                      "_quellen": ["websuche"]}, land=land)
uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ.get("PORT", "8790")), log_level="warning")
