# Soraya-Agent

Der vollständige Projektüberblick (alle Repos, Regeln, offene Punkte) steht in
`CLAUDE.md` im Repo `Attila0604/soraya-web`. Kurz für dieses Repo:

- FastAPI auf Railway, Dashboard „Content Studio“ = `dashboard.html` (HTTP-Basic-Login).
- Module: `tagesplan.py` + `redaktion.py` (Tagesplan, Formate, Qualitätsprüfung), `medien.py` / `reel.py` /
  `paket.py` (Bilder, Reels, Wochenpaket), `posten.py` + `meta.py` / `tiktok.py` / `linkedin.py` (automatisch posten;
  LinkedIn = persönliches Profil, Zugang 60 Tage ohne Verlängerung), `wirkung.py` + `cockpit.py`
  (Zahlen-Cockpit `/wirkung/cockpit`, Wochenbericht `/wirkung/wochenbericht`, nur gemerkte Zahlen, 5 Min. Cache),
  `auswertung.py` (Unterreiter Plattformen/Lernen + „Soraya erkennt“: Erkenntnis-Karten ohne KI, „Übernehmen“ füllt nur das
  Posten-Formular aus, speichert nie),
  `research_agent.py` (Zielgruppen), `db.py` (Tabellen werden in `init_db()` angelegt/erweitert).
- Tagesplan je Sprache: Feed-Post, 2 Reels (zweites = `meta.reel_nr = 2`, Platz `reel2`, eigene Uhrzeit), Story –
  aus einem Claude-Aufruf. `posten.platz()`/`sprache_fuer()` und `platzVon()`/`spracheFuer()` im Dashboard gleich halten.
- TikTok bekommt eine eigene Reel-Fassung (`paket.rendere_tiktok`, `reel.erstelle(..., tiktok=True)`): nur Hook + 1 Zeile,
  kurze Endkarte (~7–9 s), **stille** Tonspur – Attila legt in der TikTok-App einen Sound dazu.
- **Tagesplan-Automatik und automatisches Posten stehen AUS** – nur Attila schaltet sie ein.
- Tests: siehe `tests/README.md` (nie gegen die echte Datenbank laufen lassen).
