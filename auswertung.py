"""
Auswertung fuer die Unterreiter von „Wirkung“ (Plattformen, Lernen) und „Soraya erkennt“.

Alles wird aus den schon gemerkten Zahlen gerechnet (cockpit.beitraege, App-Statistik, Follower-Verlauf) --
kein Claude-Aufruf, keine Plattform-API. Bei wenigen Daten wird ehrlich „zu wenig Daten“ gemeldet statt
Muster zu erfinden: Gruppen mit weniger als GENUG gemessenen Posts zaehlen nicht fuer Aussagen.
"""

from collections import Counter
from datetime import date

import redaktion

PLATTFORMEN = ("facebook", "instagram", "tiktok")
PL_NAME = {"facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok"}
BIO = {"facebook": "bio-fb", "instagram": "bio-ig", "tiktok": "bio-tt"}
PLATZ_NAME = {"post": "Feed-Post", "reel": "Reel", "reel2": "2. Reel", "story": "Story"}
PLATZ_MEHRZAHL = {"post": "Feed-Posts", "reel": "Reels", "reel2": "Zweite Reels", "story": "Storys"}
PLAETZE = ("story", "post", "reel", "reel2")
SPRACH_NAME = {"de": "Deutsch", "en": "Englisch", "hu": "Ungarisch", "it": "Italienisch"}
# Zeitfenster der Heatmap (Wiener Zeit): [von, bis)
SLOTS = [(0, 9, "bis 9"), (9, 12, "9–12"), (12, 15, "12–15"), (15, 18, "15–18"), (18, 21, "18–21"), (21, 24, "ab 21")]
GENUG = 3          # ab so vielen gemessenen Posts zaehlt eine Gruppe fuer Aussagen
SICHER = 6         # ab so vielen gilt ein Selbst-Test als recht sicher


def slot_von(stunde: int | None) -> int | None:
    if stunde is None:
        return None
    return next(i for i, (a, b, _) in enumerate(SLOTS) if a <= stunde < b)


def komma(x: float, stellen: int = 1) -> str:
    if x >= 10 or float(x).is_integer():
        return str(round(x))
    return f"{x:.{stellen}f}".replace(".", ",")


def zahl(n) -> str:
    return f"{int(round(n)):,}".replace(",", "\u00a0")      # wie im Dashboard (de-AT): 1 234


def _schnitt(werte: list, ganz: bool = False) -> float | None:
    if not werte:
        return None
    return round(sum(werte) / len(werte)) if ganz else round(sum(werte) / len(werte), 1)


def sicherheit(n: int) -> str:
    return "gut" if n >= SICHER else "erste" if n >= GENUG else "wenig"


def gruppen(posts: list[dict], schluessel, namen: dict | None = None, alle: tuple | list | None = None) -> list[dict]:
    """Ø Punkte und Ø erreicht je Gruppe (nur gemessene Posts). alle: Gruppen, die auch mit 0 Posts erscheinen."""
    g: dict = {k: [] for k in (alle or [])}
    for p in posts:
        k = schluessel(p)
        if k:
            g.setdefault(k, []).append(p)
    out = []
    for k, liste in g.items():
        out.append({"schluessel": k, "name": (namen or {}).get(k, k), "posts": len(liste),
                    "schnitt": _schnitt([p["punkte"] for p in liste]),
                    "schnitt_erreicht": _schnitt([p["erreicht"] for p in liste], True),
                    "genug": len(liste) >= GENUG, "sicherheit": sicherheit(len(liste))})
    # erst die mit genug Daten (nach Punkten), dann die duennen
    return sorted(out, key=lambda x: (not x["genug"], -(x["schnitt"] or 0), -x["posts"]))


# ---------------------------------------------------------------------------
# Plattformen
# ---------------------------------------------------------------------------
def plattform_tage(posts: list[dict], tage: list[date], extra: list[dict] | None = None) -> list[dict]:
    """Erreicht je Tag und Plattform -- dem Tag zugeordnet, an dem der Post erschien.
    extra: TikTok-Videos ohne Soraya-Post (zaehlen bei TikTok mit)."""
    out = {d.isoformat(): {"datum": d.isoformat(), **{pl: 0 for pl in PLATTFORMEN}, "posts": 0} for d in tage}
    for p in posts:
        t = out.get(p["tag"].isoformat()) if p.get("tag") else None
        if not t:
            continue
        t["posts"] += 1
        for pl, x in p["plattformen"].items():
            if pl in PLATTFORMEN and x.get("erreicht"):
                t[pl] += x["erreicht"]
    for x in extra or []:
        t = out.get(x["tag"].isoformat()) if x.get("tag") else None
        if t:
            t["tiktok"] += x["erreicht"]
    return list(out.values())


