"""
Tagesplan aus dem Himmel
Jeden Morgen erstellt der Agent aus den echten Himmelsdaten (Mondphase,
Mondzeichen, Neu-/Vollmond, rueckläufige Planeten) die Posts des Tages,
pro Sprache: 1 Feed-Post, 1 Reel mit Skript, 1 Story.

Ob er jeden Morgen automatisch laeuft, schaltest du im Dashboard (Standard: aus).

Railway-Variablen (alle optional):
  TAGESPLAN_AUTO      "0" = Automatik ganz gesperrt (auch der Schalter wirkt dann nicht)
  TAGESPLAN_SPRACHEN  Standard "de,en,hu,it"
  TAGESPLAN_STUNDE    ab dieser Stunde (Wiener Zeit) wird erstellt, Standard 6
"""

import os
import threading
import time
from datetime import date, timedelta

import db
import himmel
import redaktion
from claude import frage_json
from sprachen import LINK_IN_BIO, SPRACHEN, norm, sprach_anweisung

SYSTEM_PROMPT = """Du bist die Social-Media-Redakteurin der App "Soraya Luxury Astrology Guide"
(persönliches Tageshoroskop aus dem eigenen Geburtshoroskop, Partner-Vergleich in Prozent,
Astro-Chat; ohne Konto zeigt Soraya sofort Sonnen- und Mondzeichen).

Du bekommst die echten Himmelsdaten des Tages und das heutige Format und schreibst daraus den
Tagesplan für Instagram, Facebook und TikTok. Ziel: Menschen hören beim Scrollen auf, fühlen sich
persönlich gemeint, speichern, kommentieren oder teilen – und schauen sich Soraya an.

Ton: elegant, warm, klug, ein bisschen mystisch. Nie reißerisch, keine Angstmacherei, keine
Heils-, Geld- oder Gesundheitsversprechen, keine Garantien.

Fakten:
- Nutze nur die gelieferten Daten (Mondphase, Mondzeichen, Sonne, Neu-/Vollmond, Rückläufigkeiten).
  Erfinde KEINE weiteren Ereignisse, Aspekte, Daten oder Zahlen. Tage-Angaben genau übernehmen.

Was gute Posts ausmacht:
- Der erste Satz ist der Hook: höchstens 12 Wörter, konkret, persönlich („du“), weckt Neugier
  oder spricht Sternzeichen direkt an. Denk dir mehrere Hooks aus und nimm den stärksten.
- Verboten sind leere Floskeln wie „Die Sterne stehen gut“, „Das Universum hat einen Plan“,
  „magische Energie“, „kosmische Schwingungen“, „Manifestiere jetzt“. Lieber ein konkretes Bild
  aus dem Alltag (Gespräch, Nachricht, Entscheidung, Schlaf, Arbeit, Beziehung).
- Kurze Absätze, gut lesbar am Handy. Höchstens 2 Emojis pro Text.
- Ein Post – eine Botschaft. Halte dich an das heutige Format.
- Keine Links und keine @-Erwähnungen im Text (der Agent fügt den Link selbst an).
- Wiederhole keine Überschriften der letzten Tage (Liste unten).
- Kommt ein Zielgruppen-Profil mit: Greife auf, was diese Menschen beschäftigt und wie sie
  sprechen. Sinngemäß in der Sprache des Posts, nicht wörtlich zitieren, nichts dazuerfinden.
- Kommen Beispiele mit, die gut angekommen sind: Lerne aus Thema und Ton, kopiere sie nicht.

Liefere genau drei Einträge, in dieser Reihenfolge:
1. art "post", platform "instagram": Feed-Post. "text": Hook, dann 2 bis 4 kurze Absätze
   (insgesamt 60-150 Wörter), dann eine Aufforderung zum Kommentieren oder Speichern, zum Schluss
   die heutige Handlungsaufforderung mit „{link_in_bio}“. "bild_punkte": wenn der Post eine Liste
   ist (z. B. drei Sternzeichen, drei Schritte), bis zu 3 sehr kurze Punkte fürs Bild (je höchstens
   5 Wörter), sonst [].
2. art "reel", platform "tiktok": Kurzvideo (12-18 Sekunden, Text-Video ohne Sprecher).
   "skript": "hook" (erste Einblendung, höchstens 8 Wörter, stoppt das Scrollen),
   "einblendungen" (3 Texte, je höchstens 8 Wörter, erzählen die Botschaft in Schritten, der
   letzte ist die Pointe), "szenen" (3 kurze Bild-Ideen, falls jemand selbst filmt),
   "schluss" (kurzer Schlusssatz, der neugierig auf das persönliche Horoskop macht, OHNE
   „{link_in_bio}“ oder andere Link-Hinweise – das Video zeigt darunter schon den Knopf, und es
   läuft auch auf Facebook). "text": Bildunterschrift, 1-3 Sätze,
   erster Satz wieder ein Hook. "bild_punkte": [].
3. art "story", platform "instagram": ein kurzer Satz zur Tagesenergie plus eine Frage, auf die
   man per Nachricht antworten kann (z. B. „Antworte mit 🌙 oder ☀️“), höchstens 40 Wörter.
   "bild_punkte": [].

Für jeden Eintrag:
- "titel": Bild-Überschrift, höchstens 6 Wörter, ohne Hashtags und Emojis.
- "untertitel": eine Zeile unter der Überschrift, höchstens 10 Wörter.
- "hashtags": 5 bis 8 Hashtags in der Sprache des Posts, mit #: 2 große (z. B. Astrologie),
  2-3 zum heutigen Thema bzw. Sternzeichen, 1-2 kleine Nischen-Hashtags. Story: 1-3 Hashtags.
- Bei "post" und "story" bleibt "skript" leer: hook "", szenen [], einblendungen [], schluss ""."""

