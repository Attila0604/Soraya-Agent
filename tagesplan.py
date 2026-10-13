"""
Tagesplan aus dem Himmel
Jeden Morgen erstellt der Agent aus den echten Himmelsdaten (Mondphase,
Mondzeichen, Neu-/Vollmond, rueckläufige Planeten) die Posts des Tages,
pro Sprache: 1 Feed-Post, 1 Reel mit Skript, 1 Story.

Railway-Variablen (alle optional):
  TAGESPLAN_AUTO      "1" (Standard) = jeden Morgen automatisch, "0" = nur per Knopf
  TAGESPLAN_SPRACHEN  Standard "de,en,hu,it"
  TAGESPLAN_STUNDE    ab dieser Stunde (Wiener Zeit) wird erstellt, Standard 6
"""

import os
import threading
import time
from datetime import date, timedelta

import db
import himmel
from claude import frage_json
from sprachen import LINK_IN_BIO, SPRACHEN, norm, sprach_anweisung

SYSTEM_PROMPT = """Du bist Social-Media-Redakteurin der App "Soraya Luxury Astrology Guide"
(persönliches Tageshoroskop aus dem eigenen Geburtshoroskop, Partner-Vergleich in
Prozent, KI-Chat; ohne Konto zeigt Soraya sofort Sonnen- und Mondzeichen).

Du bekommst die echten Himmelsdaten von heute und schreibst daraus den Tagesplan
für Instagram, TikTok und Facebook. Ton: elegant, warm, ein bisschen mystisch,
nie reißerisch, keine Angstmacherei, keine Heilsversprechen.

Regeln:
- Beziehe dich konkret auf die gelieferten Daten (Mondphase, Mondzeichen,
  Neumond/Vollmond, rückläufige Planeten). Erfinde KEINE weiteren Ereignisse,
  Aspekte oder Daten. Tage-Angaben genau so übernehmen, wie sie geliefert werden.
- Steht ein Neumond oder Vollmond in den nächsten 3 Tagen an, ist das das Hauptthema.
- Übersetze Astrologie in Alltag: was heißt das für Gefühle, Beziehungen, Entscheidungen?
- Soraya nur dezent erwähnen; am Ende von Reel und Feed-Post ein kurzer Hinweis wie
  „Dein persönliches Horoskop: {link_in_bio}" (in der Sprache des Posts).
- Wiederhole keine Überschriften der letzten Tage (Liste unten).
- Kommt ein Zielgruppen-Profil mit: Greife auf, was diese Menschen beschäftigt und
  wie sie sprechen, damit sie sich angesprochen fühlen. Sinngemäß in der Sprache des
  Posts, nicht wörtlich zitieren, nichts über sie dazuerfinden. Der Himmel bleibt der
  Anlass des Tages, die Zielgruppe bestimmt den Blickwinkel.

Liefere genau drei Einträge, in dieser Reihenfolge:
1. art "post", platform "instagram": Feed-Post (Bild + Text, 60-150 Wörter).
2. art "reel", platform "tiktok": Kurzvideo 20-30 Sekunden. "skript" enthält
   "hook" (erster Satz, max. 10 Wörter, macht neugierig), 3 bis 4 "szenen"
   (je ein Satz, was gesagt bzw. gezeigt wird) und "schluss" (Abschluss mit Hinweis
   auf den Link). "text" ist die Bildunterschrift zum Video (1-3 Sätze).
3. art "story", platform "instagram": Story, ein kurzer Satz plus eine Frage oder
   Umfrage-Idee an die Follower ("text", max. 40 Wörter).

Für jeden Eintrag:
- "titel": Bild-Überschrift, höchstens 6 Wörter, ohne Hashtags und Emojis.
- "untertitel": eine Zeile unter der Überschrift, höchstens 10 Wörter.
- "hashtags": 4 bis 6 Hashtags in der Sprache des Posts, mit #.
- Bei "post" und "story" bleibt "skript" leer: hook "", szenen [], schluss ""."""

