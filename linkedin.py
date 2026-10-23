"""
Anbindung an LinkedIn -- Posts auf dein PERSOENLICHES Profil

Eigene LinkedIn-App mit den zwei Self-Service-Produkten (ohne Pruefung, sofort freigeschaltet):
- "Sign In with LinkedIn using OpenID Connect"  -> Rechte openid, profile (wer bist du: urn:li:person:<sub>)
- "Share on LinkedIn"                           -> Recht w_member_social (in deinem Namen posten)

Was wohin geht:
- Feed-Post: Bild mit Text (Karussell: alle Bilder als Mehrbild-Beitrag, sonst das Titelbild)
- Reel: das Video (Videos API); klappt das nicht, das Titelbild mit dem Text
- Storys gibt es auf LinkedIn nicht -- die gehen dort nicht hin

Zugang: 60 Tage, ohne Refresh-Token (den gibt es nur fuer gepruefte Partner). Das Dashboard warnt
7 Tage vorher: "LinkedIn neu verbinden" (ein Klick, du bist meist noch angemeldet).

Railway-Variablen (aus linkedin.com/developers, nie in den Chat kopieren):
  LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
  LINKEDIN_VERSION   optional (JJJJMM), sonst automatisch ein aktueller Monat
Rueckruf-Adresse: <Agent>/linkedin/rueckruf
"""

from __future__ import annotations

import os
import re
import secrets
import time
from datetime import date
from urllib.parse import quote, urlencode

import requests

import db
import meta

TIMEOUT = 60
AUTH = "https://www.linkedin.com/oauth/v2"
API = "https://api.linkedin.com"
SCOPES = "openid profile w_member_social"
SCHLUESSEL = "linkedin_zugang"
WARNEN_TAGE = 7


class LinkedInFehler(RuntimeError):
    pass


def eingerichtet() -> bool:
    return bool(os.environ.get("LINKEDIN_CLIENT_ID") and os.environ.get("LINKEDIN_CLIENT_SECRET"))


def rueckruf_url() -> str:
    return f"{meta.basis_url()}/linkedin/rueckruf"


# ---------------------------------------------------------------------------
# Version der LinkedIn-Schnittstelle (JJJJMM). LinkedIn haelt jede Version etwa ein Jahr. Ohne Vorgabe
# nehmen wir den vorletzten Monat; meldet LinkedIn "gibt es nicht (mehr)", wird ein Monat davor probiert.
# ---------------------------------------------------------------------------
def _monat_minus(jjjjmm: str, n: int) -> str:
    j, m = int(jjjjmm[:4]), int(jjjjmm[4:6])
    m -= n
    while m < 1:
        m += 12
        j -= 1
    return f"{j:04d}{m:02d}"


def versionen(heute: date | None = None) -> list[str]:
    eigene = (os.environ.get("LINKEDIN_VERSION") or "").strip()
    if re.fullmatch(r"\d{6}", eigene):
        return [eigene]
    heute = heute or date.today()
    start = _monat_minus(f"{heute.year:04d}{heute.month:02d}", 2)
    return [_monat_minus(start, i) for i in range(4)]


_VERSION = {"gut": None}


def _ist_versionsfehler(r: requests.Response) -> bool:
    if r.status_code not in (400, 426):
        return False
    t = (r.text or "").upper()
    return "VERSION" in t and ("NONEXISTENT" in t or "NOT ACTIVE" in t or "DEPRECATED" in t or "SUNSET" in t
                               or "INVALID" in t)


def _antwort(r: requests.Response) -> dict:
    try:
        daten = r.json() if r.content else {}
    except ValueError:
        daten = {}
    if r.status_code >= 400:
        text = (daten.get("message") or daten.get("error_description") or daten.get("error")
                or (r.text or "")[:300]) if isinstance(daten, dict) else (r.text or "")[:300]
        if r.status_code == 401 or "expired" in str(text).lower() or "revoked" in str(text).lower():
            text = "Zugang abgelaufen oder entzogen – bitte im Dashboard „LinkedIn neu verbinden“. (" + str(text) + ")"
        elif r.status_code == 403:
            text = ("LinkedIn erlaubt das nicht – ist in der LinkedIn-App das Produkt „Share on LinkedIn“ "
                    "hinzugefügt? (" + str(text) + ")")
        elif r.status_code == 429:
            text = "Zu viele Anfragen an LinkedIn – nächster Versuch später. (" + str(text) + ")"
        raise LinkedInFehler(f"LinkedIn: {text}"[:400])
    return daten if isinstance(daten, dict) else {}


def _rest(methode: str, pfad: str, token: str, **kw) -> requests.Response:
    """Aufruf der versionierten REST-Schnittstelle (/rest/...), mit Rueckfall auf aeltere Versionen."""
    liste = [_VERSION["gut"]] if _VERSION["gut"] else versionen()
    letzte = None
    for v in liste:
        r = requests.request(methode, API + pfad, timeout=TIMEOUT * 2, headers={
            "Authorization": f"Bearer {token}", "LinkedIn-Version": v, "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"}, **kw)
        if _ist_versionsfehler(r):
            letzte = r
            continue
        _VERSION["gut"] = v
        return r
    _VERSION["gut"] = None
    return letzte


