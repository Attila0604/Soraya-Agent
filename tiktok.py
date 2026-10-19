"""
Anbindung an TikTok (Content Posting API) -- nur Reels (Videos)

Zwei Arten, beide nur, wenn du TikTok im Dashboard einschaltest:
- "entwurf": Das Video landet als Entwurf in deiner TikTok-App (Benachrichtigung im Posteingang).
  Dort waehlst du Ton/Sound und tippst auf Posten. Geht ohne Pruefung durch TikTok.
- "direkt":  Soraya veroeffentlicht selbst. Oeffentlich sichtbar erst, wenn TikTok die App geprueft
  hat (Audit) -- vorher erlaubt TikTok nur "Nur ich" (privat).

Railway-Variablen (aus developers.tiktok.com, nie in den Chat kopieren):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET

Zugang: 24 Stunden, wird mit dem Refresh-Token (ein Jahr) automatisch erneuert.
Die Zugaenge liegen in der Datenbank (soraya_einstellungen) und gehen nie ans Dashboard.
"""

from __future__ import annotations

import os
import secrets
import time
from urllib.parse import urlencode

import requests

import db
import meta

TIMEOUT = 60
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.upload,video.publish"
SCHLUESSEL = "tiktok_zugang"


class TikTokFehler(RuntimeError):
    pass


def eingerichtet() -> bool:
    return bool(os.environ.get("TIKTOK_CLIENT_KEY") and os.environ.get("TIKTOK_CLIENT_SECRET"))


def rueckruf_url() -> str:
    return f"{meta.basis_url()}/tiktok/rueckruf"


def _antwort(r: requests.Response) -> dict:
    try:
        daten = r.json()
    except ValueError:
        daten = {}
    fehler = (daten or {}).get("error")
    code = fehler.get("code") if isinstance(fehler, dict) else fehler
    if r.status_code >= 400 or (code and code != "ok"):
        text = (fehler.get("message") if isinstance(fehler, dict) else None) or \
            daten.get("error_description") or r.text[:300]
        if code in ("access_token_invalid", "invalid_grant") or r.status_code == 401:
            text = "Zugang abgelaufen oder entzogen – bitte im Dashboard neu verbinden. (" + str(text) + ")"
        if code == "unaudited_client_can_only_post_to_private_accounts":
            text = ("TikTok erlaubt Direkt-Posten erst nach der App-Prüfung. Bis dahin: TikTok auf "
                    "„Als Entwurf“ stellen. (" + str(text) + ")")
        raise TikTokFehler(f"TikTok: {text}"[:400])
    return daten


def anmelde_url() -> str:
    if not eingerichtet():
        raise TikTokFehler("Die TikTok-App ist in Railway noch nicht eingetragen (TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET).")
    state = f"tiktok.{int(time.time())}.{secrets.token_urlsafe(12)}"
    state += "." + meta.signiere(state)
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "scope": SCOPES, "response_type": "code",
        "redirect_uri": rueckruf_url(), "state": state})


def _token(**daten) -> dict:
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"], "client_secret": os.environ["TIKTOK_CLIENT_SECRET"], **daten},
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=TIMEOUT)
    return _antwort(r)


def _merken(t: dict, alt: dict | None = None) -> dict:
    jetzt = int(time.time())
    z = dict(alt or {})
    z.update(token=t["access_token"], laeuft_ab=jetzt + int(t.get("expires_in") or 86400),
             refresh=t.get("refresh_token") or z.get("refresh"),
             refresh_ab=jetzt + int(t.get("refresh_expires_in") or 31536000),
             open_id=t.get("open_id") or z.get("open_id"))
    return z


def verbinde(code: str) -> dict:
    t = _token(code=code, grant_type="authorization_code", redirect_uri=rueckruf_url())
    z = _merken(t)
    try:
        ich = _get_mit(z["token"], "/user/info/", fields="open_id,display_name")
        z["name"] = ((ich.get("data") or {}).get("user") or {}).get("display_name")
    except Exception:  # noqa: BLE001 -- der Name ist nur fuers Dashboard
        pass
    z["verbunden"] = int(time.time())
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
    return {"eingerichtet": eingerichtet(), "verbunden": bool(z.get("token")), "name": z.get("name"),
            "rueckruf_url": rueckruf_url()}


def gueltiger_token() -> str:
    """Zugang holen und rechtzeitig (eine Stunde vorher) erneuern."""
    z = zugang()
    if not z or not z.get("token"):
        raise TikTokFehler("TikTok ist nicht verbunden.")
    if z.get("laeuft_ab", 0) - time.time() < 3600:
        if not z.get("refresh"):
            raise TikTokFehler("TikTok-Zugang abgelaufen – bitte im Dashboard neu verbinden.")
        z = _merken(_token(grant_type="refresh_token", refresh_token=z["refresh"]), z)
        db.setze_einstellung(SCHLUESSEL, z)
    return z["token"]


def _get_mit(token: str, pfad: str, **params) -> dict:
    return _antwort(requests.get(API + pfad, params=params, headers={"Authorization": f"Bearer {token}"},
                                 timeout=TIMEOUT))


def _post_mit(token: str, pfad: str, json: dict) -> dict:
    return _antwort(requests.post(API + pfad, json=json, timeout=TIMEOUT, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}))


def _hochladen(upload_url: str, video: bytes) -> None:
    r = requests.put(upload_url, data=video, timeout=TIMEOUT * 5, headers={
        "Content-Type": "video/mp4", "Content-Length": str(len(video)),
        "Content-Range": f"bytes 0-{len(video) - 1}/{len(video)}"})
    if r.status_code >= 400:
        raise TikTokFehler(f"TikTok: Hochladen fehlgeschlagen ({r.status_code}).")


def _quelle(video: bytes) -> dict:
    # ein einziges Stueck (unsere Reels sind klein, deutlich unter 64 MB)
    return {"source": "FILE_UPLOAD", "video_size": len(video), "chunk_size": len(video), "total_chunk_count": 1}


def poste_video(video: bytes, titel: str, modus: str = "entwurf") -> dict:
    """modus "entwurf": in den TikTok-Posteingang; "direkt": selbst veroeffentlichen.
    Rueckgabe: {"id": publish_id, "url": None}"""
    token = gueltiger_token()
    if modus == "direkt":
        info = (_post_mit(token, "/post/publish/creator_info/query/", {}).get("data") or {})
        stufen = info.get("privacy_level_options") or ["SELF_ONLY"]
        sicht = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in stufen else stufen[0]
        start = _post_mit(token, "/post/publish/video/init/", {
            "post_info": {"title": titel[:2200], "privacy_level": sicht, "disable_comment": False,
                          "disable_duet": False, "disable_stitch": False},
            "source_info": _quelle(video)})
    else:
        start = _post_mit(token, "/post/publish/inbox/video/init/", {"source_info": _quelle(video)})
    d = start.get("data") or {}
    if not d.get("upload_url"):
        raise TikTokFehler("TikTok hat keine Upload-Adresse geliefert.")
    _hochladen(d["upload_url"], video)
    return {"id": d.get("publish_id"), "url": None}
