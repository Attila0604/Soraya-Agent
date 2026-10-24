"""
Datenbank-Anbindung an die PostgreSQL-Datenbank von Railway.
Railway stellt die Verbindung ueber die Variable DATABASE_URL bereit.
"""

import json
import os
from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get("DATABASE_URL", "")

STATUS = ("entwurf", "freigegeben", "gepostet", "gestoppt")   # gestoppt = "Nicht posten"


def _verbindung():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL fehlt. Bitte in Railway eine PostgreSQL-Datenbank "
            "hinzufuegen und mit dem Service verbinden."
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    """Legt Tabellen und neue Spalten an, falls sie noch nicht existieren."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists soraya_posts (
                id          bigint generated always as identity primary key,
                platform    text not null,
                text        text not null,
                hashtags    text,
                status      text not null default 'entwurf',
                created_at  timestamptz not null default now()
            );
            """
        )
        # Redaktionsplan, Sprachen, Bilder, Tagesplan (seit Version 0.6)
        for spalte in (
            "sprache text not null default 'de'",
            "art text not null default 'post'",
            "titel text",
            "untertitel text",
            "skript jsonb",
            "meta jsonb",
            "quelle text not null default 'studio'",
            "geplant_fuer date",
            "gepostet_am timestamptz",
            "aktualisiert timestamptz not null default now()",
        ):
            cur.execute(f"alter table soraya_posts add column if not exists {spalte};")
        cur.execute("create index if not exists soraya_posts_plan on soraya_posts (geplant_fuer, sprache);")
        cur.execute(
            """
            create table if not exists soraya_zielgruppen (
                id          bigint generated always as identity primary key,
                bereich     text not null,
                profil      jsonb not null,
                created_at  timestamptz not null default now()
            );
            """
        )
        # Schalter aus dem Dashboard (z. B. Tagesplan-Automatik), seit Version 0.10
        cur.execute(
            """
            create table if not exists soraya_einstellungen (
                schluessel    text primary key,
                wert          jsonb not null,
                aktualisiert  timestamptz not null default now()
            );
            """
        )
        # Fertige Bilder und Reel-Videos (Zwischenspeicher, seit Version 0.11)
        cur.execute(
            """
            create table if not exists soraya_medien (
                post_id        bigint not null references soraya_posts(id) on delete cascade,
                art            text not null,
                fingerabdruck  text not null,
                mime           text not null,
                daten          bytea not null,
                erstellt       timestamptz not null default now(),
                primary key (post_id, art)
            );
            """
        )
        # Automatisch posten: ein Termin pro Post und Plattform (seit Version 0.12)
        cur.execute(
            """
            create table if not exists soraya_veroeffentlichungen (
                id            bigint generated always as identity primary key,
                post_id       bigint not null references soraya_posts(id) on delete cascade,
                plattform     text not null,
                geplant_um    timestamptz not null,
                status        text not null default 'geplant',
                versuche      int not null default 0,
                fehler        text,
                extern_id     text,
                url           text,
                aktualisiert  timestamptz not null default now(),
                unique (post_id, plattform)
            );
            """
        )
        cur.execute("create index if not exists soraya_veroeff_faellig on soraya_veroeffentlichungen (status, geplant_um);")
        # Zielgruppe im Tagesplan verwenden, Land der Recherche (seit Version 0.9)
        cur.execute("alter table soraya_zielgruppen add column if not exists im_tagesplan boolean not null default false;")
        cur.execute("alter table soraya_zielgruppen add column if not exists land text;")
        # gespeichert (Instagram "Speichern") und aufrufe (Instagram/TikTok "Aufrufe") seit Version 0.13
        for spalte in ("reaktionen int", "kommentare int", "geteilt int", "zahlen_am timestamptz", "reichweite int",
                       "gespeichert int", "aufrufe int"):
            cur.execute(f"alter table soraya_veroeffentlichungen add column if not exists {spalte};")
        cur.execute(
            """
            create table if not exists soraya_tagesplaene (
                datum         date not null,
                sprache       text not null,
                status        text not null,
                versuche      int not null default 1,
                fehler        text,
                himmel        jsonb,
                erstellt      timestamptz not null default now(),
                aktualisiert  timestamptz not null default now(),
                primary key (datum, sprache)
            );
            """
        )
        conn.commit()


