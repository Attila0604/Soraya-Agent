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

Einrichtung auf developers.tiktok.com (App anlegen, Produkte "Login Kit" + "Content Posting API",
Rechte user.info.basic, video.upload, video.publish, video.list; Rueckruf-Adresse siehe rueckruf_url()).
Solange die App nicht von TikTok geprueft ist, laeuft sie im "Sandbox"-Modus: dort das eigene
TikTok-Konto als "Target User" eintragen. Hochgeladen wird die Datei selbst (FILE_UPLOAD), deshalb
ist keine Pruefung der eigenen Domain noetig.

Zahlen (Aufrufe, Gefaellt mir, Kommentare, Teilen) kommen ueber video.list -- ohne Audit.
"""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

import db
import meta

TIMEOUT = 60
API = "https://open.tiktokapis.com/v2"
# video.list (Zahlen) gibt es nur mit der "Display API", die TikTok nicht jeder App anbietet. Ohne das Recht in der
# App lehnt TikTok das Verbinden ab -> nur anfragen, wenn TIKTOK_ZAHLEN=1 in Railway gesetzt ist.
SCOPES_BASIS = "user.info.basic,video.upload,video.publish"
# TIKTOK_ZAHLEN=1: + video.list (Zahlen je Video); =2: zusaetzlich user.info.stats (Follower)
_ZAHLEN = os.environ.get("TIKTOK_ZAHLEN", "")
SCOPES = SCOPES_BASIS + (",video.list" if _ZAHLEN in ("1", "2") else "") + (",user.info.stats" if _ZAHLEN == "2" else "")
ZAHLEN_RECHT = "video.list"
# Klare deutsche Saetze fuer die haeufigsten Fehler der Content Posting API
FEHLER_TEXTE = {
    "spam_risk_too_many_pending_share": "In deiner TikTok-App warten schon 5 Entwürfe – bitte dort erst posten oder löschen.",
    "spam_risk_too_many_posts": "TikTok erlaubt heute keine weiteren Posts über die Schnittstelle (Tageslimit).",
    "spam_risk_user_banned_from_posting": "TikTok hat das Posten für dieses Konto gesperrt.",
    "reached_active_user_cap": "Die TikTok-App hat ihr Tageslimit erreicht – morgen geht es wieder.",
    "rate_limit_exceeded": "Zu viele Anfragen an TikTok – nächster Versuch später.",
    "scope_not_authorized": "Der TikTok-Zugang hat dieses Recht nicht – bitte im Dashboard neu verbinden.",
    "scope_permission_missed": "Der TikTok-Zugang hat dieses Recht nicht – bitte im Dashboard neu verbinden.",
    "privacy_level_option_mismatch": "TikTok erlaubt diese Sichtbarkeit nicht – bitte TikTok auf „Als Entwurf“ stellen.",
    "url_ownership_unverified": "TikTok verlangt eine bestätigte Domain (sollte bei Datei-Upload nicht vorkommen).",
}
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
        if code in FEHLER_TEXTE:
            text = FEHLER_TEXTE[code] + " (" + str(text) + ")"
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
    if not t.get("access_token"):
        raise TikTokFehler("TikTok hat keinen Zugang geliefert – bitte noch einmal verbinden.")
    jetzt = int(time.time())
    z = dict(alt or {})
    z.update(token=t["access_token"], laeuft_ab=jetzt + int(t.get("expires_in") or 86400),
             refresh=t.get("refresh_token") or z.get("refresh"),
             refresh_ab=jetzt + int(t.get("refresh_expires_in") or 31536000),
             open_id=t.get("open_id") or z.get("open_id"))
    if t.get("scope"):
        z["rechte"] = [x.strip() for x in str(t["scope"]).split(",") if x.strip()]
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


def zahlen_erlaubt(z: dict | None) -> bool:
    """Darf der Zugang die eigenen Videos samt Zahlen lesen (video.list)?"""
    if not z or not z.get("token") or z.get("zahlen_fehlt"):
        return False
    return ZAHLEN_RECHT in (z.get("rechte") or [])


def verbindung() -> dict:
    """Fuers Dashboard -- ohne Zugangsschluessel."""
    z = zugang() or {}
    out = {"eingerichtet": eingerichtet(), "verbunden": bool(z.get("token")), "name": z.get("name"),
           "rueckruf_url": rueckruf_url()}
    if out["verbunden"]:
        out["zahlen"] = zahlen_erlaubt(z)
        # Refresh-Token (ein Jahr) bald abgelaufen -> neu verbinden
        if z.get("refresh_ab"):
            out["laeuft_ab"] = z["refresh_ab"]
    return out


_ERNEUERN = threading.Lock()
_VERSUCHT = {"zuletzt": 0.0}


def gueltiger_token() -> str:
    """Zugang holen und rechtzeitig (eine Stunde vorher) erneuern."""
    z = zugang()
    if not z or not z.get("token"):
        raise TikTokFehler("TikTok ist nicht verbunden.")
    if z.get("laeuft_ab", 0) - time.time() < 3600:
        with _ERNEUERN:                    # Zeitplan und "Jetzt posten" nicht gleichzeitig erneuern lassen
            z = zugang() or z
            if z.get("laeuft_ab", 0) - time.time() >= 3600:
                return z["token"]
            if not z.get("refresh") or z.get("refresh_ab", time.time() + 1) < time.time():
                raise TikTokFehler("TikTok-Zugang abgelaufen – bitte im Dashboard neu verbinden.")
            z = _merken(_token(grant_type="refresh_token", refresh_token=z["refresh"]), z)
            db.setze_einstellung(SCHLUESSEL, z)
    return z["token"]


def erneuern_wenn_noetig() -> bool:
    """Laeuft im Zeitplan mit: haelt den Zugang frisch, auch wenn tagelang nichts gepostet wird."""
    z = zugang()
    if not z or not z.get("token") or z.get("laeuft_ab", 0) - time.time() >= 3600:
        return False
    if time.time() - _VERSUCHT["zuletzt"] < 900:        # klappt es nicht, hoechstens alle 15 Minuten fragen
        return False
    _VERSUCHT["zuletzt"] = time.time()
    gueltiger_token()
    return True


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


FERTIG = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}


def warte_auf_status(token: str, publish_id: str, warten_s: int = 90) -> dict:
    """Nach dem Hochladen nachsehen, ob TikTok das Video angenommen hat. FAILED -> Fehler (mit Grund);
    dauert die Verarbeitung laenger, gilt es als angekommen (TikTok meldet sich dann in der App)."""
    ende = time.time() + warten_s
    while True:
        d = (_post_mit(token, "/post/publish/status/fetch/", {"publish_id": publish_id}).get("data") or {})
        st = d.get("status")
        if st == "FAILED":
            raise TikTokFehler(f"TikTok konnte das Video nicht verarbeiten ({d.get('fail_reason') or 'unbekannt'}).")
        if st in FERTIG or time.time() > ende:
            return d
        time.sleep(5)


def poste_video(video: bytes, titel: str, modus: str = "entwurf", warten_s: int = 90) -> dict:
    """modus "entwurf": in den TikTok-Posteingang; "direkt": selbst veroeffentlichen.
    Rueckgabe: {"id": publish_id (oder Video-ID, wenn schon oeffentlich), "url": None oder Link}"""
    token = gueltiger_token()
    if modus == "direkt":
        info = (_post_mit(token, "/post/publish/creator_info/query/", {}).get("data") or {})
        stufen = info.get("privacy_level_options") or ["SELF_ONLY"]
        sicht = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in stufen else stufen[0]
        start = _post_mit(token, "/post/publish/video/init/", {
            "post_info": {"title": titel[:2200], "privacy_level": sicht,
                          "disable_comment": bool(info.get("comment_disabled")),
                          "disable_duet": bool(info.get("duet_disabled")),
                          "disable_stitch": bool(info.get("stitch_disabled"))},
            "source_info": _quelle(video)})
    else:
        start = _post_mit(token, "/post/publish/inbox/video/init/", {"source_info": _quelle(video)})
    d = start.get("data") or {}
    if not d.get("upload_url"):
        raise TikTokFehler("TikTok hat keine Upload-Adresse geliefert.")
    _hochladen(d["upload_url"], video)
    pid = d.get("publish_id")
    ergebnis = {"id": pid, "url": None}
    if pid and warten_s:
        st = warte_auf_status(token, pid, warten_s)
        oeffentlich = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
        if oeffentlich:
            vid = str(oeffentlich[0])
            name = (zugang() or {}).get("name")
            ergebnis = {"id": vid, "url": f"https://www.tiktok.com/@{name}/video/{vid}" if name else None}
    return ergebnis


# ---------------------------------------------------------------------------
# Zahlen: die eigenen Videos mit Aufrufen, Gefaellt mir, Kommentaren, Teilen (video.list, ohne Audit)
# ---------------------------------------------------------------------------
VIDEO_FELDER = "id,title,video_description,create_time,share_url,view_count,like_count,comment_count,share_count"


def videos(anzahl: int = 20) -> list[dict]:
    """Die letzten Videos des Kontos (neueste zuerst). Wirft TikTokFehler bei fehlendem Recht."""
    token = gueltiger_token()
    out, cursor = [], None
    while len(out) < anzahl:
        body = {"max_count": min(20, anzahl - len(out))}
        if cursor:
            body["cursor"] = cursor
        r = requests.post(f"{API}/video/list/", params={"fields": VIDEO_FELDER}, json=body, timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        d = _antwort(r).get("data") or {}
        out += d.get("videos") or []
        if not d.get("has_more") or not d.get("cursor"):
            break
        cursor = d["cursor"]
    return out


def konto() -> dict | None:
    """Follower, Likes und Zahl der Videos (braucht user.info.stats); None ohne das Recht."""
    z = zugang() or {}
    if "user.info.stats" not in (z.get("rechte") or []):
        return None
    d = (_get_mit(gueltiger_token(), "/user/info/", fields="follower_count,likes_count,video_count").get("data") or {})
    u = d.get("user") or {}
    return {"follower": u.get("follower_count"), "likes": u.get("likes_count"), "videos": u.get("video_count")}


def _kern(text: str | None) -> str:
    return re.sub(r"[^0-9a-zà-ÿőű]+", " ", (text or "").lower()).strip()


def zuordnen_nach_titel(reels: list[dict], liste: list[dict]) -> list[dict]:
    """Selbst hochgeladene Videos (z. B. aus dem Wochenpaket) einem Reel zuordnen: der Reel-Titel steht am Anfang
    der TikTok-Beschreibung."""
    out, vergeben = [], set()
    for v in liste:
        # in der TikTok-App gepostete Videos haben den Text oft nur in video_description, title ist leer
        t = _kern(v.get("title") or v.get("video_description"))
        if not t:
            continue
        for r in reels:
            k = _kern(r.get("titel"))
            if len(k) >= 8 and t.startswith(k[:40]) and r["post_id"] not in vergeben:
                vergeben.add(r["post_id"])
                out.append({"post_id": r["post_id"], "titel": r.get("titel"), "art": "reel", "url": v.get("share_url"),
                            "gepostet": datetime.fromtimestamp(v["create_time"], timezone.utc) if v.get("create_time") else None,
                            "aufrufe": int(v.get("view_count") or 0), "reaktionen": int(v.get("like_count") or 0),
                            "kommentare": int(v.get("comment_count") or 0), "geteilt": int(v.get("share_count") or 0),
                            "_video": str(v.get("id"))})
                break
    return out


def zuordnen(eintraege: list[dict], liste: list[dict]) -> list[dict]:
    """Unsere TikTok-Termine den Videos zuordnen: zuerst ueber die Video-ID (direkt veroeffentlicht), sonst
    das erste Video, das innerhalb von 3 Tagen nach dem Hochladen entstand (Entwurf, selbst gepostet)."""
    frei = sorted(liste, key=lambda v: v.get("create_time") or 0)
    nach_id = {str(v.get("id")): v for v in frei}
    out = []
    for e in sorted(eintraege, key=lambda x: x.get("aktualisiert") or datetime.min.replace(tzinfo=timezone.utc)):
        v = nach_id.get(str(e.get("extern_id")))
        if not v and e.get("aktualisiert"):
            ab = e["aktualisiert"].timestamp() - 600
            v = next((x for x in frei if ab <= (x.get("create_time") or 0) <= ab + 3 * 86400 and x in frei), None)
        if v:
            frei = [x for x in frei if x is not v]
            out.append({"post_id": e["post_id"], "titel": e.get("titel"), "art": e.get("art"),
                        "url": v.get("share_url") or e.get("url"), "gepostet": e.get("aktualisiert"),
                        "aufrufe": int(v.get("view_count") or 0), "reaktionen": int(v.get("like_count") or 0),
                        "kommentare": int(v.get("comment_count") or 0), "geteilt": int(v.get("share_count") or 0),
                        "_video": str(v.get("id"))})
    return out