def plattform_vergleich(posts: list[dict], quellen: dict | None, tage: list[date], extra: list[dict] | None = None,
                        verbunden: list | tuple = ()) -> dict:
    """Je Plattform: Posts, erreicht, Reaktionen, Bio-Besuche. Verbundene Plattformen erscheinen auch mit 0,
    TikTok-Videos ohne Soraya-Post zaehlen bei TikTok mit (videos_extra)."""
    von, bis = tage[0].isoformat(), tage[-1].isoformat()
    dazu = [x for x in (extra or []) if x.get("tag") and tage[0] <= x["tag"] <= tage[-1]]
    zeilen = []
    for pl in PLATTFORMEN:
        mit = [p for p in posts if pl in p["plattformen"]]
        gem = [p["plattformen"][pl] for p in mit if p["plattformen"][pl].get("erreicht") is not None]
        bio = ((quellen or {}).get(BIO[pl]) or {}).get("tage") or {}
        zeilen.append({"plattform": pl, "posts": len(mit), "gemessen": len(gem),
                       "erreicht": sum(x["erreicht"] for x in gem), "reaktionen": sum(x["reaktionen"] or 0 for x in gem),
                       "besuche": sum(int(n or 0) for d, n in bio.items() if von <= str(d)[:10] <= bis),
                       "schnitt_erreicht": _schnitt([x["erreicht"] for x in gem], True), "videos_extra": 0})
        if pl == "tiktok" and dazu:
            z = zeilen[-1]
            z["videos_extra"] = len(dazu)
            z["gemessen"] += len(dazu)
            z["erreicht"] += sum(x["erreicht"] for x in dazu)
            z["reaktionen"] += sum(x["reaktionen"] for x in dazu)
    zeilen = [z for z in zeilen if z["posts"] or z["besuche"] or z["videos_extra"] or z["plattform"] in verbunden]
    for k in ("erreicht", "reaktionen", "besuche"):
        ges = sum(z[k] for z in zeilen)
        for z in zeilen:
            z["anteil_" + k] = round(z[k] / ges * 100) if ges else None
    post_links = sum(p.get("besuche") or 0 for p in posts)
    return {"zeilen": zeilen, "post_link_besuche": post_links}


def follower_kurven(verlaeufe: dict, tage: list[date]) -> list[dict]:
    """Je Plattform: Follower im Zeitraum (plus der letzte Wert davor als Startpunkt) und Zuwachs."""
    out = []
    von, bis = tage[0].isoformat(), tage[-1].isoformat()
    for pl, verlauf in verlaeufe.items():
        vorher = [d for d in verlauf if d < von]
        punkte = [{"datum": d, "follower": int(n)} for d, n in verlauf.items() if von <= d <= bis]
        start = verlauf[vorher[-1]] if vorher else (punkte[0]["follower"] if punkte else None)
        if vorher and (not punkte or punkte[0]["datum"] != von):
            punkte.insert(0, {"datum": von, "follower": int(start), "davor": True})
        out.append({"plattform": pl, "punkte": punkte, "start": int(start) if start is not None else None,
                    "zuwachs": (punkte[-1]["follower"] - start) if punkte and start is not None else None,
                    "aktuell": punkte[-1]["follower"] if punkte else None})
    return out


# ---------------------------------------------------------------------------
# Lernen: Zeiten-Heatmap
# ---------------------------------------------------------------------------
def zeiten_karte(posts: list[dict], zeiten: dict) -> dict:
    zellen: dict = {}
    for p in posts:
        s = slot_von(p.get("stunde"))
        if s is None or not p.get("tag"):
            continue
        zellen.setdefault((p["tag"].weekday(), s), []).append(p)
    liste = [{"tag": t, "slot": s, "posts": len(v), "schnitt": _schnitt([p["punkte"] for p in v]),
              "schnitt_erreicht": _schnitt([p["erreicht"] for p in v], True)} for (t, s), v in sorted(zellen.items())]
    spalten = []
    for i, (_, _, name) in enumerate(SLOTS):
        v = [p for p in posts if slot_von(p.get("stunde")) == i]
        spalten.append({"slot": i, "name": name, "posts": len(v), "schnitt": _schnitt([p["punkte"] for p in v])})
    eingestellt = []
    for platz in PLAETZE:
        z = (zeiten or {}).get(platz)
        if z:
            eingestellt.append({"platz": platz, "name": PLATZ_NAME[platz], "zeit": z, "slot": slot_von(int(z[:2]))})
    return {"slots": [n for _, _, n in SLOTS], "zellen": liste, "spalten": spalten, "eingestellt": eingestellt}


