"""
Anbindung an Pinterest -- Pins auf das Unternehmenskonto von Soraya

Pinterest ist eine Bildersuchmaschine: ein Pin wird monatelang gefunden, und der Link ist antippbar. Darum
geht jeder Feed-Post (Titelbild) und jede Story (Hochformat) als Pin auf eine Pinnwand je Sprache, mit
Link auf die Landingpage (?q=p<id>&lang=) -- bei Posts zu einem Sternzeichen direkt auf dessen Zeichen-Seite.
Reels gehen (noch) nicht hin: Video-Pins brauchen einen eigenen Hochlade-Weg.

Eigene Pinterest-App (developers.pinterest.com, kostenlos). Neue Apps haben zuerst "Trial access": dann geht
alles nur in der Sandbox (Pins sind nicht oeffentlich). Fuer echte Pins "Standard access" beantragen (ein kurzes
Video der Verbindung zeigen). Solange: Railway PINTEREST_SANDBOX=1.

Zugang: 30 Tage, verlaengert sich selbst mit dem Refresh-Token (1 Jahr).

Railway-Variablen (nie in den Chat kopieren):
  PINTEREST_APP_ID, PINTEREST_APP_SECRET, optional PINTEREST_SANDBOX=1
  Im Testmodus nimmt die Sandbox den Zugang aus "Verbinden" nicht an ("Authentication failed"): dafuer auf
  developers.pinterest.com bei der App "Generate token" mit "Sandbox" erzeugen -> PINTEREST_SANDBOX_TOKEN.
Rueckruf-Adresse: <Agent>/pinterest/rueckruf
"""

from __future__ import annotations

import base64
import os
import secrets
import time
from urllib.parse import urlencode

import requests

import db
import medien
import meta

TIMEOUT = 60
AUTH = "https://www.pinterest.com/oauth/"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
SCHLUESSEL = "pinterest_zugang"
PINNWAENDE = {"de": "Astrologie & Horoskop", "en": "Astrology & Horoscope", "hu": "Asztrológia és horoszkóp",
              "it": "Astrologia e oroscopo"}
PINNWAND_TEXT = {"de": "Tageshoroskop, Mondphasen und Sternzeichen – von Soraya, Luxury Astro Guide.",
                 "en": "Daily horoscope, moon phases and zodiac signs – by Soraya, Luxury Astro Guide.",
                 "hu": "Napi horoszkóp, holdfázisok és csillagjegyek – Soraya, Luxury Astro Guide.",
                 "it": "Oroscopo del giorno, fasi lunari e segni zodiacali – da Soraya, Luxury Astro Guide."}
# Sternzeichen-Seiten der Landingpage (Reihenfolge wie medien.ZEICHEN_GLYPHE)
ZEICHEN_SEITEN = {
    "de": ("sternzeichen", ["widder", "stier", "zwillinge", "krebs", "loewe", "jungfrau", "waage", "skorpion",
                            "schuetze", "steinbock", "wassermann", "fische"]),
    "en": ("en/zodiac", ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius",
                         "capricorn", "aquarius", "pisces"]),
    "hu": ("hu/csillagjegyek", ["kos", "bika", "ikrek", "rak", "oroszlan", "szuz", "merleg", "skorpio", "nyilas", "bak",
                                "vizonto", "halak"]),
    "it": ("it/segni-zodiacali", ["ariete", "toro", "gemelli", "cancro", "leone", "vergine", "bilancia", "scorpione",
                                  "sagittario", "capricorno", "acquario", "pesci"]),
}


class PinterestFehler(RuntimeError):
    pass


def eingerichtet() -> bool:
    return bool(os.environ.get("PINTEREST_APP_ID") and os.environ.get("PINTEREST_APP_SECRET"))


def sandbox() -> bool:
    return (os.environ.get("PINTEREST_SANDBOX") or "").strip() in ("1", "ja", "true")


def sandbox_token() -> str:
    return (os.environ.get("PINTEREST_SANDBOX_TOKEN") or "").strip()


def _pinnwand_schluessel() -> str:
    # Pinnwaende der Sandbox gibt es im echten Pinterest nicht (und umgekehrt)
    return "pinnwaende_sandbox" if sandbox() else "pinnwaende"


def api() -> str:
    return "https://api-sandbox.pinterest.com/v5" if sandbox() else "https://api.pinterest.com/v5"


def rueckruf_url() -> str:
    return f"{meta.basis_url()}/pinterest/rueckruf"