def _hashtags(werte) -> str:
    if isinstance(werte, str):
        return werte.strip()
    return " ".join(h.strip() for h in (werte or []) if h and h.strip())


def speichere_posts(posts: list[dict], *, quelle: str = "studio",
                    geplant_fuer: date | None = None, meta: dict | None = None) -> list[dict]:
    if not posts:
        return []
    gespeichert = []
    with _verbindung() as conn, conn.cursor() as cur:
        for p in posts:
            cur.execute(
                "insert into soraya_posts (platform, text, hashtags, sprache, art, titel, untertitel, "
                "skript, meta, quelle, geplant_fuer) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *;",
                (
                    p.get("platform", "instagram"),
                    p.get("text", ""),
                    _hashtags(p.get("hashtags")),
                    p.get("sprache", "de"),
                    p.get("art", "post"),
                    p.get("titel") or None,
                    p.get("untertitel") or None,
                    Jsonb(p["skript"]) if p.get("skript") else None,
                    Jsonb(meta) if meta else None,
                    quelle,
                    geplant_fuer,
                ),
            )
            gespeichert.append(cur.fetchone())
        conn.commit()
    return gespeichert


def lade_post(post_id: int) -> dict | None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("select * from soraya_posts where id = %s;", (post_id,))
        return cur.fetchone()


def lade_posts_zeitraum(von: date, bis: date, *, sprachen: list[str] | None = None,
                        status: list[str] | None = None) -> list[dict]:
    """Nur Posts mit Datum im Zeitraum (fuer das Wochenpaket), nach Datum, Sprache, Art."""
    bedingungen, werte = ["geplant_fuer between %s and %s"], [von, bis]
    if sprachen:
        bedingungen.append("sprache = any(%s)")
        werte.append(list(sprachen))
    if status:
        bedingungen.append("status = any(%s)")
        werte.append(list(status))
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            f"select * from soraya_posts where {' and '.join(bedingungen)} "
            "order by geplant_fuer, sprache, case art when 'post' then 1 when 'reel' then 2 else 3 end, id;",
            werte,
        )
        return cur.fetchall()


def plane_veroeffentlichung(post_id: int, plattform: str, geplant_um, *, zurueckgeben: bool = False):
    """Termin anlegen. Normal: bestehende bleiben unveraendert (Rueckgabe 1 = neu, 0 = gab es schon).
    zurueckgeben=True ("Jetzt posten"): Termin auf jetzt setzen und die id liefern."""
    with _verbindung() as conn, conn.cursor() as cur:
        if not zurueckgeben:
            cur.execute("insert into soraya_veroeffentlichungen (post_id, plattform, geplant_um) values (%s, %s, %s) "
                        "on conflict (post_id, plattform) do nothing returning id;", (post_id, plattform, geplant_um))
            neu = cur.fetchone() is not None
            conn.commit()
            return 1 if neu else 0
        cur.execute("select id, status from soraya_veroeffentlichungen where post_id = %s and plattform = %s;",
                    (post_id, plattform))
        da = cur.fetchone()
        if da and da["status"] in ("fertig", "laeuft"):
            raise ValueError("Dieser Post ist dort schon gepostet." if da["status"] == "fertig"
                             else "Wird gerade gepostet.")
        cur.execute("insert into soraya_veroeffentlichungen (post_id, plattform, geplant_um) values (%s, %s, %s) "
                    "on conflict (post_id, plattform) do update set geplant_um = excluded.geplant_um, "
                    "status = 'geplant', versuche = 0, fehler = null, aktualisiert = now() returning id;",
                    (post_id, plattform, geplant_um))
        zid = cur.fetchone()["id"]
        conn.commit()
        return zid