def beste_zeiten(posts: list[dict], zeiten: dict) -> list[dict]:
    """Je Termin-Platz: bestes und schwaechstes Zeitfenster, wenn mindestens zwei Fenster mit je GENUG
    gemessenen Posts verglichen werden koennen. Mit Vorschlag, falls die eingestellte Zeit woanders liegt."""
    out = []
    for platz in PLAETZE:
        je: dict = {}
        for p in posts:
            if p["platz"] == platz and p.get("stunde") is not None:
                je.setdefault(slot_von(p["stunde"]), []).append(p)
        kandidaten = [(s, v) for s, v in je.items() if len(v) >= GENUG]
        if len(kandidaten) < 2:
            continue
        kandidaten.sort(key=lambda sv: sum(p["punkte"] for p in sv[1]) / len(sv[1]), reverse=True)
        (s1, v1), (s2, v2) = kandidaten[0], kandidaten[-1]
        a, b = sum(p["punkte"] for p in v1) / len(v1), sum(p["punkte"] for p in v2) / len(v2)
        stunde = Counter(p["stunde"] for p in v1).most_common(1)[0][0]
        stunde2 = Counter(p["stunde"] for p in v2).most_common(1)[0][0]
        jetzt = (zeiten or {}).get(platz)
        out.append({"platz": platz, "slot": s1, "stunde": stunde, "schnitt": round(a, 1), "posts": len(v1),
                    "statt_slot": s2, "statt_stunde": stunde2, "statt_schnitt": round(b, 1), "statt_posts": len(v2),
                    "faktor": round(a / b, 1) if b else None, "eingestellt": jetzt,
                    "vorschlag": f"{stunde:02d}:00" if jetzt and slot_von(int(jetzt[:2])) != s1 and b and a / b >= 1.3 else None})
    return out


# ---------------------------------------------------------------------------
# Soraya erkennt: Erkenntnis-Karten (serverseitig, ohne KI)
# ---------------------------------------------------------------------------
def _karte(id_, art, text, zahl_, gewicht, detail=None, **extra) -> dict:
    return {"id": id_, "art": art, "text": text, "zahl": zahl_, "detail": detail, "gewicht": round(gewicht, 1), **extra}