def _antwort(r: requests.Response) -> dict:
    try:
        daten = r.json() if r.content else {}
    except ValueError:
        daten = {}
    if r.status_code >= 400:
        text = (daten.get("message") or daten.get("error_description") or daten.get("error")
                or (r.text or "")[:300]) if isinstance(daten, dict) else (r.text or "")[:300]
        if r.status_code == 401 and sandbox():
            text = ("Der Testmodus braucht einen eigenen Sandbox-Schlüssel: auf developers.pinterest.com bei der App "
                    "„Generate token“ mit „Sandbox“ erzeugen und in Railway als PINTEREST_SANDBOX_TOKEN eintragen. (" + str(text) + ")")
        elif r.status_code == 401:
            text = "Zugang abgelaufen oder entzogen – bitte im Dashboard „Pinterest neu verbinden“. (" + str(text) + ")"
        elif r.status_code == 403 and not sandbox():
            text = ("Pinterest erlaubt das (noch) nicht – hat die App schon „Standard access“? Bis dahin in Railway "
                    "PINTEREST_SANDBOX=1 setzen. (" + str(text) + ")")
        elif r.status_code == 429:
            text = "Zu viele Anfragen an Pinterest – nächster Versuch später. (" + str(text) + ")"
        raise PinterestFehler(f"Pinterest: {text}"[:400])
    return daten if isinstance(daten, dict) else {}


def _basic() -> str:
    roh = f"{os.environ.get('PINTEREST_APP_ID', '')}:{os.environ.get('PINTEREST_APP_SECRET', '')}"
    return "Basic " + base64.b64encode(roh.encode()).decode()


# ---------------------------------------------------------------------------
# Verbinden
# ---------------------------------------------------------------------------
def anmelde_url() -> str:
    if not eingerichtet():
        raise PinterestFehler("Die Pinterest-App ist in Railway noch nicht eingetragen (PINTEREST_APP_ID / PINTEREST_APP_SECRET).")
    state = f"pinterest.{int(time.time())}.{secrets.token_urlsafe(12)}"
    state += "." + meta.signiere(state)
    return AUTH + "?" + urlencode({"client_id": os.environ["PINTEREST_APP_ID"], "redirect_uri": rueckruf_url(),
                                   "response_type": "code", "scope": SCOPES, "state": state})


def _token(daten: dict) -> dict:
    # die Token-Adresse gibt es nur auf api.pinterest.com (auch fuer die Sandbox)
    return _antwort(requests.post("https://api.pinterest.com/v5/oauth/token", data=daten, timeout=TIMEOUT,
                                  headers={"Authorization": _basic(), "Content-Type": "application/x-www-form-urlencoded"}))


def verbinde(code: str) -> dict:
    t = _token({"grant_type": "authorization_code", "code": code, "redirect_uri": rueckruf_url()})
    if not t.get("access_token"):
        raise PinterestFehler("Pinterest hat keinen Zugang geliefert – bitte noch einmal verbinden.")
    jetzt = int(time.time())
    z = {"token": t["access_token"], "laeuft_ab": jetzt + int(t.get("expires_in") or 2592000),
         "refresh": t.get("refresh_token"), "refresh_ab": jetzt + int(t.get("refresh_token_expires_in") or 31536000),
         "verbunden": jetzt, "rechte": str(t.get("scope") or "").replace(",", " ").split() or None, "pinnwaende": {}}
    try:
        ich = _get("/user_account", z["token"], basis="https://api.pinterest.com/v5")   # Lesen geht auch im Testmodus
        z["name"] = ich.get("username") or ich.get("business_name")
        z["konto_art"] = ich.get("account_type")
    except PinterestFehler:
        z["name"] = None
    db.setze_einstellung(SCHLUESSEL, z)
    return {"name": z.get("name")}


def trennen() -> None:
    db.setze_einstellung(SCHLUESSEL, {})


def zugang() -> dict | None:
    try:
        return db.lade_einstellung(SCHLUESSEL, None)
    except Exception:
        return None


def verbindung() -> dict:
    """Fuers Dashboard -- ohne Zugangsschluessel."""
    z = zugang() or {}
    refresh_ok = bool(z.get("refresh")) and z.get("refresh_ab", 0) > time.time()
    abgelaufen = bool(z.get("token")) and z.get("laeuft_ab", 0) < time.time() and not refresh_ok
    return {"eingerichtet": eingerichtet(), "verbunden": bool(z.get("token")) and not abgelaufen,
            "name": z.get("name"), "konto_art": z.get("konto_art"), "laeuft_ab": z.get("refresh_ab") if refresh_ok else z.get("laeuft_ab"),
            "rueckruf_url": rueckruf_url(), "abgelaufen": abgelaufen, "sandbox": sandbox(), "selbst_verlaengert": refresh_ok,
            "sandbox_schluessel": bool(sandbox_token()) if sandbox() else None}