def faellige_veroeffentlichungen(jetzt, max_versuche: int = 3) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from soraya_veroeffentlichungen where geplant_um <= %s and ("
            " status = 'geplant'"
            " or (status = 'fehler' and versuche < %s and aktualisiert < now() - interval '15 minutes')"
            " or (status = 'laeuft' and aktualisiert < now() - interval '30 minutes' and versuche < %s)"
            ") order by geplant_um, id limit 20;",
            (jetzt, max_versuche, max_versuche),
        )
        return cur.fetchall()


def setze_veroeffentlichung(zid: int, status: str, *, fehler: str | None = None, extern_id: str | None = None,
                            url: str | None = None, versuch: bool = False) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "update soraya_veroeffentlichungen set status = %s, fehler = %s, "
            "extern_id = coalesce(%s, extern_id), url = coalesce(%s, url), "
            "versuche = versuche + %s, aktualisiert = now() where id = %s;",
            (status, fehler, extern_id, url, 1 if versuch else 0, zid),
        )
        conn.commit()


def alle_veroeffentlicht(post_id: int) -> bool:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("select count(*) as n, count(*) filter (where status = 'fertig') as f "
                    "from soraya_veroeffentlichungen where post_id = %s;", (post_id,))
        z = cur.fetchone()
    return z["n"] > 0 and z["n"] == z["f"]


def lade_veroeffentlichungen(von, bis, limit: int = 200) -> list[dict]:
    """Termine im Zeitraum (fuers Dashboard), mit den wichtigsten Post-Feldern."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select v.*, p.titel, p.art, p.sprache, p.status as post_status, p.geplant_fuer, "
            "(p.meta->>'reel_nr')::int as reel_nr "
            "from soraya_veroeffentlichungen v join soraya_posts p on p.id = v.post_id "
            "where v.geplant_um between %s and %s order by v.geplant_um, v.plattform limit %s;",
            (von, bis, limit),
        )
        return cur.fetchall()


def lade_gepostete(plattform: str, seit, limit: int = 30) -> list[dict]:
    """Erfolgreich gepostete Beitraege einer Plattform (neueste zuerst), fuer die Reaktionen."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select v.post_id, v.extern_id, v.url, v.aktualisiert, p.titel, p.art, p.sprache "
            "from soraya_veroeffentlichungen v join soraya_posts p on p.id = v.post_id "
            "where v.plattform = %s and v.status = 'fertig' and v.extern_id is not null and v.aktualisiert >= %s "
            "order by v.aktualisiert desc limit %s;",
            (plattform, seit, limit),
        )
        return cur.fetchall()


def speichere_zahlen(post_id: int, plattform: str, reaktionen: int, kommentare: int, geteilt: int,
                     reichweite: int | None = None, gespeichert: int | None = None,
                     aufrufe: int | None = None) -> None:
    """Reaktionen eines geposteten Beitrags merken (fuer das Lernen ohne staendige API-Aufrufe).
    reichweite/gespeichert/aufrufe None = nicht gemessen (der alte Wert bleibt stehen)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("update soraya_veroeffentlichungen set reaktionen = %s, kommentare = %s, geteilt = %s, "
                    "reichweite = coalesce(%s, reichweite), gespeichert = coalesce(%s, gespeichert), "
                    "aufrufe = coalesce(%s, aufrufe), zahlen_am = now() where post_id = %s and plattform = %s;",
                    (reaktionen, kommentare, geteilt, reichweite, gespeichert, aufrufe, post_id, plattform))
        conn.commit()


def lade_gemerkte_zahlen(plattform: str, seit, limit: int = 30) -> list[dict]:
    """Gepostete Beitraege einer Plattform mit den zuletzt gemerkten Zahlen (ohne API-Aufruf)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select v.post_id, v.extern_id, v.url, v.aktualisiert as gepostet, v.reaktionen, v.kommentare, v.geteilt, "
            "v.reichweite, v.gespeichert, v.aufrufe, v.zahlen_am, p.titel, p.art, p.sprache "
            "from soraya_veroeffentlichungen v join soraya_posts p on p.id = v.post_id "
            "where v.plattform = %s and v.status = 'fertig' and v.aktualisiert >= %s "
            "order by v.aktualisiert desc limit %s;",
            (plattform, seit, limit),
        )
        return cur.fetchall()


