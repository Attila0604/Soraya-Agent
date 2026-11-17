"""
Kommentare auf Facebook beantworten (seit 18.11.2026)

Das Content Studio zeigt die neuen Kommentare unter Sorayas Facebook-Beitraegen der letzten Tage und schlaegt
auf Knopfdruck passende Antworten im Soraya-Ton vor (ein Claude-Aufruf fuer mehrere Kommentare). Attila kopiert die
Antwort und antwortet auf Facebook -- Soraya schreibt selbst nichts (dafuer braeuchte die Meta-App zusaetzlich
pages_manage_engagement). Lesen braucht pages_read_user_content (ist in FB_SCOPES).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import db
import himmel
import meta

TAGE = 4                     # Beitraege der letzten Tage
MAX_BEITRAEGE = 20
CACHE_S = 120
_CACHE: dict = {}

SYSTEM = """Du bist Soraya, eine warme, weise Astrologin, und beantwortest Kommentare unter deinen Facebook-Beiträgen.
Die Leserinnen sind meist Frauen ab 40, oft aus Ungarn. Antworte IMMER in der Sprache des Kommentars, muttersprachlich,
natürlich und herzlich, mit dem Vornamen (wenn bekannt), 1–2 kurze Sätze, höchstens 2 Emojis. Immer positiv, nie
belehrend, nichts versprechen, keine Links. Für jeden Kommentar entscheidest du:
- "herz": nur ein Sternzeichen, Emoji, „köszönöm“ o. ä. -> ein Herz als Reaktion reicht; trotzdem 2 sehr kurze Antworten
  vorschlagen (z. B. „Szép napot, kedves Mérleg! ⚖️✨“).
- "antworten": jemand erzählt etwas, fragt, freut sich, ist traurig oder skeptisch-freundlich -> 3 Antworten in
  verschiedenem Ton (warm, verspielt, kurz). Bei echtem Interesse an mehr (Aszendent, Zukunft, Partner, persönliches
  Horoskop) darf EINE der Antworten sanft auf die kostenlose Soraya-App hinweisen, ohne Link: Android: Google Play
  „Soraya Astro“, iPhone: bei Google „Soraya Luxury Astrology“ suchen.
- "verbergen": beleidigend, Betrugs-Vorwurf, Spam, Werbung, abwertend -> nicht diskutieren, keine Vorschläge.
"hinweis": ein kurzer Satz auf Deutsch für den Seitenbetreiber, was die Person meint (bei Ironie oder unklaren Kommentaren
besonders hilfreich)."""

SCHEMA = {
    "type": "object",
    "properties": {"antworten": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "art": {"type": "string", "enum": ["herz", "antworten", "verbergen"]},
                       "hinweis": {"type": "string"}, "vorschlaege": {"type": "array", "items": {"type": "string"}}},
        "required": ["id", "art", "hinweis", "vorschlaege"], "additionalProperties": False}}},
    "required": ["antworten"],
    "additionalProperties": False,
}


def leeren() -> None:
    _CACHE.clear()


def _seite_und_token() -> tuple[str, str]:
    z = meta.zugang("facebook")
    if not z or not z.get("token") or not z.get("seite_id"):
        raise meta.MetaFehler("Facebook-Seite ist nicht verbunden.")
    return str(z["seite_id"]), z["token"]


def _kommentare_von(oid: str, token: str) -> list[dict]:
    d = meta._get(f"{meta.graph_fb()}/{oid}/comments", access_token=token, filter="toplevel",
                  order="reverse_chronological", limit=50,
                  fields="id,message,created_time,permalink_url,from{id,name},comments.limit(10){from{id}}")
    return d.get("data") or []


def lade(neu_laden: bool = False) -> dict:
    """Kommentare der letzten Tage: offen zuerst. {"kommentare": [...], "offen": n, "fehler": [...]}"""
    if not neu_laden and _CACHE.get("zeit") and time.time() - _CACHE["zeit"] < CACHE_S:
        return _CACHE["daten"]
    seite, token = _seite_und_token()
    seit = datetime.now(himmel.WIEN) - timedelta(days=TAGE)
    liste, fehler = [], []
    for e in db.lade_gepostete("facebook", seit, limit=MAX_BEITRAEGE):
        if e.get("art") == "story":
            continue
        try:
            roh = _kommentare_von(str(e["extern_id"]), token)
        except Exception as ex:  # noqa: BLE001
            fehler.append(f"{e.get('titel') or e['post_id']}: {str(ex)[:160]}")
            continue
        for k in roh:
            von = k.get("from") or {}
            if str(von.get("id") or "") == seite:
                continue                                          # eigener Kommentar der Seite
            text = (k.get("message") or "").strip()
            beantwortet = any(str((a.get("from") or {}).get("id") or "") == seite
                              for a in ((k.get("comments") or {}).get("data") or []))
            liste.append({"id": k["id"], "post_id": e["post_id"], "post_titel": e.get("titel"), "sprache": e.get("sprache"),
                          "von": (von.get("name") or "").strip(), "text": text, "zeit": k.get("created_time"),
                          "link": k.get("permalink_url") or e.get("url"), "beantwortet": beantwortet})
    staende = db.lade_kommentar_staende([k["id"] for k in liste])
    for k in liste:
        st = staende.get(k["id"]) or {}
        k["status"] = "erledigt" if k["beantwortet"] else st.get("status") or "offen"
        k["vorschlag"] = st.get("vorschlag")
    offen = [k for k in liste if k["status"] == "offen"]
    rest = [k for k in liste if k["status"] != "offen"]
    offen.sort(key=lambda k: k.get("zeit") or "", reverse=True)
    rest.sort(key=lambda k: k.get("zeit") or "", reverse=True)
    daten = {"kommentare": offen + rest[:30], "offen": len(offen), "fehler": fehler}
    _CACHE.update(zeit=time.time(), daten=daten)
    return daten


def vorschlaege(ids: list[str]) -> dict:
    """Antwort-Vorschlaege fuer bis zu 10 Kommentare in EINEM Claude-Aufruf; gemerkt, damit nichts doppelt kostet."""
    from claude import frage_json
    alle = {k["id"]: k for k in lade().get("kommentare", [])}
    gesucht = [alle[i] for i in ids if i in alle and not alle[i].get("vorschlag")][:10]
    if gesucht:
        bloecke = []
        for k in gesucht:
            vorname = (k.get("von") or "").split(" ")[-1] if (k.get("sprache") or "") == "hu" else (k.get("von") or "").split(" ")[0]
            bloecke.append(f"id: {k['id']}\nName: {k.get('von') or 'unbekannt'} (Vorname vermutlich: {vorname})\n"
                           f"Beitrag: {k.get('post_titel') or ''}\nKommentar: {k.get('text') or '(nur Bild/Sticker)'}")
        d = frage_json(SYSTEM, "Schlage Antworten vor für diese Kommentare:\n\n" + "\n\n---\n\n".join(bloecke),
                       SCHEMA, effort="low", max_tokens=6000)
        for a in d.get("antworten") or []:
            if a.get("id") in alle:
                v = {"art": a.get("art"), "hinweis": a.get("hinweis") or "",
                     "vorschlaege": [x.strip() for x in (a.get("vorschlaege") or []) if x and x.strip()][:3]}
                db.setze_kommentar(a["id"], alle[a["id"]]["post_id"], vorschlag=v)
                alle[a["id"]]["vorschlag"] = v
    return {"kommentare": [alle[i] for i in ids if i in alle]}


def erledigt(kid: str, ja: bool = True) -> None:
    db.setze_kommentar(kid, status="erledigt" if ja else "offen")
    leeren()
