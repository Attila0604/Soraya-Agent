"""
Zahlen-Cockpit fuer den Reiter „Wirkung“: alles in einem Aufruf, serverseitig zusammengerechnet.

Quellen (nur gemerkte Werte, keine Plattform-API-Aufrufe -- darum schnell):
- App-Statistik der astro-engine (wirkung.hole_statistik): Besuche ueber die Links (?q=), Gratis-Tests, neue Konten
- Zahlen je Beitrag und Plattform (db.lade_cockpit_zeilen, gemerkt von posten.aktualisiere_zahlen)
- Follower-Verlauf (posten.follower_stand) und das Lernen (redaktion.bewerte / erkenntnisse)

Begriffe:
- Erreicht  = Reichweite eines Beitrags (Menschen), wenn die Plattform sie liefert, sonst Aufrufe.
              Gezaehlt fuer die Beitraege, die im Zeitraum gepostet wurden (summiert ueber die Plattformen).
- Reaktionen = Gefaellt mir + Kommentare + Gespeichert + Geteilt (dieselben Beitraege).
- Besuche   = Besuche ueber deine Post- und Bio-Links (Landingpage und App) im Zeitraum.
- Gratis-Test = Sonne/Mond-Schnellstart berechnet (App und Landingpage).
"""

import re
import threading
import time
from datetime import date, datetime, time as uhrzeit, timedelta

import auswertung
import db
import himmel
import meta
import posten
import redaktion
import tiktok
from wirkung import hole_statistik

PLATTFORMEN = ("facebook", "instagram", "tiktok")
FOLLOWER_SCHLUESSEL = {"facebook": "facebook_follower", "instagram": "instagram_follower", "tiktok": "tiktok_follower"}
CACHE_S = 300
_CACHE: dict = {}
_SPERRE = threading.Lock()
ART_NAME = {"post": "Feed-Post", "reel": "Reel", "story": "Story"}


# ---------------------------------------------------------------------------
# kleine Helfer
# ---------------------------------------------------------------------------
def erreicht(z: dict) -> int:
    """Reichweite, sonst Aufrufe (0, wenn nichts gemessen)."""
    if z.get("reichweite") is not None:
        return int(z["reichweite"])
    return int(z.get("aufrufe") or 0)


def reaktionen(z: dict) -> int:
    return sum(int(z.get(k) or 0) for k in ("reaktionen", "kommentare", "gespeichert", "geteilt"))


def aenderung(jetzt, vorher) -> int | None:
    """Veraenderung in Prozent; None = keine Vergleichsdaten (neutral anzeigen)."""
    if jetzt is None or not vorher:
        return None
    return round((jetzt - vorher) / vorher * 100)


def _tag(ts) -> date | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return (ts.astimezone(himmel.WIEN) if ts.tzinfo else ts).date()
    return ts


def _bereich(von: date, bis: date) -> list[date]:
    return [von + timedelta(days=i) for i in range((bis - von).days + 1)]


def tageswerte(statistik: dict | None) -> dict:
    """{iso-datum: {"besuche", "gratis", "konten"}} aus der App-Statistik.
    Besuche: eigener Tageswert der Engine ("besuche"), sonst die Summe der Besuche ueber alle Link-Kennungen."""
    out: dict = {}
    if not statistik:
        return out
    link = {}
    for q in (statistik.get("quellen") or {}).values():
        for d, n in (q.get("tage") or {}).items():
            link[str(d)[:10]] = link.get(str(d)[:10], 0) + int(n or 0)
    for t in statistik.get("tage") or []:
        d = str(t.get("datum") or "")[:10]
        if not d:
            continue
        besuche = t.get("besuche")
        out[d] = {"besuche": int(besuche) if besuche is not None else link.get(d, 0),
                  "gratis": max(int(t.get("schnellstart_berechnet") or 0), int(t.get("gratis_tests") or 0)),
                  "konten": int(t.get("neue_konten") or 0)}
    for d, n in link.items():          # Link-Besuche an Tagen, die die Engine (noch) nicht liefert
        out.setdefault(d, {"besuche": n, "gratis": 0, "konten": 0})
    return out


def _summe(werte: dict, tage: list[date], k: str) -> int:
    return sum(werte.get(d.isoformat(), {}).get(k, 0) for d in tage)