def erkennt(gem: list[dict], *, kpis: dict, trichter: dict, plattformen: dict, zeiten: list[dict],
            follower: list[dict], formate: list[dict], tage: int, max_karten: int = 5) -> list[dict]:
    karten = []
    n = len(gem)

    # 1) Arten vergleichen: Ø erreicht je Termin-Platz
    arten = [g for g in gruppen(gem, lambda p: p["platz"], PLATZ_NAME) if g["genug"] and g["schnitt_erreicht"]]
    if len(arten) >= 2:
        arten.sort(key=lambda g: g["schnitt_erreicht"], reverse=True)
        hoch, tief = arten[0], arten[-1]
        f = hoch["schnitt_erreicht"] / tief["schnitt_erreicht"]
        if f >= 1.5:
            karten.append(_karte("arten", "plus", f"{PLATZ_MEHRZAHL[hoch['schluessel']]} erreichen {komma(f)}× mehr Menschen "
                                 f"als {PLATZ_MEHRZAHL[tief['schluessel']]}", f"{komma(f)}×", 20 + min(f, 5) * 6,
                                 f"Ø {zahl(hoch['schnitt_erreicht'])} statt {zahl(tief['schnitt_erreicht'])} erreicht · "
                                 f"{hoch['posts']} + {tief['posts']} Posts"))

    # 2) Plattform mit der meisten Reichweite
    pls = [z for z in plattformen["zeilen"] if z["gemessen"] and z["erreicht"]]
    if len(pls) >= 2:
        pls.sort(key=lambda z: z["erreicht"], reverse=True)
        top, zweite = pls[0], pls[1]
        if (top["anteil_erreicht"] or 0) >= 45 and top["anteil_erreicht"] - (zweite["anteil_erreicht"] or 0) >= 10:
            karten.append(_karte("plattform", "info", f"{PL_NAME[top['plattform']]} bringt die meiste Reichweite",
                                 f"{top['anteil_erreicht']} %", 18 + top["anteil_erreicht"] / 5,
                                 f"{zahl(top['erreicht'])} von {zahl(sum(z['erreicht'] for z in pls))} erreicht · "
                                 f"Ø {zahl(top['schnitt_erreicht'] or 0)} je Post", plattform=top["plattform"]))

    # 3) Beste Uhrzeit je Platz (mit Vorschlag zum Übernehmen)
    for z in zeiten:
        if not z["faktor"] or z["faktor"] < 1.3 or not z["schnitt"]:
            continue
        name = PLATZ_MEHRZAHL[z["platz"]]
        aktion = ({"platz": z["platz"], "zeit": z["vorschlag"],
                   "text": f"{PLATZ_NAME[z['platz']]} auf {int(z['vorschlag'][:2])}:00 Uhr"} if z["vorschlag"] else None)
        karten.append(_karte(f"zeit-{z['platz']}", "plus", f"{name} um {z['stunde']} Uhr laufen besser als um {z['statt_stunde']} Uhr",
                             f"{komma(z['faktor'])}×", 22 + min(z["faktor"], 4) * 5 + (6 if aktion else 0),
                             f"Ø {komma(z['schnitt'])} statt {komma(z['statt_schnitt'])} Punkte · {z['posts']} + {z['statt_posts']} Posts"
                             + (f" · eingestellt: {z['eingestellt']} Uhr" if z["eingestellt"] else ""), aktion=aktion))

    # 4) Ausreisser: ein Post weit über (oder unter) dem Schnitt
    if n >= 5:
        schnitt = sum(p["punkte"] for p in gem) / n
        if schnitt > 0:
            bester = max(gem, key=lambda p: p["punkte"])
            f = bester["punkte"] / schnitt
            if f >= 2.5 and bester["punkte"] >= 5:
                karten.append(_karte("ausreisser", "plus", f"„{bester.get('titel') or 'Post ' + str(bester['id'])}“ lief "
                                     f"{komma(f)}× besser als dein Schnitt" + (f" – Format {bester['format']}" if bester.get("format") else ""),
                                     f"{komma(f)}×", 26 + min(f, 6) * 3,
                                     f"{zahl(bester['punkte'])} Punkte statt Ø {komma(schnitt)} · {PLATZ_NAME.get(bester['platz'], 'Post')}",
                                     post_id=bester["id"]))
            schwach = [p for p in gem if p["punkte"] <= schnitt * 0.25]
            if schnitt >= 8 and schwach:
                p = min(schwach, key=lambda x: x["punkte"])
                karten.append(_karte("ausreisser-tief", "minus", f"„{p.get('titel') or 'Post ' + str(p['id'])}“ blieb weit unter "
                                     "deinem Schnitt", f"{zahl(p['punkte'])}", 10,
                                     f"{zahl(p['punkte'])} Punkte statt Ø {komma(schnitt)}" + (f" · Format {p['format']}" if p.get("format") else ""),
                                     post_id=p["id"]))

    # 5) Trend gegenüber dem Zeitraum davor
    e = kpis.get("erreicht") or {}
    if e.get("aenderung") is not None and (e.get("vorher") or 0) >= 50 and abs(e["aenderung"]) >= 25:
        auf = e["aenderung"] > 0
        karten.append(_karte("trend", "plus" if auf else "minus",
                             f"Deine Reichweite {'steigt' if auf else 'sinkt'} gegenüber den {tage} Tagen davor",
                             f"{'+' if auf else '−'}{abs(e['aenderung'])} %", 16 + min(abs(e["aenderung"]), 200) / 10,
                             f"{zahl(e['wert'])} statt {zahl(e['vorher'])} erreicht"))
    b = kpis.get("besuche") or {}
    g = next((s for s in trichter["stufen"] if s["schluessel"] == "gratis"), {})
    if (b.get("wert") or 0) >= 15 and g.get("wert") is not None and g["wert"] / b["wert"] < 0.1:
        steigt = (b.get("aenderung") or 0) > 0
        karten.append(_karte("landing", "achtung", ("Besuche steigen, aber" if steigt else "Besuche kommen an, aber") +
                             " kaum Gratis-Tests → Landingpage prüfen", komma(g["wert"] / b["wert"] * 100) + " %", 30,
                             f"{zahl(g['wert'])} Gratis-Tests aus {zahl(b['wert'])} Besuchen"))
    elif (e.get("wert") or 0) >= 300 and b.get("wert") is not None and b["wert"] / e["wert"] < 0.01:
        karten.append(_karte("klicks", "achtung", "Viele sehen deine Posts, aber kaum jemand klickt den Link",
                             komma(b["wert"] / e["wert"] * 100) + " %", 24,
                             f"{zahl(b['wert'])} Besuche aus {zahl(e['wert'])} erreicht"))

    # 6) Bestes Format
    fm = [f for f in formate if f["genug"]]
    if len(fm) >= 2 and n:
        schnitt = sum(p["punkte"] for p in gem) / n
        if schnitt and fm[0]["schnitt"] / schnitt >= 1.3:
            karten.append(_karte("format", "plus", f"Das Format „{fm[0]['name']}“ kommt am besten an",
                                 f"Ø {komma(fm[0]['schnitt'])}", 14 + min(fm[0]["schnitt"] / schnitt, 4) * 3,
                                 f"Punkte je Post (dein Schnitt: {komma(schnitt)}) · {fm[0]['posts']} Posts"))

    # 7) Follower-Wachstum
    wachsen = [f for f in follower if f.get("zuwachs")]
    if wachsen:
        f = max(wachsen, key=lambda x: x["zuwachs"])
        if f["zuwachs"] > 0:
            karten.append(_karte("follower", "plus", f"{PL_NAME.get(f['plattform'], f['plattform'])} wächst am schnellsten",
                                 f"+{zahl(f['zuwachs'])}", 8 + min(f["zuwachs"], 50) / 5, f"Follower in diesen {tage} Tagen"))

    karten.sort(key=lambda k: k["gewicht"], reverse=True)
    karten = karten[:max_karten]
    if n < 5:
        duenn = _karte("duenn", "duenn", "Noch zu wenig Daten für sichere Muster",
                       str(n), 0, f"{n} gemessene{'r' if n == 1 else ''} Post{'' if n == 1 else 's'} in diesem Zeitraum – "
                       "ab etwa 5 erkennt Soraya, was besser läuft. Tipp: längeren Zeitraum wählen.")
        karten = karten[:max_karten - 1] + [duenn]
    return karten


