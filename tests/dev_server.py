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
        a = random.randint(0, 1) if WENIG else random.randint(0, 9)
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
    grenze = H - timedelta(days=int(params["tage"]) - 1)
    for code, q in DEMO_QUELLEN.items():
        t = {d: n for d, n in q["tage"].items() if d >= grenze.isoformat()}
        if t:
            data["quellen"][code] = {**q, "tage": t, "schritte": {**q["schritte"], "besuch": sum(t.values())}}
    return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "data": data}, text="")
WENIG = bool(os.environ.get("DEMO_WENIG"))   # mit DEMO_KANAELE=1: wenige Posts, kleine Zahlen (wie beim Start)
DEMO_QUELLEN = {}   # p<id> -> Besuche je Tag (DEMO_KANAELE=1: Posts der letzten 30 Tage)
def wert(n, lo, hi):
    """Feste, plausible Zufallszahl je Beitrag (gleich bei jedem Abruf)."""
    return lo + (n * 7919 + 13) % (hi - lo + 1)
# Instagram (DEMO_KANAELE=1): Follower und Zahlen je Beitrag
def fake_instagram(url, params):
    if url.endswith("/me"):
        return {"username": "soraya.astroguide", "followers_count": 1243, "media_count": 58}
    mid = url.split("/")[-2] if url.endswith("/insights") else url.rsplit("/", 1)[-1]
    n = int("".join(ch for ch in mid if ch.isdigit()) or 1)
    if url.endswith("/insights"):
        r = wert(n, 180, 1400)
        werte = {"reach": r, "views": r * 3 // 2, "saved": wert(n, 1, 24), "shares": wert(n, 0, 9), "likes": wert(n, 8, 70),
                 "comments": wert(n, 0, 12), "replies": 1}
        return {"data": [{"name": k, "values": [{"value": werte[k]}]} for k in params["metric"].split(",")]}
    return {"like_count": wert(n, 8, 70), "comments_count": wert(n, 0, 12)}
# Facebook-Seite (DEMO_KANAELE=1): Follower, Reaktionen, Reichweite
def fake_facebook(url, params):
    if params.get("fields") == "followers_count,fan_count":
        return {"followers_count": 412, "fan_count": 398}
    mid = url.split("/")[-2] if url.endswith("/insights") else url.rsplit("/", 1)[-1]
    n = int("".join(ch for ch in mid if ch.isdigit()) or 1)
    if url.endswith("/insights"):
        return {"data": [{"name": params.get("metric"), "values": [{"value": wert(n, 60, 520)}]}]}
    return {"reactions": {"summary": {"total_count": wert(n, 2, 30)}}, "comments": {"summary": {"total_count": wert(n, 0, 6)}},
            "shares": {"count": wert(n, 0, 4)}}