# ---------------------------------------------------------------------------
# Beitraege: eine Zeile je Post, Spalten je Plattform
# ---------------------------------------------------------------------------
def _gemessen(z: dict) -> bool:
    """Zahlen geholt -- bei Storys nur, wenn es Reichweite/Aufrufe gab (eine abgelaufene Story ohne Insights ist
    nicht "0", sondern nie gemessen; wie db.lade_lern_posts)."""
    if z.get("zahlen_am") is None:
        return False
    return (z.get("art") or "post") != "story" or z.get("reichweite") is not None or z.get("aufrufe") is not None


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def punkte_teile(p: dict) -> list[dict]:
    """Woraus sich die Punkte eines Posts zusammensetzen (fuer die Post-Details), nur Teile > 0."""
    teile = [("Neue Konten", p.get("konten", 0), 15), ("Besuche über den Link", p.get("besuche", 0), 2),
             ("Geteilt", p.get("geteilt", 0), 4), ("Kommentare", p.get("kommentare", 0), 3),
             ("Gespeichert", p.get("gespeichert", 0), 3), ("Gefällt mir", p.get("reaktionen", 0), 1)]
    out = [{"name": n, "anzahl": int(a or 0), "punkte": int(a or 0) * f} for n, a, f in teile if a]
    if (p.get("reichweite") or 0) >= 100:
        out.append({"name": "Erreicht (je 100 = 1)", "anzahl": int(p["reichweite"]), "punkte": int(p["reichweite"]) // 100})
    return out


def beitraege(zeilen: list[dict], quellen: dict | None = None) -> list[dict]:
    posts: dict = {}
    for z in zeilen:
        pid = z["post_id"]
        m = z.get("meta") or {}
        p = posts.setdefault(pid, {
            "id": pid, "titel": z.get("titel"), "art": z.get("art") or "post", "sprache": z.get("sprache"),
            "reel_nr": m.get("reel_nr"), "format": m.get("thema"), "hook_stil": m.get("hook_stil"),
            "aufforderung": m.get("aufforderung"), "folge": m.get("folge"),
            "stand": z["post_stand"].isoformat() if hasattr(z.get("post_stand"), "isoformat") else z.get("post_stand"),
            "gepostet": z.get("gepostet"), "geplant": z.get("geplant_um"), "plattformen": {},
            "reaktionen": 0, "kommentare": 0, "geteilt": 0, "gespeichert": 0, "reichweite": 0,
            "erreicht": 0, "reaktionen_summe": 0, "gemessen": False, "zahlen_am": None})
        if z.get("gepostet") and (p["gepostet"] is None or z["gepostet"] < p["gepostet"]):
            p["gepostet"] = z["gepostet"]
        if z.get("geplant_um") and (p["geplant"] is None or z["geplant_um"] < p["geplant"]):
            p["geplant"] = z["geplant_um"]
        gemessen = _gemessen(z)
        p["plattformen"][z["plattform"]] = {
            "erreicht": erreicht(z) if gemessen else None, "reaktionen": reaktionen(z) if gemessen else None,
            "url": z.get("url"), "gepostet": _iso(z.get("gepostet")), "zahlen_am": _iso(z.get("zahlen_am")),
            **{k: (int(z[k]) if z.get(k) is not None else None) for k in
               ("reichweite", "aufrufe", "kommentare", "gespeichert", "geteilt")},
            "gefaellt": int(z["reaktionen"]) if z.get("reaktionen") is not None else None}
        for k in ("reaktionen", "kommentare", "geteilt", "gespeichert", "reichweite"):
            p[k] += int(z.get(k) or 0)
        p["erreicht"] += erreicht(z)
        p["reaktionen_summe"] += reaktionen(z)
        if gemessen:
            p["gemessen"] = True
        if z.get("zahlen_am") is not None:
            p["zahlen_am"] = max(p["zahlen_am"], z["zahlen_am"]) if p["zahlen_am"] else z["zahlen_am"]
    out = []
    for p in posts.values():
        q = (quellen or {}).get(f"p{p['id']}") or {}
        p["besuche"] = int((q.get("schritte") or {}).get("besuch") or 0)
        p["konten"] = int(q.get("konten") or 0)
        p["besuche_tage"] = {str(d)[:10]: int(n or 0) for d, n in sorted((q.get("tage") or {}).items())}
        if p["besuche"] or p["konten"]:
            p["gemessen"] = True                     # Besuche ueber den Post-Link sind eine Messung
        p["punkte"] = redaktion.punkte(p["besuche"], p["konten"], p["reaktionen"], p["kommentare"], p["geteilt"],
                                       p["reichweite"], p["gespeichert"])
        p["punkte_teile"] = punkte_teile(p)
        p["tag"] = _tag(p["gepostet"])
        p["platz"] = "reel2" if p["art"] == "reel" and p["reel_nr"] == 2 else p["art"]
        g = p["gepostet"]
        lokal = g.astimezone(himmel.WIEN) if isinstance(g, datetime) and g.tzinfo else g
        p["stunde"] = lokal.hour if isinstance(lokal, datetime) else None
        p["uhrzeit"] = lokal.strftime("%H:%M") if isinstance(lokal, datetime) else None
        out.append(p)
    return sorted(out, key=lambda p: p["gepostet"] or datetime.min.replace(tzinfo=himmel.WIEN), reverse=True)


# ---------------------------------------------------------------------------
# Trichter und Lernen
# ---------------------------------------------------------------------------
TRICHTER_TIPP = {
    "besuche": "Viele sehen die Posts, aber wenige klicken. Nenne den Link früher und konkret – z. B. „Dein Mondzeichen gratis: Link in Bio“.",
    "gratis": "Besucher probieren den Gratis-Test selten. Der Test sollte auf der Landingpage ganz oben und mit einem Klick erreichbar sein.",
    "konten": "Nach dem Gratis-Test legen wenige ein Konto an. Zeig direkt nach dem Ergebnis, was ein Konto zusätzlich bringt.",
}


def trichter(werte: dict) -> dict:
    stufen = [("erreicht", "Erreicht"), ("besuche", "Besuche"), ("gratis", "Gratis-Test"), ("konten", "Konto")]
    out = [{"schluessel": k, "name": n, "wert": werte.get(k)} for k, n in stufen]
    schwach = None
    for vor, s in zip(out, out[1:]):
        if vor["wert"] and s["wert"] is not None:
            s["quote"] = round(s["wert"] / vor["wert"] * 100, 1)
            if s["quote"] <= 100 and (schwach is None or s["quote"] < schwach["quote"]):
                schwach = s
        else:
            s["quote"] = None
    genug = sum(1 for s in out if s["wert"]) >= 2
    if schwach and genug:
        schwach["schwach"] = True
    return {"stufen": out, "schwach": schwach["schluessel"] if schwach and genug else None,
            "hinweis": TRICHTER_TIPP.get(schwach["schluessel"]) if schwach and genug
            else "Noch zu wenig Daten für den Weg vom Post zum Konto."}


def _komma(x: float) -> str:
    """Punkte deutsch: ab 10 ganze Zahl, darunter eine Nachkommastelle mit Komma."""
    return str(round(x)) if x >= 10 or float(x).is_integer() else f"{x:.1f}".replace(".", ",")


def _name(kategorie: str, name: str) -> str:
    if kategorie == "arten":
        return ART_NAME.get(name, name) + "s"
    if kategorie == "formate":
        return f"das Format „{name}“"
    if kategorie == "stile":
        return f"der Anfang „{name}“"
    return f"die Einladung „{name}“"


def lern_saetze(bewertet: list[dict], min_gemessen: int = 4) -> dict:
    """Drei Saetze fuer „Soraya lernt“: Mehr davon / Weniger davon / Naechster Test."""
    gemessen = redaktion.gemessen(bewertet)
    erk = redaktion.erkenntnisse(bewertet)
    duenn = "Noch zu wenig Daten – nach ein paar gemessenen Posts mehr steht hier, was ankommt."
    mehr = weniger = None
    if len(gemessen) >= min_gemessen:
        for kat in ("formate", "arten", "stile", "aufforderungen"):
            g = erk.get(kat) or []
            if len(g) >= 2:
                beste, schwach = g[0], g[-1]
                mehr = (f"{_name(kat, beste['name'])[0].upper()}{_name(kat, beste['name'])[1:]} kommt am besten an "
                        f"(Ø {_komma(beste['schnitt'])} Punkte aus {beste['posts']} Posts).")
                if schwach["schnitt"] < beste["schnitt"] * 0.7:
                    weniger = (f"{_name(kat, schwach['name'])[0].upper()}{_name(kat, schwach['name'])[1:]} bleibt "
                               f"zurück (Ø {_komma(schwach['schnitt'])} Punkte).")
                else:
                    weniger = "Nichts fällt deutlich ab – die Formate liegen nah beieinander."
                break
    # Naechster Test: der Anfang (Hook-Stil) mit den wenigsten Messungen, sonst die Einladung
    test = kurz = None
    for schluessel, namen in (("hook_stil", redaktion.HOOK_NAMEN), ("aufforderung", redaktion.AUFFORDERUNG_NAMEN)):
        zaehl = {k: 0 for k in namen}
        for e in gemessen:
            k = (e["post"].get("meta") or {}).get(schluessel)
            if k in zaehl:
                zaehl[k] += 1
        offen = sorted((n, k) for k, n in zaehl.items() if n < 3)
        if offen:
            n, k = offen[0]
            was = "Anfang" if schluessel == "hook_stil" else "Einladung in die App"
            test = f"{was} „{namen[k]}“ – bisher {n} von 3 Posts gemessen."
            kurz = f"{'den Anfang' if schluessel == 'hook_stil' else 'die Einladung'} „{namen[k]}“"
            break
    if test is None:
        stile = erk.get("stile") or []
        test = (f"Soraya bleibt meist beim Anfang „{stile[0]['name']}“ und probiert ab und zu etwas Neues."
                if stile else "Soraya probiert weiter verschiedene Anfänge aus.")
        kurz = (f"weiter den Anfang „{stile[0]['name']}“ – und ab und zu etwas Neues" if stile
                else "verschiedene Anfänge")
    return {"saetze": [{"art": "mehr", "titel": "Mehr davon", "text": mehr or duenn},
                       {"art": "weniger", "titel": "Weniger davon", "text": weniger or "Noch zu wenig Daten."},
                       {"art": "test", "titel": "Nächster Test", "text": test}],
            "test_kurz": kurz, "gemessen": len(gemessen), "duenn": mehr is None}


# ---------------------------------------------------------------------------
# Verbindungen und Follower
# ---------------------------------------------------------------------------
def verbunden() -> dict:
    out = {p: False for p in PLATTFORMEN}
    try:
        v = meta.verbindungen()
        out["facebook"], out["instagram"] = v["facebook"]["verbunden"], v["instagram"]["verbunden"]
    except Exception:  # noqa: BLE001
        pass
    try:
        out["tiktok"] = bool(tiktok.verbindung()["verbunden"])
    except Exception:  # noqa: BLE001
        pass
    return out


def follower(verb: dict) -> list[dict]:
    out = []
    for p in PLATTFORMEN:
        if not verb.get(p):
            continue
        try:
            s = posten.follower_stand(FOLLOWER_SCHLUESSEL[p])
        except Exception:  # noqa: BLE001
            s = {}
        out.append({"plattform": p, "follower": s.get("follower"), "zuwachs_7": s.get("zuwachs_7"), "am": s.get("am")})
    return out


# ---------------------------------------------------------------------------
# Das Cockpit
# ---------------------------------------------------------------------------
def _statistik(tage: int) -> tuple[dict | None, str | None]:
    try:
        return hole_statistik(tage), None
    except LookupError:
        return None, "nicht_verbunden"
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


def tiktok_extra() -> list[dict]:
    """TikTok-Videos ohne Soraya-Post (selbst gemacht): zaehlen bei Erreicht, Reaktionen und Plattformen mit."""
    try:
        videos = posten.tiktok_videos()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for v in videos:
        if v.get("post_id"):
            continue
        try:
            tag = _tag(datetime.fromisoformat(v["zeit"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"tag": tag, "erreicht": int(v.get("aufrufe") or 0), "titel": v.get("titel"), "url": v.get("url"),
                    "reaktionen": sum(int(v.get(k) or 0) for k in ("gefaellt", "kommentare", "geteilt"))})
    return out


def _kennzahlen(posts: list[dict], werte: dict, tage: list[date], stat_ok: bool, extra: list[dict] | None = None) -> dict:
    drin = [p for p in posts if p["tag"] and tage[0] <= p["tag"] <= tage[-1]]
    dazu = [x for x in (extra or []) if tage[0] <= x["tag"] <= tage[-1]]
    return {"erreicht": sum(p["erreicht"] for p in drin) + sum(x["erreicht"] for x in dazu),
            "reaktionen": sum(p["reaktionen_summe"] for p in drin) + sum(x["reaktionen"] for x in dazu),
            "besuche": _summe(werte, tage, "besuche") if stat_ok else None,
            "gratis": _summe(werte, tage, "gratis") if stat_ok else None,
            "konten": _summe(werte, tage, "konten") if stat_ok else None,
            "posts": len(drin), "gemessen": sum(1 for p in drin if p["gemessen"]) + len(dazu)}


def berechne(von: date, bis: date, *, heute: date | None = None, mit_tabelle: bool = True) -> dict:
    heute = heute or himmel.heute()
    laenge = (bis - von).days + 1
    vor_von, vor_bis = von - timedelta(days=laenge), von - timedelta(days=1)
    stat, stat_fehler = _statistik(max(1, min(180, (heute - vor_von).days + 1)))
    werte = tageswerte(stat)
    seit = datetime.combine(vor_von, uhrzeit.min, tzinfo=himmel.WIEN)
    try:
        zeilen = db.lade_cockpit_zeilen(seit)
    except Exception:  # noqa: BLE001
        zeilen = []
    posts = beitraege(zeilen, (stat or {}).get("quellen"))
    tage, vor_tage = _bereich(von, bis), _bereich(vor_von, vor_bis)
    extra = tiktok_extra()
    jetzt = _kennzahlen(posts, werte, tage, stat is not None, extra)
    vorher = _kennzahlen(posts, werte, vor_tage, stat is not None, extra)
    kpis = []
    for k, name in (("erreicht", "Erreicht"), ("reaktionen", "Reaktionen"), ("besuche", "Besuche"), ("konten", "Neue Konten")):
        # ohne Posts/ohne Statistik im Vorzeitraum gibt es keinen fairen Vergleich -> neutral
        vergleich = vorher[k] if (k in ("besuche", "konten") or vorher["gemessen"]) else None
        kpis.append({"schluessel": k, "name": name, "wert": jetzt[k], "vorher": vergleich,
                     "aenderung": aenderung(jetzt[k], vergleich)})
    im_zeitraum = [p for p in posts if p["tag"] and von <= p["tag"] <= bis]
    top = [p for p in sorted(im_zeitraum, key=lambda p: p["punkte"], reverse=True) if p["punkte"] > 0][:3]
    verlauf = []
    for d in tage:
        am_tag = [p for p in im_zeitraum if p["tag"] == d]
        w = werte.get(d.isoformat(), {})
        verlauf.append({"datum": d.isoformat(), "erreicht": sum(p["erreicht"] for p in am_tag)
                        + sum(x["erreicht"] for x in extra if x["tag"] == d),
                        "besuche": w.get("besuche", 0) if stat is not None else None,
                        "konten": w.get("konten", 0) if stat is not None else None, "posts": len(am_tag)})
    try:
        bewertet = redaktion.bewerte(db.lade_post, statistik=stat or {})
    except Exception:  # noqa: BLE001
        bewertet = []
    verb = verbunden()
    stand = max((p["zahlen_am"] for p in posts if p["zahlen_am"]), default=None)

    def oeffentlich(p: dict) -> dict:
        out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items()
               if k not in ("reaktionen", "kommentare", "geteilt", "gespeichert", "reichweite")}
        out["hook_name"] = redaktion.HOOK_NAMEN.get(p.get("hook_stil"))
        out["aufforderung_name"] = redaktion.AUFFORDERUNG_NAMEN.get(p.get("aufforderung"))
        return out

    tr = trichter(jetzt)
    try:
        zeiten = posten.einstellungen().get("zeiten") or {}
    except Exception:  # noqa: BLE001
        zeiten = {}
    verlaeufe = {}
    for pl in PLATTFORMEN:
        if verb.get(pl):
            try:
                verlaeufe[pl] = posten.follower_verlauf(FOLLOWER_SCHLUESSEL[pl])
            except Exception:  # noqa: BLE001
                verlaeufe[pl] = {}
    analyse = auswertung.auswerten(im_zeitraum, tage=tage, quellen=(stat or {}).get("quellen"), kpis=kpis, trichter=tr,
                                   trichter_vorher=trichter(vorher), follower_verlaeufe=verlaeufe, zeiten=zeiten,
                                   extra=extra, verbunden=[pl for pl in PLATTFORMEN if verb.get(pl)])

    return {
        "von": von.isoformat(), "bis": bis.isoformat(), "tage": laenge,
        "vorher": {"von": vor_von.isoformat(), "bis": vor_bis.isoformat()},
        "statistik": "ok" if stat is not None else stat_fehler,
        "verbunden": verb, "kpis": kpis, "follower": follower(verb),
        "top": [oeffentlich(p) for p in top],
        "trichter": tr,
        "analyse": analyse, "zeiten": zeiten,
        "lernen": lern_saetze(bewertet),
        "verlauf": verlauf,
        "beitraege": [oeffentlich(p) for p in im_zeitraum] if mit_tabelle else [],
        "zahlen_stand": stand.isoformat() if stand else None,
    }


def cockpit(tage: int = 7, heute: date | None = None) -> dict:
    """Cockpit der letzten `tage` Tage (bis heute), einige Minuten zwischengespeichert."""
    tage = 7 if tage not in (7, 30, 90) else tage
    heute = heute or himmel.heute()
    schluessel = ("cockpit", tage, heute.isoformat())
    with _SPERRE:
        treffer = _CACHE.get(schluessel)
        if treffer and time.time() - treffer[0] < CACHE_S:
            return treffer[1]
    daten = berechne(heute - timedelta(days=tage - 1), heute, heute=heute)
    with _SPERRE:
        _CACHE[schluessel] = (time.time(), daten)
    return daten


def leeren() -> None:
    with _SPERRE:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Wochenbericht (fuer „Heute“): letzte Kalenderwoche Mo–So, ohne Claude
# ---------------------------------------------------------------------------
def _woche(d: date) -> str:
    j, w, _ = d.isocalendar()
    return f"{j}-W{w:02d}"


def _zahl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def wochenbericht(heute: date | None = None) -> dict:
    """Bericht ueber die letzte Woche. Ab Montag sichtbar, bis er weggeklickt wird – so erscheint er auch,
    wenn der letzte gesehene Bericht aelter als 7 Tage ist."""
    heute = heute or himmel.heute()
    montag = heute - timedelta(days=heute.weekday())
    von, bis = montag - timedelta(days=7), montag - timedelta(days=1)
    woche = _woche(von)
    gesehen = (db.lade_einstellung("wochenbericht", {}) or {}).get("gesehen")
    schluessel = ("woche", woche)
    with _SPERRE:
        treffer = _CACHE.get(schluessel)
    if treffer and time.time() - treffer[0] < CACHE_S:
        c = treffer[1]
    else:
        c = berechne(von, bis, heute=heute, mit_tabelle=False)
        with _SPERRE:
            _CACHE[schluessel] = (time.time(), c)
    k = {x["schluessel"]: x for x in c["kpis"]}
    hat_daten = bool(k["erreicht"]["wert"] or k["reaktionen"]["wert"] or k["besuche"]["wert"] or k["konten"]["wert"])
    teile = []
    e = k["erreicht"]
    if e["wert"]:
        d = e["aenderung"]
        teile.append(f"{_zahl(e['wert'])} erreicht" + (f" ({'+' if d >= 0 else '−'}{abs(d)} %)" if d is not None else ""))
    elif k["besuche"]["wert"]:
        teile.append(f"{_zahl(k['besuche']['wert'])} Besuche")
    if k["konten"]["wert"]:
        teile.append(f"{_zahl(k['konten']['wert'])} neue Konten")
    beste = c["top"][0] if c["top"] else None
    return {"zeigen": hat_daten and gesehen != woche, "woche": woche, "von": von.isoformat(), "bis": bis.isoformat(),
            "zahlen": " · ".join(teile), "kpis": c["kpis"],
            "bester": {"id": beste["id"], "titel": beste["titel"], "art": beste["art"], "punkte": beste["punkte"]} if beste else None,
            "test": c["lernen"]["test_kurz"]}


def wochenbericht_gesehen(woche: str) -> None:
    if not re.fullmatch(r"\d{4}-W\d{2}", woche or ""):
        raise ValueError("Ungültige Woche.")
    db.setze_einstellung("wochenbericht", {"gesehen": woche})
