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

STATUS = ("entwurf", "freigegeben", "gepostet")


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
        # Zielgruppe im Tagesplan verwenden, Land der Recherche (seit Version 0.9)
        cur.execute("alter table soraya_zielgruppen add column if not exists im_tagesplan boolean not null default false;")
        cur.execute("alter table soraya_zielgruppen add column if not exists land text;")
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


def letzte_titel(sprache: str, tage: int = 7) -> list[str]:
    """Bild-Ueberschriften der letzten Tage, damit sich der Tagesplan nicht wiederholt."""
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select titel from soraya_posts where quelle = 'himmel' and sprache = %s and titel is not null "
            "and geplant_fuer >= current_date - %s order by geplant_fuer desc limit 45;",
            (sprache, tage),
        )
        return [z["titel"] for z in cur.fetchall()]