# ---------------------------------------------------------------------------
# Verbinden
# ---------------------------------------------------------------------------
def anmelde_url() -> str:
    if not eingerichtet():
        raise LinkedInFehler("Die LinkedIn-App ist in Railway noch nicht eingetragen "
                             "(LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET).")
    state = f"linkedin.{int(time.time())}.{secrets.token_urlsafe(12)}"
    state += "." + meta.signiere(state)
    return f"{AUTH}/authorization?" + urlencode({
        "response_type": "code", "client_id": os.environ["LINKEDIN_CLIENT_ID"], "redirect_uri": rueckruf_url(),
        "state": state, "scope": SCOPES})


def verbinde(code: str) -> dict:
    r = requests.post(f"{AUTH}/accessToken", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": rueckruf_url(),
        "client_id": os.environ["LINKEDIN_CLIENT_ID"], "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    t = _antwort(r)
    if not t.get("access_token"):
        raise LinkedInFehler("LinkedIn hat keinen Zugang geliefert – bitte noch einmal verbinden.")
    ich = _antwort(requests.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {t['access_token']}"},
                                timeout=TIMEOUT))
    if not ich.get("sub"):
        raise LinkedInFehler("LinkedIn hat keine Profil-ID geliefert (Produkt „Sign In with LinkedIn using "
                             "OpenID Connect“ hinzugefügt?).")
    jetzt = int(time.time())
    rechte = str(t.get("scope") or "").replace(",", " ").split()
    z = {"token": t["access_token"], "laeuft_ab": jetzt + int(t.get("expires_in") or 5184000),
         "autor": f"urn:li:person:{ich['sub']}", "name": ich.get("name") or ich.get("given_name"),
         "verbunden": jetzt, "rechte": rechte or None}
    if t.get("refresh_token"):           # nur fuer gepruefte Partner -- wenn es kommt, nutzen wir es
        z.update(refresh=t["refresh_token"], refresh_ab=jetzt + int(t.get("refresh_token_expires_in") or 31536000))
    if rechte and "w_member_social" not in rechte:
        raise LinkedInFehler("LinkedIn hat das Recht zum Posten (w_member_social) nicht freigegeben. Bitte in der "
                             "LinkedIn-App das Produkt „Share on LinkedIn“ hinzufügen und neu verbinden.")
    db.setze_einstellung(SCHLUESSEL, z)
    return {"name": z["name"]}


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
    ab = z.get("laeuft_ab")
    rest = (ab - time.time()) / 86400 if ab else None
    return {"eingerichtet": eingerichtet(), "verbunden": bool(z.get("token")) and (rest is None or rest > 0),
            "name": z.get("name"), "laeuft_ab": ab, "rueckruf_url": rueckruf_url(),
            "abgelaufen": bool(z.get("token")) and rest is not None and rest <= 0,
            "bald_ablaufend": bool(z.get("token")) and rest is not None and 0 < rest <= WARNEN_TAGE,
            "selbst_verlaengert": bool(z.get("refresh"))}


def gueltiger_token() -> dict:
    z = zugang()
    if not z or not z.get("token"):
        raise LinkedInFehler("LinkedIn ist nicht verbunden.")
    if z.get("laeuft_ab", 0) - time.time() < 3600:
        if z.get("refresh") and z.get("refresh_ab", 0) > time.time():
            t = _antwort(requests.post(f"{AUTH}/accessToken", data={
                "grant_type": "refresh_token", "refresh_token": z["refresh"],
                "client_id": os.environ.get("LINKEDIN_CLIENT_ID", ""),
                "client_secret": os.environ.get("LINKEDIN_CLIENT_SECRET", "")}, timeout=TIMEOUT))
            z.update(token=t["access_token"], laeuft_ab=int(time.time()) + int(t.get("expires_in") or 5184000),
                     refresh=t.get("refresh_token") or z["refresh"])
            db.setze_einstellung(SCHLUESSEL, z)
        else:
            raise LinkedInFehler("LinkedIn-Zugang abgelaufen (60 Tage) – bitte im Dashboard „LinkedIn neu verbinden“.")
    return z


# ---------------------------------------------------------------------------
# Text: LinkedIn liest den Beitragstext im Format "little text" -- Zeichen wie ( ) # _ * muessen mit
# Backslash geschuetzt werden, sonst schneidet LinkedIn den Text ab. Hashtags bekommen die Vorlage.
# ---------------------------------------------------------------------------
_RESERVIERT = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_URL = re.compile(r"https?://\S+")


def little_text(text: str) -> str:
    teile, pos = [], 0
    for m in _URL.finditer(text):
        teile.append(_RESERVIERT.sub(r"\\\1", text[pos:m.start()]))
        teile.append(m.group(0))
        pos = m.end()
    teile.append(_RESERVIERT.sub(r"\\\1", text[pos:]))
    aus = "".join(teile)
    # "\#Tag" -> Hashtag-Vorlage, damit LinkedIn ihn als anklickbaren Hashtag zeigt
    return re.sub(r"\\#(?=[^\W\d_])([^\s\\#]+)", lambda m: "{hashtag|\\#|" + m.group(1) + "}", aus)