_SKRIPT = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "szenen": {"type": "array", "items": {"type": "string"}},
        "einblendungen": {"type": "array", "items": {"type": "string"}},
        "schluss": {"type": "string"},
    },
    "required": ["hook", "szenen", "einblendungen", "schluss"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "thema": {"type": "string"},
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "art": {"type": "string", "enum": ["post", "reel", "story"]},
                    "platform": {"type": "string", "enum": ["instagram", "tiktok", "facebook"]},
                    "titel": {"type": "string"},
                    "untertitel": {"type": "string"},
                    "text": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "bild_punkte": {"type": "array", "items": {"type": "string"}},
                    "skript": _SKRIPT,
                },
                "required": ["art", "platform", "titel", "untertitel", "text", "hashtags", "bild_punkte", "skript"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["thema", "posts"],
    "additionalProperties": False,
}


def sprachen() -> list[str]:
    """Sprachen des Tagesplans: Auswahl im Dashboard, sonst TAGESPLAN_SPRACHEN, sonst alle."""
    try:
        gewaehlt = db.lade_einstellung("tagesplan_sprachen", None)
    except Exception:
        gewaehlt = None
    if gewaehlt:
        return [s for s in SPRACHEN if s in gewaehlt] or ["de"]
    roh = os.environ.get("TAGESPLAN_SPRACHEN") or ",".join(SPRACHEN)
    gewaehlt = [norm(s) for s in roh.split(",") if s.strip()]
    return [s for s in SPRACHEN if s in gewaehlt] or ["de"]


def gesperrt() -> bool:
    """TAGESPLAN_AUTO=0 in Railway sperrt die Automatik unabhaengig vom Schalter."""
    return (os.environ.get("TAGESPLAN_AUTO") or "").strip() == "0"


def automatisch() -> bool:
    """Schalter im Dashboard (Standard: aus). Bei einem Datenbankfehler lieber nichts erstellen."""
    if gesperrt():
        return False
    try:
        return bool(db.lade_einstellung("tagesplan_auto", False))
    except Exception as e:
        print(f"[Tagesplan] Schalter nicht lesbar, Automatik bleibt aus: {e}", flush=True)
        return False