_SKRIPT = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "szenen": {"type": "array", "items": {"type": "string"}},
        "schluss": {"type": "string"},
    },
    "required": ["hook", "szenen", "schluss"],
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
                    "skript": _SKRIPT,
                },
                "required": ["art", "platform", "titel", "untertitel", "text", "hashtags", "skript"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["thema", "posts"],
    "additionalProperties": False,
}


def sprachen() -> list[str]:
    roh = os.environ.get("TAGESPLAN_SPRACHEN") or ",".join(SPRACHEN)
    gewaehlt = [norm(s) for s in roh.split(",") if s.strip()]
    return [s for s in SPRACHEN if s in gewaehlt] or ["de"]


def automatisch() -> bool:
    return (os.environ.get("TAGESPLAN_AUTO") or "1").strip() != "0"


def startstunde() -> int:
    try:
        return max(0, min(23, int(os.environ.get("TAGESPLAN_STUNDE") or 6)))
    except ValueError:
        return 6


# Recherche-Land -> Sprache der Posts (welches Profil passt zu welcher Sprache)
LAND_SPRACHE = {"at": "de", "de": "de", "ch": "de", "hu": "hu", "it": "it", "uk": "en", "us": "en"}


def zielgruppen_je_sprache(zeilen: list[dict] | None = None) -> dict:
    """Welches Profil der Tagesplan je Sprache nutzt: markierte Profile (passendes Land
    zuerst, sonst das neueste markierte); ist keines markiert, das neueste Profil.
    Antwort: {sprache: {"id", "bereich", "automatisch"}} -- leer, wenn es keine Profile gibt."""
    if zeilen is None:
        zeilen = db.lade_zielgruppen(limit=50)
    markiert = [z for z in zeilen if z.get("im_tagesplan")]
    kandidaten = markiert or zeilen[:1]
    auswahl = {}
    for s in SPRACHEN:
        passend = [z for z in kandidaten if LAND_SPRACHE.get(z.get("land") or "") == s]
        z = (passend or kandidaten or [None])[0]
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


def schreibe_posts(info: dict, sprache: str, bisherige: list[str], zielgruppe: dict | None = None) -> list[dict]:
    """Ein Claude-Aufruf: die drei Eintraege des Tages in einer Sprache."""
    system = SYSTEM_PROMPT.replace("{link_in_bio}", LINK_IN_BIO[sprache])
    profil = zielgruppen_text(zielgruppe)
    frage = (
        "Himmelsdaten für den Tag des Posts (bereits in der Zielsprache benannt):\n"
        f"{himmel.als_text(info)}\n\n"
        + (f"{profil}\n\n" if profil else "")
        + "Überschriften der letzten Tage (nicht wiederholen):\n"
        + ("\n".join(f"- {t}" for t in bisherige) if bisherige else "- (noch keine)")
        + f"\n\n{sprach_anweisung(sprache)}"
    )
    daten = frage_json(system, frage, SCHEMA, effort="medium")
    posts = []
    for p in daten.get("posts", [])[:3]:
        skript = p.get("skript") or {}
        posts.append({
            **p,
            "sprache": sprache,
            "skript": skript if p.get("art") == "reel" and (skript.get("hook") or skript.get("szenen")) else None,
        })
    if not posts:
        raise RuntimeError("Claude hat keine Posts geliefert.")
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
        posts = schreibe_posts(info, sprache, db.letzte_titel(sprache), zielgruppe)
        meta = himmel.bild_meta(info)
        if zielgruppe:
            meta["zielgruppe"] = zielgruppe["bereich"]
        gespeichert = db.speichere_posts(posts, quelle="himmel", geplant_fuer=tag, meta=meta)
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
    """Einmal pro Durchlauf des Zeitplans: fehlende Tagesplaene von heute erstellen."""
    if not automatisch():
        return []
    stunde = jetzt_stunde if jetzt_stunde is not None else himmel.stunde_jetzt()
    if stunde < startstunde():
        return []
    return [erstelle(s) for s in sprachen()]


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