# ---------------------------------------------------------------------------
# Alles zusammen
# ---------------------------------------------------------------------------
def auswerten(im_zeitraum: list[dict], *, tage: list[date], quellen: dict | None, kpis: list[dict], trichter: dict,
              trichter_vorher: dict, follower_verlaeufe: dict, zeiten: dict, extra: list[dict] | None = None,
              verbunden: list | tuple = ()) -> dict:
    gem = [p for p in im_zeitraum if p["gemessen"]]
    pv = plattform_vergleich(im_zeitraum, quellen, tage, extra, verbunden)
    fk = follower_kurven(follower_verlaeufe, tage)
    formate = gruppen(gem, lambda p: p.get("format"))
    bz = beste_zeiten(gem, zeiten)
    sprachen = gruppen(gem, lambda p: p.get("sprache"), SPRACH_NAME)
    return {
        "gemessen": len(gem), "posts": len(im_zeitraum),
        "plattform_tage": plattform_tage(im_zeitraum, tage, extra),
        "plattformen": pv,
        "follower": fk,
        "arten": gruppen(gem, lambda p: p["platz"], PLATZ_NAME, alle=[a for a in ("post", "reel", "reel2", "story")
                                                                       if any(p["platz"] == a for p in im_zeitraum)]),
        "formate": formate,
        "zeiten": {**zeiten_karte(gem, zeiten), "beste": bz},
        "stile": gruppen(gem, lambda p: p.get("hook_stil"), redaktion.HOOK_NAMEN, alle=list(redaktion.HOOK_NAMEN)),
        "aufforderungen": gruppen(gem, lambda p: p.get("aufforderung"), redaktion.AUFFORDERUNG_NAMEN,
                                  alle=list(redaktion.AUFFORDERUNG_NAMEN)),
        "sprachen": sprachen if len({p.get("sprache") for p in im_zeitraum if p.get("sprache")}) > 1 else [],
        "trichter_vorher": trichter_vorher,
        "erkennt": erkennt(gem, kpis={k["schluessel"]: k for k in kpis}, trichter=trichter, plattformen=pv, zeiten=bz,
                           follower=fk, formate=formate, tage=len(tage)),
    }