def sprachen_setzen(liste: list[str]) -> list[str]:
    gewaehlt = [s for s in SPRACHEN if s in {str(x).strip().lower()[:2] for x in liste}]   # Unbekanntes ignorieren
    if not gewaehlt:
        raise ValueError("Mindestens eine Sprache wählen.")
    db.setze_einstellung("tagesplan_sprachen", gewaehlt)
    return sprachen()


def automatik_setzen(an: bool) -> bool:
    db.setze_einstellung("tagesplan_auto", bool(an))
    return automatisch()


def startstunde() -> int:
    try:
        return max(0, min(23, int(os.environ.get("TAGESPLAN_STUNDE") or 6)))
    except ValueError:
        return 6


# Recherche-Land -> Sprache der Posts (welches Profil passt zu welcher Sprache)
LAND_SPRACHE = {"at": "de", "de": "de", "ch": "de", "hu": "hu", "it": "it", "uk": "en", "us": "en"}


def zielgruppen_je_sprache(zeilen: list[dict] | None = None) -> dict:
    """Welches Profil der Tagesplan je Sprache nutzt: markierte Profile (passendes Land
    zuerst, sonst das neueste markierte). Ist keines markiert, je Sprache automatisch:
    passendes Land, sonst ein Profil ohne Land, sonst das neueste -- so schreibt z. B.
    Deutsch nicht fuer ein ungarisches Profil, nur weil es zuletzt erstellt wurde.
    Antwort: {sprache: {"id", "bereich", "automatisch"}} -- leer, wenn es keine Profile gibt."""
    if zeilen is None:
        zeilen = db.lade_zielgruppen(limit=50)
    markiert = [z for z in zeilen if z.get("im_tagesplan")]
    kandidaten = markiert or zeilen
    auswahl = {}
    for s in SPRACHEN:
        passend = [z for z in kandidaten if LAND_SPRACHE.get(z.get("land") or "") == s]
        ohne_land = [] if markiert else [z for z in kandidaten if not z.get("land")]
        z = (passend or ohne_land or kandidaten or [None])[0]
        if z:
            auswahl[s] = {"id": z["id"], "bereich": z["bereich"], "automatisch": not markiert}
    return auswahl


def _punkte(werte, n: int) -> str:
    if isinstance(werte, str):
        werte = [werte]
    werte = [str(w).strip() for w in (werte or []) if str(w).strip()][:n]
    return "; ".join(w[:160] for w in werte)


def zielgruppen_text(zeile: dict | None) -> str:
    """Kurzfassung eines Profils fuer den Prompt (nur das, was beim Schreiben hilft)."""
    if not zeile:
        return ""
    p = zeile.get("profil") or {}
    teile = [
        ("Wer sie sind", (p.get("wer_sind_sie") or "").strip()[:400]),
        ("Was sie beschäftigt", _punkte(p.get("beschaeftigt_sie") or p.get("beschäftigt_sie"), 4)),
        ("Ihre Worte", _punkte(p.get("sprache"), 6)),
        ("Was sie sich wünschen", _punkte(p.get("wuensche"), 3)),
        ("Worauf achten", _punkte(p.get("worauf_achten"), 3)),
    ]
    zeilen = [f"- {k}: {v}" for k, v in teile if v]
    if not zeilen:
        return ""
    return f"Zielgruppe (Recherche „{zeile.get('bereich')}“):\n" + "\n".join(zeilen)


def _frage(info: dict, sprache: str, bisherige: list[str], zielgruppe: dict | None, thema: dict,
           vorbilder: list[str]) -> str:
    profil = zielgruppen_text(zielgruppe)
    return (
        "Himmelsdaten für den Tag des Posts (bereits in der Zielsprache benannt):\n"
        f"{himmel.als_text(info)}\n\n"
        f"{redaktion.thema_text(thema, LINK_IN_BIO[sprache])}\n\n"
        + (f"{profil}\n\n" if profil else "")
        + ("Diese eigenen Posts haben zuletzt die meisten Besucher gebracht:\n"
           + "\n".join(f"- {v}" for v in vorbilder) + "\n\n" if vorbilder else "")
        + "Überschriften der letzten Tage (nicht wiederholen):\n"
        + ("\n".join(f"- {t}" for t in bisherige) if bisherige else "- (noch keine)")
        + f"\n\n{sprach_anweisung(sprache)}"
    )