# ---------------------------------------------------------------------------
# Hochladen
# ---------------------------------------------------------------------------
def _bild_hochladen(z: dict, bild: bytes) -> str:
    r = _antwort(_rest("POST", "/rest/images?action=initializeUpload", z["token"],
                       json={"initializeUploadRequest": {"owner": z["autor"]}}))
    v = r.get("value") or {}
    if not v.get("uploadUrl") or not v.get("image"):
        raise LinkedInFehler("LinkedIn hat keine Upload-Adresse für das Bild geliefert.")
    up = requests.put(v["uploadUrl"], data=bild, timeout=TIMEOUT * 2,
                      headers={"Authorization": f"Bearer {z['token']}", "Content-Type": "image/jpeg"})
    if up.status_code >= 400:
        raise LinkedInFehler(f"LinkedIn: Bild hochladen fehlgeschlagen ({up.status_code}).")
    return v["image"]


def _video_hochladen(z: dict, video: bytes, warten_s: int = 180) -> str:
    r = _antwort(_rest("POST", "/rest/videos?action=initializeUpload", z["token"], json={"initializeUploadRequest": {
        "owner": z["autor"], "fileSizeBytes": len(video), "uploadCaptions": False, "uploadThumbnail": False}}))
    v = r.get("value") or {}
    urn, teile = v.get("video"), v.get("uploadInstructions") or []
    if not urn or not teile:
        raise LinkedInFehler("LinkedIn hat keine Upload-Adresse für das Video geliefert.")
    etags = []
    for t in teile:
        a, b = int(t.get("firstByte", 0)), int(t.get("lastByte", len(video) - 1))
        up = requests.put(t["uploadUrl"], data=video[a:b + 1], timeout=TIMEOUT * 5,
                          headers={"Content-Type": "application/octet-stream"})
        if up.status_code >= 400:
            raise LinkedInFehler(f"LinkedIn: Video hochladen fehlgeschlagen ({up.status_code}).")
        etags.append(up.headers.get("etag") or up.headers.get("ETag") or "")
    _antwort(_rest("POST", "/rest/videos?action=finalizeUpload", z["token"], json={"finalizeUploadRequest": {
        "video": urn, "uploadToken": v.get("uploadToken") or "", "uploadedPartIds": etags}}))
    ende = time.time() + warten_s
    while True:          # erst posten, wenn LinkedIn das Video verarbeitet hat
        st = _antwort(_rest("GET", "/rest/videos/" + quote(urn, safe=""), z["token"])).get("status")
        if st == "AVAILABLE":
            return urn
        if st == "PROCESSING_FAILED":
            raise LinkedInFehler("LinkedIn konnte das Video nicht verarbeiten.")
        if time.time() > ende:
            raise LinkedInFehler("LinkedIn verarbeitet das Video noch zu lange.")
        time.sleep(5)


def _beitrag(z: dict, text: str, inhalt: dict | None) -> dict:
    body = {"author": z["autor"], "commentary": little_text(text), "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    if inhalt:
        body["content"] = inhalt
    r = _rest("POST", "/rest/posts", z["token"], json=body)
    _antwort(r)
    urn = r.headers.get("x-restli-id") or r.headers.get("X-RestLi-Id") or ""
    return {"id": urn, "url": f"https://www.linkedin.com/feed/update/{urn}/" if urn else None}


def poste(art: str, text: str, bild: bytes | None = None, bilder: list[bytes] | None = None,
          video: bytes | None = None, alt: str = "", video_warten_s: int = 180) -> dict:
    """art: post (Bild; mit mehreren `bilder` als Mehrbild-Beitrag) oder reel (Video, sonst Titelbild).
    Rueckgabe: {"id": Beitrags-URN, "url"}"""
    if art == "story":
        raise ValueError("Storys gibt es auf LinkedIn nicht.")
    z = gueltiger_token()
    alt = (alt or "Soraya")[:300]
    if art == "reel" and video:
        try:
            return _beitrag(z, text, {"media": {"id": _video_hochladen(z, video, video_warten_s), "title": alt[:200]}})
        except LinkedInFehler as ex:
            if "abgelaufen" in str(ex) or not bild:
                raise
            print(f"[LinkedIn] Video ging nicht ({ex}) – poste das Titelbild.", flush=True)
    if bilder and len(bilder) > 1:
        urns = [_bild_hochladen(z, b) for b in bilder[:20]]
        return _beitrag(z, text, {"multiImage": {"images": [{"id": u, "altText": alt} for u in urns]}})
    daten = bild or (bilder or [None])[0]
    if not daten:
        return _beitrag(z, text, None)
    return _beitrag(z, text, {"media": {"id": _bild_hochladen(z, daten), "altText": alt}})
