"""
Datenbank-Anbindung an die PostgreSQL-Datenbank von Railway.
Railway stellt die Verbindung ueber die Variable DATABASE_URL bereit.
"""

import os
import json
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _verbindung():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL fehlt. Bitte in Railway eine PostgreSQL-Datenbank "
            "hinzufuegen und mit dem Service verbinden."
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    """Legt die Tabellen an, falls sie noch nicht existieren."""
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
        conn.commit()


def speichere_posts(posts: list[dict]) -> list[dict]:
    if not posts:
        return []
    gespeichert = []
    with _verbindung() as conn, conn.cursor() as cur:
        for p in posts:
            cur.execute(
                "insert into soraya_posts (platform, text, hashtags) "
                "values (%s, %s, %s) returning *;",
                (
                    p.get("platform", "instagram"),
                    p.get("text", ""),
                    " ".join(p.get("hashtags", [])),
                ),
            )
            gespeichert.append(cur.fetchone())
        conn.commit()
    return gespeichert


def lade_posts(limit: int = 50) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from soraya_posts order by created_at desc limit %s;",
            (limit,),
        )
        return cur.fetchall()


def speichere_zielgruppe(bereich: str, profil: dict) -> dict:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into soraya_zielgruppen (bereich, profil) "
            "values (%s, %s) returning *;",
            (bereich, json.dumps(profil)),
        )
        zeile = cur.fetchone()
        conn.commit()
    return zeile


def lade_zielgruppen(limit: int = 20) -> list[dict]:
    with _verbindung() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from soraya_zielgruppen order by created_at desc limit %s;",
            (limit,),
        )
        return cur.fetchall()
