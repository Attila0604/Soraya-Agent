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
- Reel-Musik (`musik.py`, ab `reel-12`): echte Instrument-Aufnahmen (CC0, `klaenge/*.opus` + `index.json`, Quellen in
  `klaenge/QUELLEN.md`, neu bauen mit `tools/klaenge_bauen.py`), 4 Stile nach Thema (`stil_fuer`), je Post-ID eigenes Stück.
  `reel.musik_fuer()` fällt ohne Klang-Bank auf die alte `reel.klang` zurück.
- Instagram: Feed-Post nur Mo/Mi/Fr als Karussell (`posten.KARUSSELL_TAGE`), sonst als Reel aus den Folien
  (`posten.als_diashow`, `paket.rendere_diashow`, `reel.diashow`; Folien mit `video=True` ohne „Wischen“). Facebook bleibt Karussell.
- Pinterest (`pinterest.py`): Feed-Post (Titelbild) + Story werden Pins, je Sprache eine Pinnwand, Link auf Landingpage bzw.
  Zeichen-Seite (`ziel_link`), Zugang 30 Tage mit Refresh. Railway `PINTEREST_APP_ID`/`PINTEREST_APP_SECRET`, bis „Standard access“
  `PINTEREST_SANDBOX=1` (Pins nicht öffentlich). Rückruf `/pinterest/rueckruf`, eigener Haken Standard AUS.
- **Tagesplan-Automatik und automatisches Posten stehen AUS** – nur Attila schaltet sie ein.
- Tests: siehe `tests/README.md` (nie gegen die echte Datenbank laufen lassen).