def lade_cockpit_zeilen(seit, limit: int = 2000) -> list[dict]:
    """Je geposteter Beitrag und Plattform die gemerkten Zahlen (fuers Zahlen-Cockpit, ohne API-Aufruf)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select v.post_id, v.plattform, v.aktualisiert as gepostet, v.geplant_um, v.url, v.reaktionen, v.kommentare, v.geteilt, "
            "v.reichweite, v.gespeichert, v.aufrufe, v.zahlen_am, p.titel, p.art, p.sprache, p.meta, "
            "coalesce(p.aktualisiert, p.created_at) as post_stand "
            "from soraya_veroeffentlichungen v join soraya_posts p on p.id = v.post_id "
            "where v.status = 'fertig' and v.aktualisiert >= %s order by v.aktualisiert limit %s;",
            (seit, limit),
        )
        return cur.fetchall()


def lade_lern_posts(seit) -> list[dict]:
    """Gepostete Beitraege mit gemerkten Reaktionen (summiert ueber die Plattformen)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select p.id, p.titel, p.art, p.sprache, p.meta, min(v.aktualisiert) as gepostet, "
            "coalesce(sum(v.reaktionen), 0) as reaktionen, coalesce(sum(v.kommentare), 0) as kommentare, "
            "coalesce(sum(v.geteilt), 0) as geteilt, coalesce(sum(v.reichweite), 0) as reichweite, "
            "coalesce(sum(v.gespeichert), 0) as gespeichert, "
            # gemessen: Zahlen geholt -- bei Storys nur, wenn es Reichweite/Aufrufe gab (eine abgelaufene Story
            # ohne Insights ist nicht "0 Punkte", sondern nie gemessen)
            "bool_or(v.zahlen_am is not null and (p.art <> 'story' or v.reichweite is not null "
            "or v.aufrufe is not null)) as gemessen "
            "from soraya_veroeffentlichungen v join soraya_posts p on p.id = v.post_id "
            "where v.status = 'fertig' and v.aktualisiert >= %s group by p.id order by gepostet desc limit 200;",
            (seit,),
        )
        return cur.fetchall()


def lade_medium(post_id: int, art: str, fingerabdruck: str) -> bytes | None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("select daten from soraya_medien where post_id = %s and art = %s and fingerabdruck = %s;",
                    (post_id, art, fingerabdruck))
        zeile = cur.fetchone()
    return bytes(zeile["daten"]) if zeile else None


def speichere_medium(post_id: int, art: str, fingerabdruck: str, mime: str, daten: bytes) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into soraya_medien (post_id, art, fingerabdruck, mime, daten) values (%s, %s, %s, %s, %s) "
            "on conflict (post_id, art) do update set fingerabdruck = excluded.fingerabdruck, mime = excluded.mime, "
            "daten = excluded.daten, erstellt = now();",
            (post_id, art, fingerabdruck, mime, daten),
        )
        # alte Videos/Bilder nicht ewig aufheben
        cur.execute("delete from soraya_medien where erstellt < now() - interval '21 days';")
        conn.commit()


def lade_posts(limit: int = 50, *, von: date | None = None, bis: date | None = None,
               sprache: str | None = None, status: str | None = None,
               himmel: bool | None = None) -> list[dict]:
    """himmel=False: nur eigene Posts (Studio/Webseite), neueste zuerst."""
    bedingungen, werte = [], []
    if himmel is not None:
        bedingungen.append("quelle = 'himmel'" if himmel else "quelle <> 'himmel'")
    if von and bis:
        # Posts im Zeitraum plus alle ohne Datum (die gehoeren noch eingeplant)
        bedingungen.append("(geplant_fuer between %s and %s or geplant_fuer is null)")
        werte += [von, bis]
    if sprache:
        bedingungen.append("sprache = %s")
        werte.append(sprache)
    if status:
        bedingungen.append("status = %s")
        werte.append(status)
    wo = ("where " + " and ".join(bedingungen)) if bedingungen else ""
    werte.append(max(1, min(int(limit), 500)))
    reihenfolge = ("created_at desc, id desc" if himmel is False
                   else "geplant_fuer desc nulls last, created_at desc")
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            f"select * from soraya_posts {wo} order by {reihenfolge} limit %s;",
            werte,
        )
        return cur.fetchall()