def gueltiger_token() -> str:
    z = zugang()
    if not z or not z.get("token"):
        raise PinterestFehler("Pinterest ist nicht verbunden.")
    if sandbox():
        if not sandbox_token():
            raise PinterestFehler("Pinterest-Testmodus: Es fehlt der Sandbox-Schlüssel – auf developers.pinterest.com bei der App "
                                  "„Generate token“ mit „Sandbox“ erzeugen und in Railway als PINTEREST_SANDBOX_TOKEN eintragen.")
        return sandbox_token()
    if z.get("laeuft_ab", 0) - time.time() < 86400 and z.get("refresh") and z.get("refresh_ab", 0) > time.time():
        t = _token({"grant_type": "refresh_token", "refresh_token": z["refresh"]})
        jetzt = int(time.time())
        z.update(token=t["access_token"], laeuft_ab=jetzt + int(t.get("expires_in") or 2592000))
        if t.get("refresh_token"):
            z.update(refresh=t["refresh_token"], refresh_ab=jetzt + int(t.get("refresh_token_expires_in") or 31536000))
        db.setze_einstellung(SCHLUESSEL, z)
    return z["token"]


def _get(pfad: str, token: str, basis: str | None = None, **params) -> dict:
    return _antwort(requests.get((basis or api()) + pfad, params=params, timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}"}))


def _post(pfad: str, token: str, daten: dict) -> dict:
    return _antwort(requests.post(api() + pfad, json=daten, timeout=TIMEOUT * 2,
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}))


# ---------------------------------------------------------------------------
# Pinnwand je Sprache und Pins
# ---------------------------------------------------------------------------
def pinnwand(sprache: str, token: str | None = None, ohne: set[str] | None = None) -> str:
    """ID der Pinnwand fuer die Sprache -- vorhandene (gleicher Name) nutzen, sonst anlegen und merken.
    ohne: Pinnwaende, die nicht gehen (z. B. noch aus dem Testmodus) -> dann eine neue anlegen."""
    token = token or gueltiger_token()
    ohne = ohne or set()
    z = zugang() or {}
    gemerkt = (z.get(_pinnwand_schluessel()) or {}).get(sprache)
    if gemerkt and gemerkt not in ohne:
        return gemerkt
    name = PINNWAENDE.get(sprache, PINNWAENDE["en"])
    vorhanden = next((b for b in (_get("/boards", token, page_size=100).get("items") or [])
                      if b.get("name") == name and b.get("id") not in ohne), None)
    if not vorhanden:
        neu = {"name": name, "description": PINNWAND_TEXT.get(sprache, PINNWAND_TEXT["en"]), "privacy": "PUBLIC"}
        try:
            vorhanden = _post("/boards", token, neu)
        except PinterestFehler:
            if not ohne:
                raise
            vorhanden = _post("/boards", token, {**neu, "name": f"{name} ✦"})     # alter Name noch belegt
    bid = vorhanden["id"]
    z = zugang() or {}
    z.setdefault(_pinnwand_schluessel(), {})[sprache] = bid
    db.setze_einstellung(SCHLUESSEL, z)
    return bid


def ziel_link(post: dict, basis: str) -> str:
    """Wohin der Pin fuehrt: Zeichen-Seite, wenn der Post von einem Sternzeichen handelt, sonst die Landingpage."""
    sprache = (post.get("sprache") or "en")[:2]
    st = medien.stil(post)
    idx = st.get("zeichen")
    if idx is None:
        idx = medien.zeichen_aus_text(post.get("titel"))
    q = f"q=p{post['id']}&lang={sprache}"
    if idx is not None and sprache in ZEICHEN_SEITEN:
        pfad, slugs = ZEICHEN_SEITEN[sprache]
        return f"{basis.rstrip('/')}/{pfad}/{slugs[idx]}?{q}"
    return f"{basis}?{q}"


def poste_pin(bild: bytes, titel: str, beschreibung: str, link: str, sprache: str, alt: str | None = None) -> dict:
    token = gueltiger_token()
    daten = {"board_id": pinnwand(sprache, token), "title": (titel or "Soraya")[:100], "description": beschreibung[:500],
             "link": link, "alt_text": (alt or titel or "Soraya")[:500],
             "media_source": {"source_type": "image_base64", "content_type": "image/jpeg",
                              "data": base64.b64encode(bild).decode()}}
    try:
        pin = _post("/pins", token, daten)
    except PinterestFehler as ex:
        if "sandbox board" not in str(ex).lower():
            raise
        # nach "Standard access": die gemerkte Pinnwand stammt noch aus dem Testmodus -> neue echte anlegen, nochmal
        daten["board_id"] = pinnwand(sprache, token, ohne={daten["board_id"]})
        pin = _post("/pins", token, daten)
    pid = pin.get("id")
    return {"id": pid, "url": f"https://www.pinterest.com/pin/{pid}/" if pid and not sandbox() else None}
