"""
Anbindung an Meta: Facebook-Seite und Instagram (Business-Konto)

Zwei getrennte Verbindungen, beide ueber eine eigene Meta-App ("Soraya Agent"):
- Facebook-Seite: Facebook-Anmeldung -> Seiten-Zugang (laeuft nicht ab)
- Instagram: Instagram-Anmeldung (Business Login, ohne Verknuepfung mit der Seite)
  -> Zugang fuer 60 Tage, wird automatisch verlaengert. Zahlen je Beitrag (Reichweite, Aufrufe,
  Speichern, Teilen) braucht zusaetzlich das Recht instagram_business_manage_insights.

Railway-Variablen (aus developers.facebook.com, nie in den Chat kopieren):
  META_APP_ID, META_APP_SECRET            Facebook-Seite
  INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET  Instagram (eigene IDs im Bereich "Instagram")
  META_API_VERSION                        optional, Standard v24.0

Die Zugaenge liegen in der Datenbank (soraya_einstellungen) und gehen nie ans Dashboard.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import json
import secrets
import time
from urllib.parse import urlencode

import requests

import db

TIMEOUT = 60
FB_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts"
IG_SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights"
IG_INSIGHTS_RECHT = "instagram_business_manage_insights"


class MetaFehler(RuntimeError):
    pass


def version() -> str:
    return (os.environ.get("META_API_VERSION") or "v24.0").strip()


def graph_fb() -> str:
    return f"https://graph.facebook.com/{version()}"


def graph_ig() -> str:
    return f"https://graph.instagram.com/{version()}"


def basis_url() -> str:
    """Oeffentliche Adresse des Agenten (Railway setzt RAILWAY_PUBLIC_DOMAIN)."""
    eigene = (os.environ.get("AGENT_URL") or "").strip().rstrip("/")
    if eigene:
        return eigene
    domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    return f"https://{domain}" if domain else "https://soraya-agent-production.up.railway.app"


def rueckruf_url(dienst: str) -> str:
    return f"{basis_url()}/meta/rueckruf/{dienst}"


def eingerichtet(dienst: str) -> bool:
    if dienst == "facebook":
        return bool(os.environ.get("META_APP_ID") and os.environ.get("META_APP_SECRET"))
    return bool(os.environ.get("INSTAGRAM_APP_ID") and os.environ.get("INSTAGRAM_APP_SECRET"))


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def _geheimnis() -> bytes:
    return hashlib.sha256(("soraya-meta:" + os.environ.get("AGENT_PASSWORT", "")).encode()).digest()


def signiere(text: str) -> str:
    return hmac.new(_geheimnis(), text.encode(), hashlib.sha256).hexdigest()[:32]


def _antwort(r: requests.Response) -> dict:
    try:
        daten = r.json()
    except ValueError:
        daten = {}
    if r.status_code >= 400 or (isinstance(daten, dict) and daten.get("error")):
        fehler = (daten or {}).get("error") or {}
        if isinstance(fehler, dict):
            text = fehler.get("error_user_msg") or fehler.get("message") or r.text[:300]
            code = fehler.get("code")
        else:
            text, code = str(fehler), None
        if code == 190 or r.status_code == 401:
            text = "Zugang abgelaufen oder entzogen – bitte im Dashboard neu verbinden. (" + text + ")"
        raise MetaFehler(f"Meta: {text}"[:400])
    return daten


def _get(url, **params):
    return _antwort(requests.get(url, params=params, timeout=TIMEOUT))


def _post(url, data=None, files=None, headers=None):
    return _antwort(requests.post(url, data=data, files=files, headers=headers, timeout=TIMEOUT * 3))


# ---------------------------------------------------------------------------
# Verbinden
# ---------------------------------------------------------------------------
def anmelde_url(dienst: str) -> str:
    if not eingerichtet(dienst):
        raise MetaFehler("Die Meta-App ist in Railway noch nicht eingetragen.")
    zufall = secrets.token_urlsafe(12)
    state = f"{dienst}.{int(time.time())}.{zufall}"
    state += "." + signiere(state)
    if dienst == "facebook":
        return "https://www.facebook.com/" + version() + "/dialog/oauth?" + urlencode({
            "client_id": os.environ["META_APP_ID"], "redirect_uri": rueckruf_url("facebook"),
            "state": state, "scope": FB_SCOPES, "response_type": "code"})
    return "https://www.instagram.com/oauth/authorize?" + urlencode({
        "client_id": os.environ["INSTAGRAM_APP_ID"], "redirect_uri": rueckruf_url("instagram"),
        "state": state, "scope": IG_SCOPES, "response_type": "code", "enable_fb_login": "0"})


def pruefe_state(dienst: str, state: str) -> None:
    teile = (state or "").split(".")
    if len(teile) != 4 or teile[0] != dienst:
        raise MetaFehler("Ungültige Rückmeldung von Meta (state).")
    roh, sig = ".".join(teile[:3]), teile[3]
    if not hmac.compare_digest(signiere(roh), sig) or time.time() - int(teile[1]) > 1800:
        raise MetaFehler("Die Anmeldung ist abgelaufen – bitte noch einmal verbinden.")


def verbinde_facebook(code: str) -> dict:
    """Code -> Nutzer-Zugang -> langlebiger Zugang -> Seiten-Zugang (laeuft nicht ab)."""
    kurz = _get(graph_fb() + "/oauth/access_token", client_id=os.environ["META_APP_ID"],
                client_secret=os.environ["META_APP_SECRET"], redirect_uri=rueckruf_url("facebook"), code=code)
    lang = _get(graph_fb() + "/oauth/access_token", grant_type="fb_exchange_token",
                client_id=os.environ["META_APP_ID"], client_secret=os.environ["META_APP_SECRET"],
                fb_exchange_token=kurz["access_token"])
    seiten = _get(graph_fb() + "/me/accounts", fields="id,name,access_token", access_token=lang["access_token"],
                  limit=50).get("data") or []
    if not seiten:
        raise MetaFehler("Keine Facebook-Seite freigegeben. Bitte beim Verbinden die Seite Soraya auswählen.")
    wunsch = (os.environ.get("META_PAGE_ID") or "").strip()
    seite = next((s for s in seiten if s["id"] == wunsch), None) or \
        next((s for s in seiten if "soraya" in (s.get("name") or "").lower()), None) or seiten[0]
    daten = {"seite_id": seite["id"], "name": seite.get("name"), "token": seite["access_token"],
             "verbunden": int(time.time()), "andere_seiten": [s.get("name") for s in seiten if s is not seite]}
    db.setze_einstellung("meta_facebook", daten)
    return {"name": daten["name"]}


def verbinde_instagram(code: str) -> dict:
    """Code -> kurzer Zugang -> 60-Tage-Zugang; dazu Konto-ID und Name."""
    r = requests.post("https://api.instagram.com/oauth/access_token", data={
        "client_id": os.environ["INSTAGRAM_APP_ID"], "client_secret": os.environ["INSTAGRAM_APP_SECRET"],
        "grant_type": "authorization_code", "redirect_uri": rueckruf_url("instagram"), "code": code}, timeout=TIMEOUT)
    kurz = _antwort(r)
    if isinstance(kurz.get("data"), list) and kurz["data"]:
        kurz = kurz["data"][0]
    lang = _get("https://graph.instagram.com/access_token", grant_type="ig_exchange_token",
                client_secret=os.environ["INSTAGRAM_APP_SECRET"], access_token=kurz["access_token"])
    ich = _get(graph_ig() + "/me", fields="user_id,username", access_token=lang["access_token"])
    rechte = kurz.get("permissions")
    if isinstance(rechte, str):
        rechte = [r.strip() for r in rechte.split(",") if r.strip()]
    daten = {"konto_id": str(ich.get("user_id") or kurz.get("user_id")), "name": ich.get("username"),
             "token": lang["access_token"], "laeuft_ab": int(time.time()) + int(lang.get("expires_in") or 5184000),
             "verbunden": int(time.time()), "angefragt": IG_SCOPES,
             "rechte": rechte if isinstance(rechte, list) else None}
    db.setze_einstellung("meta_instagram", daten)
    return {"name": daten["name"]}


def trennen(dienst: str) -> None:
    db.setze_einstellung("meta_" + dienst, {})


def zugang(dienst: str) -> dict | None:
    try:
        return db.lade_einstellung("meta_" + dienst, None)
    except Exception:
        return None


def instagram_zahlen_erlaubt(z: dict | None) -> bool:
    """Darf der gespeicherte Instagram-Zugang Zahlen je Beitrag lesen (instagram_business_manage_insights)?
    Verbindungen von vor diesem Recht haben es nie bekommen -> Hinweis "neu verbinden"."""
    if not z or not z.get("token"):
        return False
    if z.get("insights_fehlt") and z.get("insights_meldung") and not (
            "not enough viewers" in z["insights_meldung"].lower() or _objekt_weg(Exception(z["insights_meldung"]))):
        return False          # (ohne gemerkte Meldung einmal neu fragen, damit sie im Dashboard steht)
    # Die Liste der Freigaben, die Instagram beim Verbinden mitschickt, ist nicht immer vollstaendig.
    # Deshalb zaehlt, ob das Recht angefragt wurde; fehlt es wirklich, meldet Meta beim ersten Abruf
    # "keine Berechtigung" -> insights_fehlt (bis zum Neu-Verbinden).
    if isinstance(z.get("rechte"), list) and IG_INSIGHTS_RECHT in z["rechte"]:
        return True
    return IG_INSIGHTS_RECHT in (z.get("angefragt") or "")


def verbindungen() -> dict:
    """Fuers Dashboard -- ohne Zugangsschluessel."""
    out = {}
    for dienst in ("facebook", "instagram"):
        z = zugang(dienst) or {}
        out[dienst] = {"eingerichtet": eingerichtet(dienst), "verbunden": bool(z.get("token")),
                       "name": z.get("name"), "laeuft_ab": z.get("laeuft_ab"),
                       "rueckruf_url": rueckruf_url(dienst)}
    if out["instagram"]["verbunden"]:
        out["instagram"]["zahlen"] = instagram_zahlen_erlaubt(zugang("instagram"))
    return out


def instagram_verlaengern(tage_vorher: int = 20) -> bool:
    """Den 60-Tage-Zugang rechtzeitig verlaengern (laeuft im Zeitplan mit)."""
    z = zugang("instagram")
    if not z or not z.get("token") or z.get("laeuft_ab", 0) - time.time() > tage_vorher * 86400:
        return False
    neu = _get("https://graph.instagram.com/refresh_access_token", grant_type="ig_refresh_token",
               access_token=z["token"])
    z.update(token=neu["access_token"], laeuft_ab=int(time.time()) + int(neu.get("expires_in") or 5184000))
    db.setze_einstellung("meta_instagram", z)
    return True


# ---------------------------------------------------------------------------
# Posten
# ---------------------------------------------------------------------------
def poste_facebook(art: str, text: str, bild: bytes | None = None, video: bytes | None = None,
                   bilder: list[bytes] | None = None) -> dict:
    """art: post (Foto mit Text; mit mehreren `bilder` als Mehrbild-Beitrag), story (Foto-Story),
    reel (Video-Reel). Rueckgabe: {"id", "url"}"""
    z = zugang("facebook")
    if not z or not z.get("token"):
        raise MetaFehler("Facebook-Seite ist nicht verbunden.")
    seite, token = z["seite_id"], z["token"]
    if art == "reel":
        start = _post(f"{graph_fb()}/{seite}/video_reels", data={"upload_phase": "start", "access_token": token})
        vid = start["video_id"]
        ziel = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{version()}/{vid}"
        _post(ziel, data=video, headers={"Authorization": f"OAuth {token}", "offset": "0",
                                         "file_size": str(len(video)), "Content-Type": "application/octet-stream"})
        _post(f"{graph_fb()}/{seite}/video_reels", data={
            "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
            "description": text, "access_token": token})
        return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}"}
    if art == "story":
        foto = _post(f"{graph_fb()}/{seite}/photos", data={"published": "false", "access_token": token},
                     files={"source": ("story.jpg", bild, "image/jpeg")})
        st = _post(f"{graph_fb()}/{seite}/photo_stories", data={"photo_id": foto["id"], "access_token": token})
        return {"id": st.get("post_id") or foto["id"], "url": f"https://www.facebook.com/{seite}"}
    if bilder and len(bilder) > 1:
        # Mehrbild-Beitrag: Fotos erst unveroeffentlicht hochladen, dann gemeinsam mit dem Text posten
        ids = []
        for i, daten in enumerate(bilder[:10]):
            f = _post(f"{graph_fb()}/{seite}/photos", data={"published": "false", "access_token": token},
                      files={"source": (f"bild{i + 1}.jpg", daten, "image/jpeg")})
            ids.append(f["id"])
        felder = {"message": text, "access_token": token}
        felder.update({f"attached_media[{i}]": json.dumps({"media_fbid": fid}) for i, fid in enumerate(ids)})
        beitrag = _post(f"{graph_fb()}/{seite}/feed", data=felder)
        return {"id": beitrag["id"], "url": f"https://www.facebook.com/{beitrag['id']}"}
    foto = _post(f"{graph_fb()}/{seite}/photos", data={"message": text, "access_token": token},
                 files={"source": ("post.jpg", bild or (bilder or [None])[0], "image/jpeg")})
    pid = foto.get("post_id") or foto["id"]
    return {"id": pid, "url": f"https://www.facebook.com/{pid}"}


# Wie viele Menschen ein Beitrag erreicht hat. Meta hat die Kennzahlen umbenannt: die erste, die
# antwortet, gilt. Braucht das Recht read_insights -- fehlt es, gibt es eben keine Reichweite.
REICHWEITE_METRIKEN = ("post_impressions_unique", "post_media_view")


def facebook_reichweite(extern_id: str, token: str) -> int | None:
    for metrik in REICHWEITE_METRIKEN:
        try:
            d = _get(f"{graph_fb()}/{extern_id}/insights", metric=metrik, access_token=token)
        except Exception:  # noqa: BLE001
            continue
        for eintrag in d.get("data") or []:
            werte = eintrag.get("values") or []
            if werte and isinstance(werte[-1].get("value"), (int, float)):
                return int(werte[-1]["value"])
    return None


def facebook_konto() -> dict:
    """Follower der Facebook-Seite (followers_count, sonst fan_count = "Gefaellt mir" der Seite).
    Geht mit dem Seiten-Zugang (pages_read_engagement), ein einziger Aufruf."""
    z = zugang("facebook")
    if not z or not z.get("token") or not z.get("seite_id"):
        raise MetaFehler("Facebook-Seite ist nicht verbunden.")
    d = _get(f"{graph_fb()}/{z['seite_id']}", fields="followers_count,fan_count", access_token=z["token"])
    anzahl = d.get("followers_count")
    return {"follower": anzahl if anzahl is not None else d.get("fan_count")}


def _fb_summen(d: dict, schluessel: str = "reactions") -> dict:
    return {"reaktionen": ((d.get(schluessel) or {}).get("summary") or {}).get("total_count", 0),
            "kommentare": ((d.get("comments") or {}).get("summary") or {}).get("total_count", 0),
            "geteilt": (d.get("shares") or {}).get("count", 0)}


def _fb_zahlen_eines(oid: str, art: str | None, seite: str | None, token: str) -> tuple[dict, str]:
    """Zahlen eines Beitrags. Je nach Objekt (Seitenbeitrag, Foto, Reel/Video) kennt Meta andere Felder:
    erst Felder, dann einfachere Felder, dann die Kanten /reactions und /comments. Bei Reels zuerst den
    zugehoerigen Seitenbeitrag (post_id) suchen. Rueckgabe: (Zahlen, ID, die geantwortet hat)."""
    kandidaten = [oid]
    if art == "reel":
        try:
            pid = str(_get(f"{graph_fb()}/{oid}", fields="post_id", access_token=token).get("post_id") or "")
            if pid:
                kandidaten.insert(0, pid if "_" in pid or not seite else f"{seite}_{pid}")
        except MetaFehler as ex:
            if "abgelaufen" in str(ex):
                raise
    letzter: Exception | None = None
    for k in kandidaten:
        felder = ["reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares",
                  "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0)",
                  "likes.summary(true).limit(0),comments.summary(true).limit(0)"]
        for f in felder:
            try:
                d = _get(f"{graph_fb()}/{k}", fields=f, access_token=token)
                return _fb_summen(d, "likes" if f.startswith("likes") else "reactions"), k
            except MetaFehler as ex:
                if "abgelaufen" in str(ex):
                    raise
                letzter = ex
        try:   # als Kanten fragen (manche Objekte kennen die Felder nicht, die Kanten aber schon)
            r = _get(f"{graph_fb()}/{k}/reactions", summary="total_count", limit=0, access_token=token)
            c = _get(f"{graph_fb()}/{k}/comments", summary="true", limit=0, access_token=token)
            return {"reaktionen": (r.get("summary") or {}).get("total_count", 0),
                    "kommentare": (c.get("summary") or {}).get("total_count", 0), "geteilt": 0}, k
        except MetaFehler as ex:
            if "abgelaufen" in str(ex):
                raise
            letzter = ex
    raise letzter or MetaFehler("Meta: keine Zahlen")


def facebook_reaktionen(eintraege: list[dict]) -> list[dict]:
    """Gefaellt-mir, Kommentare und Teilen je Facebook-Beitrag (braucht pages_read_engagement),
    dazu die Reichweite, wenn Meta sie herausgibt. Storys liefert Facebook ohne Zahlen (nicht_messbar)."""
    z = zugang("facebook")
    if not z or not z.get("token"):
        raise MetaFehler("Facebook-Seite ist nicht verbunden.")
    out = []
    reichweite_geht = True
    for e in eintraege:
        zeile = {"post_id": e["post_id"], "titel": e.get("titel"), "art": e.get("art"), "url": e.get("url"),
                 "gepostet": e.get("aktualisiert")}
        if e.get("art") == "story":
            zeile["nicht_messbar"] = True          # Facebook-Storys: keine Gefaellt-mir/Kommentare ueber die API
            out.append(zeile)
            continue
        try:
            zahlen, oid = _fb_zahlen_eines(str(e["extern_id"]), e.get("art"), z.get("seite_id"), z["token"])
            zeile.update(zahlen)
            if reichweite_geht:
                zeile["reichweite"] = facebook_reichweite(oid, z["token"])
                reichweite_geht = zeile["reichweite"] is not None   # ohne Recht nicht bei jedem Beitrag fragen
        except Exception as ex:  # noqa: BLE001 - ein Beitrag ohne Zahlen soll die Liste nicht stoppen
            zeile["fehler"] = f"{ARTNAME.get(e.get('art'), 'Beitrag')}: {str(ex)[:160]}"
        out.append(zeile)
    return out


ARTNAME = {"post": "Feed-Post", "reel": "Reel", "story": "Story"}


# ---------------------------------------------------------------------------
# Instagram: Zahlen je Beitrag und Follower (Instagram API mit Instagram-Login)
# ---------------------------------------------------------------------------
# Kennzahlen je Art. Meta hat "impressions"/"plays" abgeschafft, "views" gilt fuer Feed, Reels und Storys.
# Antwortet Meta mit "Kennzahl gibt es nicht", wird mit der kurzen Liste noch einmal gefragt.
IG_METRIKEN = {"post": "reach,likes,comments,saved,shares,views", "reel": "reach,likes,comments,saved,shares,views",
               "story": "reach,views,shares,replies"}
IG_METRIKEN_KURZ = "reach,saved"


class KeinRecht(MetaFehler):
    """Dem Zugang fehlt das Recht fuer die Zahlen (instagram_business_manage_insights)."""


def _zu_wenig_aufrufe(ex: Exception) -> bool:
    """Instagram zeigt Zahlen erst ab genug Aufrufen ("(#10) Not enough viewers for the media to show insights")."""
    return "not enough viewers" in str(ex).lower()


def _objekt_weg(ex: Exception) -> bool:
    """Beitrag nicht (mehr) abrufbar, z. B. abgelaufene Story oder geloeschter Post ("Unsupported get request.
    Object with ID ... does not exist, cannot be loaded due to missing permissions ...")."""
    t = str(ex).lower()
    return "unsupported get request" in t or "does not exist" in t


def _ist_rechtefehler(ex: Exception) -> bool:
    t = str(ex).lower()
    if _zu_wenig_aufrufe(ex) or _objekt_weg(ex):
        return False
    return any(w in t for w in ("permission", "(#200)", "insufficient", "not authorized", "scope"))


def _werte(d: dict) -> dict:
    """Antwort von /insights -> {name: zahl} (Meta liefert mal values[], mal total_value)."""
    out = {}
    for e in d.get("data") or []:
        wert = (e.get("total_value") or {}).get("value")
        if wert is None and e.get("values"):
            wert = e["values"][-1].get("value")
        if isinstance(wert, (int, float)):
            out[e.get("name")] = int(wert)
    return out


def instagram_insights(media_id: str, art: str, token: str) -> dict:
    """Zahlen eines Instagram-Beitrags. Wirft KeinRecht, wenn das Insights-Recht fehlt."""
    try:
        return _werte(_get(f"{graph_ig()}/{media_id}/insights", metric=IG_METRIKEN.get(art, IG_METRIKEN["post"]),
                           access_token=token))
    except MetaFehler as ex:
        if _zu_wenig_aufrufe(ex):
            return {}              # noch zu wenige Aufrufe: Instagram liefert (noch) keine Zahlen, kein Fehler
        if _ist_rechtefehler(ex):
            raise KeinRecht(str(ex)) from ex
        try:                       # z. B. eine Kennzahl, die es fuer diese Art (noch) nicht gibt
            return _werte(_get(f"{graph_ig()}/{media_id}/insights", metric=IG_METRIKEN_KURZ, access_token=token))
        except MetaFehler as ex2:
            if _zu_wenig_aufrufe(ex2):
                return {}
            if _ist_rechtefehler(ex2):
                raise KeinRecht(str(ex2)) from ex2
            raise


def instagram_konto() -> dict:
    """Follower und Zahl der Beitraege (geht schon mit instagram_business_basic)."""
    z = zugang("instagram")
    if not z or not z.get("token"):
        raise MetaFehler("Instagram ist nicht verbunden.")
    d = _get(graph_ig() + "/me", fields="username,followers_count,media_count", access_token=z["token"])
    return {"name": d.get("username") or z.get("name"), "follower": d.get("followers_count"),
            "beitraege": d.get("media_count")}


def instagram_zahlen(eintraege: list[dict]) -> dict:
    """Gefaellt mir und Kommentare je Instagram-Beitrag (immer), dazu Reichweite, Aufrufe, Speichern und
    Teilen, wenn der Zugang das Insights-Recht hat. Rueckgabe: {"beitraege": [...], "recht_fehlt": bool}"""
    z = zugang("instagram")
    if not z or not z.get("token"):
        raise MetaFehler("Instagram ist nicht verbunden.")
    token = z["token"]
    insights = instagram_zahlen_erlaubt(z)
    recht_fehlt = not insights
    out = []
    for e in eintraege:
        zeile = {"post_id": e["post_id"], "titel": e.get("titel"), "art": e.get("art"), "url": e.get("url"),
                 "gepostet": e.get("aktualisiert")}
        try:
            if e.get("art") != "story":         # Storys haben keine Gefaellt-mir-Zahl
                d = _get(f"{graph_ig()}/{e['extern_id']}", fields="like_count,comments_count", access_token=token)
                zeile.update(reaktionen=int(d.get("like_count") or 0), kommentare=int(d.get("comments_count") or 0))
            if insights:
                try:
                    w = instagram_insights(e["extern_id"], e.get("art") or "post", token)
                except KeinRecht as ex:
                    insights, recht_fehlt = False, True
                    z["insights_fehlt"] = True          # bis zum Neu-Verbinden nicht mehr fragen
                    z["insights_meldung"] = str(ex)[:300]   # genaue Meldung von Instagram (fuers Dashboard)
                    db.setze_einstellung("meta_instagram", z)
                    w = {}
                zeile.setdefault("reaktionen", w.get("likes", 0))
                # Storys: Antworten per Nachricht zaehlen wie Kommentare
                zeile.setdefault("kommentare", w.get("replies", 0) if e.get("art") == "story" else w.get("comments", 0))
                if w:
                    zeile.update(reichweite=w.get("reach"), aufrufe=w.get("views"), gespeichert=w.get("saved"),
                                 geteilt=w.get("shares", 0))
            zeile.setdefault("reaktionen", 0)
            zeile.setdefault("kommentare", 0)
            zeile.setdefault("geteilt", 0)
        except Exception as ex:  # noqa: BLE001 - ein Beitrag ohne Zahlen soll die Liste nicht stoppen
            zeile["fehler"] = str(ex)[:160]
        out.append(zeile)
    return {"beitraege": out, "recht_fehlt": recht_fehlt}


def _warte_auf(behaelter: str, token: str, art: str, warten_s: int) -> None:
    ende = time.time() + warten_s
    while True:
        st = _get(f"{graph_ig()}/{behaelter}", fields="status_code,status", access_token=token)
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise MetaFehler(f"Instagram konnte die Datei nicht verarbeiten ({code}: {st.get('status') or ''}).")
        if time.time() > ende:
            raise MetaFehler("Instagram verarbeitet die Datei noch zu lange – nächster Versuch später.")
        time.sleep(3 if art != "reel" else 6)


def poste_instagram(art: str, text: str, medien_url: str, warten_s: int = 300,
                    medien_urls: list[str] | None = None) -> dict:
    """Instagram holt Bild/Video selbst von medien_url (oeffentliche, signierte Adresse des Agenten).
    Mit mehreren medien_urls wird ein Feed-Post zum Karussell."""
    z = zugang("instagram")
    if not z or not z.get("token"):
        raise MetaFehler("Instagram ist nicht verbunden.")
    konto, token = z["konto_id"], z["token"]
    daten = {"access_token": token}
    if art == "post" and medien_urls and len(medien_urls) > 1:
        kinder = []
        for url in medien_urls[:10]:
            k = _post(f"{graph_ig()}/{konto}/media", data={"image_url": url, "is_carousel_item": "true",
                                                         "access_token": token})["id"]
            _warte_auf(k, token, art, warten_s)
            kinder.append(k)
        daten.update(media_type="CAROUSEL", children=",".join(kinder), caption=text)
    elif art == "reel":
        daten.update(media_type="REELS", video_url=medien_url, caption=text, share_to_feed="true")
    elif art == "story":
        daten.update(media_type="STORIES", image_url=medien_url)
    else:
        daten.update(image_url=medien_url, caption=text)
    behaelter = _post(f"{graph_ig()}/{konto}/media", data=daten)["id"]
    _warte_auf(behaelter, token, art, warten_s)
    veroeff = _post(f"{graph_ig()}/{konto}/media_publish", data={"creation_id": behaelter, "access_token": token})
    mid = veroeff["id"]
    try:
        link = _get(f"{graph_ig()}/{mid}", fields="permalink", access_token=token).get("permalink")
    except MetaFehler:
        link = None
    return {"id": mid, "url": link or (f"https://www.instagram.com/{z.get('name')}/" if z.get("name") else None)}