_AENDERBAR = {"text", "hashtags", "titel", "untertitel", "status", "geplant_fuer", "platform"}


def aendere_post(post_id: int, felder: dict) -> dict | None:
    felder = {k: v for k, v in felder.items() if k in _AENDERBAR}
    if "status" in felder and felder["status"] not in STATUS:
        raise ValueError("Unbekannter Status.")
    if "hashtags" in felder:
        felder["hashtags"] = _hashtags(felder["hashtags"])
    if not felder:
        raise ValueError("Nichts zu ändern.")
    setzen = [f"{k} = %s" for k in felder]
    werte = list(felder.values())
    if "status" in felder:
        setzen.append("gepostet_am = case when %s = 'gepostet' then coalesce(gepostet_am, now()) else null end")
        werte.append(felder["status"])
    setzen.append("aktualisiert = now()")
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(f"update soraya_posts set {', '.join(setzen)} where id = %s returning *;", werte + [post_id])
        zeile = cur.fetchone()
        conn.commit()
    return zeile


def setze_meta(post_id: int, schluessel: str, wert) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("update soraya_posts set meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object(%s::text, %s::jsonb) "
                    "where id = %s;", (schluessel, Jsonb(wert), post_id))
        conn.commit()


def loesche_post(post_id: int) -> bool:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("delete from soraya_posts where id = %s;", (post_id,))
        geloescht = cur.rowcount > 0
        conn.commit()
    return geloescht


def speichere_zielgruppe(bereich: str, profil: dict, land: str | None = None) -> dict:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into soraya_zielgruppen (bereich, profil, land) "
            "values (%s, %s, %s) returning *;",
            (bereich, json.dumps(profil), land),
        )
        zeile = cur.fetchone()
        conn.commit()
    return zeile


def lade_zielgruppen(limit: int = 20) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from soraya_zielgruppen order by created_at desc, id desc limit %s;",
            (limit,),
        )
        return cur.fetchall()


def lade_einstellung(schluessel: str, standard=None):
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute("select wert from soraya_einstellungen where schluessel = %s;", (schluessel,))
        zeile = cur.fetchone()
    return zeile["wert"] if zeile else standard


def setze_einstellung(schluessel: str, wert) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into soraya_einstellungen (schluessel, wert) values (%s, %s) "
            "on conflict (schluessel) do update set wert = excluded.wert, aktualisiert = now();",
            (schluessel, Jsonb(wert)),
        )
        conn.commit()


def setze_zielgruppe_im_tagesplan(zielgruppe_id: int, an: bool) -> dict | None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "update soraya_zielgruppen set im_tagesplan = %s where id = %s returning *;",
            (bool(an), zielgruppe_id),
        )
        zeile = cur.fetchone()
        conn.commit()
    return zeile