def _aufbereiten(daten: dict, sprache: str) -> list[dict]:
    posts = []
    for p in daten.get("posts", [])[:3]:
        skript = p.get("skript") or {}
        punkte = [x.strip() for x in (p.get("bild_punkte") or []) if x and x.strip()][:3]
        posts.append({
            **{k: v for k, v in p.items() if k != "bild_punkte"},
            "sprache": sprache,
            "skript": skript if p.get("art") == "reel" and (skript.get("hook") or skript.get("szenen")) else None,
            "_bild_punkte": punkte if p.get("art") == "post" else [],
        })
    return posts


def schreibe_posts(info: dict, sprache: str, bisherige: list[str], zielgruppe: dict | None = None,
                   thema: dict | None = None, vorbilder: list[str] | None = None) -> list[dict]:
    """Ein Claude-Aufruf: die drei Eintraege des Tages in einer Sprache. Bei schweren Befunden
    der Qualitaetspruefung (z. B. falsche Sprache, heikle Versprechen) genau ein Korrekturdurchgang."""
    tag = date.fromisoformat(info["datum"]) if info.get("datum") else himmel.heute()
    thema = thema or redaktion.wochenthema(tag, info)
    system = SYSTEM_PROMPT.replace("{link_in_bio}", LINK_IN_BIO[sprache])
    frage = _frage(info, sprache, bisherige, zielgruppe, thema, vorbilder or [])
    posts = _aufbereiten(frage_json(system, frage, SCHEMA, effort="medium"), sprache)
    befunde = {i: redaktion.pruefe_post(p, sprache) for i, p in enumerate(posts)}
    if any(redaktion.schwer(b) for b in befunde.values()):
        hinweis = "\n".join(f"- {posts[i].get('art')}: {'; '.join(b)}" for i, b in befunde.items() if b)
        korrigiert = _aufbereiten(frage_json(
            system, frage + "\n\nDein erster Entwurf hatte diese Probleme, vermeide sie:\n" + hinweis,
            SCHEMA, effort="medium"), sprache)
        if korrigiert:
            posts = korrigiert
            befunde = {i: redaktion.pruefe_post(p, sprache) for i, p in enumerate(posts)}
    if not posts:
        raise RuntimeError("Claude hat keine Posts geliefert.")
    for i, p in enumerate(posts):
        p["_pruefung"] = befunde.get(i) or []
        p["_thema"] = thema["name"]
    return posts


def _zielgruppe_fuer(sprache: str) -> dict | None:
    """Das Profil fuer diese Sprache; ein Datenbankfehler hier soll den Tagesplan nicht stoppen."""
    try:
        zeilen = db.lade_zielgruppen(limit=50)
        wahl = zielgruppen_je_sprache(zeilen).get(sprache)
        return next((z for z in zeilen if wahl and z["id"] == wahl["id"]), None)
    except Exception as e:
        print(f"[Tagesplan] Zielgruppe nicht geladen: {e}", flush=True)
        return None