def router_get(url, params=None, headers=None, timeout=None):
    if "graph.facebook.com" in url:
        d = fake_facebook(url, params or {})
        return SimpleNamespace(status_code=200, json=lambda: d, text="")
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
              "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "META_APP_ID", "META_APP_SECRET"):
        os.environ[k] = "demo"
    jetzt = int(time.time())
    db.setze_einstellung("meta_instagram", {"konto_id": "1789", "name": "soraya.astroguide", "token": "demo", "verbunden": jetzt,
                                            "laeuft_ab": jetzt + 50 * 86400, "angefragt": meta.IG_SCOPES})
    db.setze_einstellung("tiktok_zugang", {"token": "demo", "laeuft_ab": jetzt + 86400, "refresh": "r", "refresh_ab": jetzt + 300 * 86400,
                                           "name": "soraya.astroguide", "rechte": ["user.info.basic", "video.upload", "video.publish"]})
    db.setze_einstellung("linkedin_zugang", {"token": "demo", "laeuft_ab": jetzt + 5 * 86400, "autor": "urn:li:person:x", "name": "Attila Kovacs"})
    posten.speichere_einstellungen({"plattformen": {"facebook": False, "linkedin": True, "tiktok": True}})
    db.setze_einstellung("meta_facebook", {"seite_id": "555", "name": "Soraya Luxury Astrology", "token": "demo", "verbunden": jetzt})
    # Follower-Verlauf (Instagram: der Wert von vor 8 Tagen bleibt der Vergleich fuer "+63 in 7 Tagen")
    if WENIG:
        for i, n in ((20, 1), (12, 2), (6, 3), (1, 4)):
            posten.merke_follower(n, H - timedelta(days=i))
        for i, n in ((15, 1), (3, 2)):
            posten.merke_follower(n, H - timedelta(days=i), "facebook_follower")
        posten.merke_follower(1, H - timedelta(days=2), "tiktok_follower")
    else:
        for i in range(30, 7, -1):
            posten.merke_follower(1180 - (i - 8) * 4, H - timedelta(days=i))
        for i in range(30, 0, -1):
            posten.merke_follower(412 - i * 2 + (i % 3), H - timedelta(days=i), "facebook_follower")
            posten.merke_follower(318 - i * 3, H - timedelta(days=i), "tiktok_follower")
        posten.merke_follower(318, H, "tiktok_follower")
    # Posts der letzten 30 Tage auf Facebook, Instagram und TikTok mit gemerkten Zahlen
    FORMATE = ["Deine Woche", "Mitmachen", "Ritual", "Astro-Wissen", "Ritual", "Mitmachen", "Rückblick"]
    STILE, AUFF = ["frage", "szene", "geheimnis", "zeichen", "aussage", "zahl"], ["mondzeichen", "partner", "horoskop", "chat"]
    TITEL = {"post": ["Dein Mondzeichen verrät mehr", "3 Zeichen, die heute loslassen", "Das Herz-Ritual zum Neumond", "Warum Venus rückwärts geht",
                      "Welches Zeichen bist du?", "Deine Woche in den Sternen", "Was der Vollmond zeigt", "Skorpion-Saison beginnt"],
             "reel": ["Noch 2 Nächte bis Vollmond", "Drei Zeichen spüren es zuerst", "Das sagt dein Aszendent", "Fische: heute ruhen",
                      "Ein Satz für deine Woche", "Wenn der Mond im Krebs steht"],
             "story": ["Wie schläfst du gerade?", "A, B oder C?", "Dein Gefühl heute"]}
    con = psycopg.connect(os.environ["DATABASE_URL"])
    klein = (lambda v: v // 8) if WENIG else (lambda v: v)
    k = 0
    for tag in range(29, 0, -1):
        d = H - timedelta(days=tag)
        arten = ["post", "reel", "story"] if tag % 2 else ["post", "reel"]
        if WENIG:
            arten = {9: ["post"], 6: ["reel"], 4: ["story"], 2: ["post"]}.get(tag, [])
        for art in arten:
            k += 1
            fm = FORMATE[d.weekday()]
            stil = STILE[k % (len(STILE) if tag > 12 else 3)]
            p = db.speichere_posts([{"art": art, "titel": TITEL[art][k % len(TITEL[art])], "sprache": "en" if k % 3 else "de",
                                     "text": "Demo-Post.", "hashtags": ["#astro"]}], quelle="tagesplan", geplant_fuer=d,
                                   meta={"thema": fm, "hook_stil": stil, "aufforderung": AUFF[k % 4]})[0]
            db.aendere_post(p["id"], {"status": "gepostet"})
            wo = {"post": ["facebook", "instagram"], "reel": ["instagram", "tiktok", "facebook"], "story": ["instagram"]}[art]
            stunde = {"post": (12, 12, 9, 18)[k % 4], "reel": (19, 19, 9)[k % 3], "story": 9}[art]
            # Rituale und Reels kommen besser an, Rueckblick schwaecher -> "Soraya lernt" hat etwas zu sagen;
            # Reels am Morgen laufen besser als am Abend -> "Soraya erkennt" schlaegt eine Uhrzeit vor
            faktor = (1.8 if fm == "Ritual" else 0.5 if fm == "Rückblick" else 1.0) * (1.5 if art == "reel" else 1)
            faktor *= 1.6 if art == "reel" and stunde == 9 else 1
            if WENIG:
                faktor = 0.08
            for pl in wo:
                zid = db.plane_veroeffentlichung(p["id"], pl, datetime.combine(d, datetime.min.time()).replace(hour=stunde, tzinfo=himmel.WIEN), zurueckgeben=True)
                n = 100 + k * 10 + len(pl)
                ext = {"facebook": f"FB{n}", "instagram": f"IG{n}", "tiktok": f"TT{n}"}[pl]
                db.setze_veroeffentlichung(zid, "fertig", extern_id=ext, url=f"https://example.com/{ext}")
                r = int(wert(n, 150, 1300) * faktor)
                if pl == "facebook":
                    db.speichere_zahlen(p["id"], pl, int(wert(n, 2, 30) * faktor), klein(wert(n, 0, 6)), klein(wert(n, 0, 4)), reichweite=klein(wert(n, 60, 520)))
                elif pl == "instagram":
                    db.speichere_zahlen(p["id"], pl, int(wert(n, 8, 70) * faktor), klein(wert(n, 0, 12)), klein(wert(n, 0, 9)), reichweite=r,
                                        gespeichert=int(wert(n, 1, 24) * faktor), aufrufe=r * 3 // 2)
                else:
                    db.speichere_zahlen(p["id"], pl, int(wert(n, 20, 160) * faktor), klein(wert(n, 0, 15)), klein(wert(n, 0, 10)), aufrufe=int(wert(n, 300, 2600) * faktor))
                um = datetime.combine(d, datetime.min.time()).replace(hour=stunde, minute=k % 50, tzinfo=himmel.WIEN)
                con.execute("update soraya_veroeffentlichungen set aktualisiert = %s, geplant_um = %s where id = %s", (um, um, zid))
            if art != "story" and not WENIG:
                DEMO_QUELLEN[f"p{p['id']}"] = {"schritte": {"schnellstart": int(faktor * 2), "register_click": 1},
                                              "konten": 1 if faktor > 1.5 and k % 2 else 0,
                                              "tage": {d.isoformat(): int(wert(k, 1, 9) * faktor), (d + timedelta(days=1)).isoformat(): wert(k, 0, 4)}}
    con.commit(); con.close()
    if WENIG:
        # ein selbst gemachtes TikTok-Video ohne Soraya-Post (zaehlt bei TikTok mit)
        eigen = datetime.combine(H - timedelta(days=3), datetime.min.time()).replace(hour=18, tzinfo=himmel.WIEN)
        posten.merke_tiktok_videos([{"id": "eigen1", "title": "Mein Abend-Ritual", "create_time": int(eigen.timestamp()),
                                     "view_count": 85, "like_count": 6, "comment_count": 1, "share_count": 0}], {})
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
