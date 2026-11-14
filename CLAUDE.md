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
  `PINTEREST_SANDBOX=1` (Pins nicht öffentlich) + `PINTEREST_SANDBOX_TOKEN` (App-Seite → „Generate token“ → Sandbox; der OAuth-Zugang gilt dort nicht). Rückruf `/pinterest/rueckruf`, eigener Haken Standard AUS.
  Seit 07.11.: Reels als Video-Pins (`pinterest.poste_video`), Pins zu genau einem Zeichen auf einer Pinnwand je Zeichen
  (`pinnwand_zeichen`), Zusatz-Pins in `pin_extras.py` + Tabelle `soraya_pins` (Karussell-Folien 2/4/6 h nach dem Titel-Pin,
  20:30 ein Sternzeichen-Pin aus `inhalte/zeichen_pins.json`, neu bauen mit `tools/zeichen_pins_bauen.py ../soraya-landing`);
  ihre Zahlen zählen zum Feed-Post.
- Feste Text-Prüfungen im Tagesplan (`tagesplan.tageszeit_befunde`, `stil_befunde`, `zeichen_befunde`, `redaktion` „Leerer Hook“)
  lösen einen Korrekturdurchgang aus, ohne das Posten zu blockieren. Reels nennen immer Sternzeichen (2. Reel = Drei-Zeichen-Check
  „Name, Name, Name: Aussage“). Facebook-Text = Hook + Kommentar-Frage (`posten.fb_kurz`), 6 Hashtags. Tagesplan und
  Lektorat mit `effort="high"`; Lektorat prüft auch, ob der Hook zum Rest passt.
- Reels ab `reel-18` ohne Umlaufbahn und Sternbild; Neumond mit goldenem Lichtkranz (`reel._neumond_kranz`).
- Sonntags ist das 2. Reel das **App-Reel** (`tagesplan.app_funktion`/`app_reel_text`, `meta.app_reel`): weiter Drei-Zeichen-Check,
  führt aber zu einer App-Funktion (wöchentlich wechselnd). Reel-Schlussbild ab `reel-22` mit Zeile „Google Play: Soraya Astro“.
  „Heute“ zeigt die Zeile „Gestern: Aufrufe · neue Follower · neue Konten“ (`/wirkung/gestern`, `cockpit.gestern`).
- **Tagesplan-Automatik und automatisches Posten stehen AUS** – nur Attila schaltet sie ein.
- Tests: siehe `tests/README.md` (nie gegen die echte Datenbank laufen lassen).
