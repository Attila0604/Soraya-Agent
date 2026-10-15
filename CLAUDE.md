# Soraya-Agent

Der vollständige Projektüberblick (alle Repos, Regeln, offene Punkte) steht in
`CLAUDE.md` im Repo `Attila0604/soraya-web`. Kurz für dieses Repo:

- FastAPI auf Railway, Dashboard „Content Studio“ = `dashboard.html` (HTTP-Basic-Login).
- Module: `tagesplan.py` + `redaktion.py` (Tagesplan, Formate, Qualitätsprüfung), `medien.py` / `reel.py` /
  `paket.py` (Bilder, Reels, Wochenpaket), `posten.py` + `meta.py` (automatisch posten), `wirkung.py`,
  `research_agent.py` (Zielgruppen), `db.py` (Tabellen werden in `init_db()` angelegt/erweitert).
- **Tagesplan-Automatik und automatisches Posten stehen AUS** – nur Attila schaltet sie ein.
- Tests: siehe `tests/README.md` (nie gegen die echte Datenbank laufen lassen).