# ---------------------------------------------------------------------------
# Tagesplan: pro Datum und Sprache genau ein Lauf (Sperre ueber die Datenbank,
# damit auch bei Neustarts nichts doppelt erzeugt wird)
# ---------------------------------------------------------------------------
def beanspruche_tagesplan(datum: date, sprache: str, *, erzwingen: bool = False, manuell: bool = False) -> bool:
    """True, wenn dieser Aufruf den Tagesplan jetzt erstellen darf.
    erzwingen: alles ausser laufenden Laeufen neu; manuell (Knopf): Fehler sofort wiederholen;
    sonst (Zeitplan): Fehler hoechstens 3x, mit 30 Minuten Abstand."""
    haengt = ("(soraya_tagesplaene.status = 'laeuft' "
              " and soraya_tagesplaene.aktualisiert < now() - interval '15 minutes')")
    if erzwingen:
        bedingung = "soraya_tagesplaene.status <> 'laeuft' or " + haengt
    elif manuell:
        bedingung = "soraya_tagesplaene.status = 'fehler' or " + haengt
    else:
        bedingung = (
            "(soraya_tagesplaene.status = 'fehler' and soraya_tagesplaene.versuche < 3 "
            " and soraya_tagesplaene.aktualisiert < now() - interval '30 minutes') or " + haengt
        )
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into soraya_tagesplaene (datum, sprache, status) values (%s, %s, 'laeuft') "
            "on conflict (datum, sprache) do update set status = 'laeuft', fehler = null, "
            "versuche = case when %s then 1 else soraya_tagesplaene.versuche + 1 end, aktualisiert = now() "
            f"where {bedingung} returning datum;",
            (datum, sprache, erzwingen),
        )
        erhalten = cur.fetchone() is not None
        conn.commit()
    return erhalten


def tagesplan_fertig(datum: date, sprache: str, himmel: dict) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "update soraya_tagesplaene set status = 'fertig', fehler = null, himmel = %s, aktualisiert = now() "
            "where datum = %s and sprache = %s;",
            (Jsonb(himmel), datum, sprache),
        )
        conn.commit()


def tagesplan_fehler(datum: date, sprache: str, fehler: str) -> None:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "update soraya_tagesplaene set status = 'fehler', fehler = %s, aktualisiert = now() "
            "where datum = %s and sprache = %s;",
            (fehler[:500], datum, sprache),
        )
        conn.commit()


def lade_tagesplaene(datum: date) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select datum, sprache, status, versuche, fehler, himmel, erstellt, aktualisiert "
            "from soraya_tagesplaene where datum = %s order by sprache;",
            (datum,),
        )
        return cur.fetchall()


def lade_tagesplaene_zeitraum(von: date, bis: date) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select datum, sprache, status, versuche, fehler, erstellt, aktualisiert "
            "from soraya_tagesplaene where datum between %s and %s order by datum, sprache;",
            (von, bis),
        )
        return cur.fetchall()


def loesche_tagesplan_entwuerfe(datum: date, sprache: str) -> int:
    """Vor dem Neu-Erstellen: nur unbearbeitete Entwuerfe dieses Tages entfernen."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from soraya_posts where quelle = 'himmel' and status = 'entwurf' "
            "and aktualisiert - created_at < interval '5 seconds' "
            "and geplant_fuer = %s and sprache = %s;",
            (datum, sprache),
        )
        anzahl = cur.rowcount
        conn.commit()
    return anzahl


def letzte_anfaenge(sprache: str, tage: int = 7) -> list[str]:
    """Erste Zeilen der Feed-Posts und Reels der letzten Tage (gegen gleiche Anfaenge)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select split_part(trim(text), E'\\n', 1) as anfang from soraya_posts where quelle = 'himmel' "
            "and sprache = %s and art in ('post', 'reel') and text is not null "
            "and geplant_fuer >= current_date - %s order by geplant_fuer desc limit 14;",
            (sprache, tage),
        )
        return [z["anfang"][:140] for z in cur.fetchall() if z["anfang"]]


def zaehle_format(sprache: str, thema: str, vor) -> int:
    """Wie viele Tage dieses Format in dieser Sprache schon hatte (fuer die Serien-Nummer)."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select count(distinct geplant_fuer) as n from soraya_posts where quelle = 'himmel' and sprache = %s "
            "and meta->>'thema' = %s and geplant_fuer < %s;",
            (sprache, thema, vor),
        )
        return int(cur.fetchone()["n"] or 0)


def letzte_titel(sprache: str, tage: int = 7) -> list[str]:
    """Bild-Ueberschriften der letzten Tage, damit sich der Tagesplan nicht wiederholt."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select titel from soraya_posts where quelle = 'himmel' and sprache = %s and titel is not null "
            "and geplant_fuer >= current_date - %s order by geplant_fuer desc limit 45;",
            (sprache, tage),
        )
        return [z["titel"] for z in cur.fetchall()]