def erstelle(sprache: str, *, tag: date | None = None, erzwingen: bool = False, manuell: bool = False) -> dict:
    """Erstellt den Tagesplan fuer eine Sprache (falls noch nicht vorhanden)."""
    sprache = norm(sprache)
    tag = tag or himmel.heute()
    if not db.beanspruche_tagesplan(tag, sprache, erzwingen=erzwingen, manuell=manuell):
        return {"sprache": sprache, "status": "schon_da"}
    try:
        if erzwingen:
            db.loesche_tagesplan_entwuerfe(tag, sprache)
        info = himmel.aufbereiten(himmel.hole_himmel(tag), tag, sprache)
        zielgruppe = _zielgruppe_fuer(sprache)
        thema = redaktion.wochenthema(tag, info)
        vorbilder = redaktion.gut_angekommen(db.lade_post, sprache)
        posts = schreibe_posts(info, sprache, db.letzte_titel(sprache), zielgruppe, thema, vorbilder)
        gespeichert = []
        for p in posts:
            meta = himmel.bild_meta(info) | {"thema": p.pop("_thema"), "pruefung": p.pop("_pruefung")}
            punkte = p.pop("_bild_punkte", [])
            if punkte:
                meta["bild_punkte"] = punkte
            if zielgruppe:
                meta["zielgruppe"] = zielgruppe["bereich"]
            gespeichert += db.speichere_posts([p], quelle="himmel", geplant_fuer=tag, meta=meta)
        db.tagesplan_fertig(tag, sprache, info)
        print(f"[Tagesplan] {tag} {sprache}: {len(gespeichert)} Posts", flush=True)
        return {"sprache": sprache, "status": "fertig", "posts": len(gespeichert)}
    except Exception as e:
        db.tagesplan_fehler(tag, sprache, str(e))
        print(f"[Tagesplan] {tag} {sprache}: FEHLER {e}", flush=True)
        return {"sprache": sprache, "status": "fehler", "fehler": str(e)}


def erstelle_im_hintergrund(liste: list[str], *, erzwingen: bool = False) -> None:
    """Fuer den Knopf im Dashboard: laeuft weiter, waehrend die Seite den Stand abfragt."""
    def lauf():
        for s in liste:
            erstelle(s, erzwingen=erzwingen, manuell=True)
    threading.Thread(target=lauf, name="tagesplan-knopf", daemon=True).start()


_vorplanen_sperre = threading.Lock()


def vorplanen(tage: int = 7, liste: list[str] | None = None) -> dict:
    """Die naechsten Tage (ab morgen) im Hintergrund vorplanen, Tag fuer Tag, damit jeder Tag
    die Ueberschriften der Vortage kennt. Schon erstellte Tage kosten nichts (werden uebersprungen)."""
    tage = max(1, min(int(tage), 14))
    liste = liste or sprachen()
    erster = himmel.heute() + timedelta(days=1)
    daten = [erster + timedelta(days=i) for i in range(tage)]
    if not _vorplanen_sperre.acquire(blocking=False):
        return {"gestartet": False, "grund": "Vorplanen läuft bereits."}

    def lauf():
        try:
            for tag in daten:
                for s in liste:
                    erstelle(s, tag=tag, manuell=True)
        finally:
            _vorplanen_sperre.release()
    threading.Thread(target=lauf, name="tagesplan-vorplanen", daemon=True).start()
    return {"gestartet": True, "von": daten[0].isoformat(), "bis": daten[-1].isoformat(), "sprachen": liste}


def pruefe_faellige(jetzt_stunde: int | None = None) -> list[dict]:
    """Einmal pro Durchlauf des Zeitplans: fehlende Tagesplaene von heute und morgen erstellen.
    Morgen wird schon heute geschrieben -- so bleibt ein ganzer Abend Zeit zum Pruefen und Stoppen."""
    if not automatisch():
        return []
    stunde = jetzt_stunde if jetzt_stunde is not None else himmel.stunde_jetzt()
    if stunde < startstunde():
        return []
    heute = himmel.heute()
    return [erstelle(s, tag=t) for t in (heute, heute + timedelta(days=1)) for s in sprachen()]


def zeitplan_starten(intervall_sekunden: int = 600) -> None:
    """Hintergrund-Schleife: alle 10 Minuten nachsehen, ob der Tagesplan fehlt."""
    def schleife():
        time.sleep(20)  # dem Start Zeit lassen (Datenbank, Healthcheck)
        while True:
            try:
                pruefe_faellige()
            except Exception as e:
                print(f"[Tagesplan] Zeitplan-Fehler: {e}", flush=True)
            time.sleep(intervall_sekunden)
    threading.Thread(target=schleife, name="tagesplan-zeitplan", daemon=True).start()
