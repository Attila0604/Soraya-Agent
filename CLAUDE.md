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
- 2. Reel wechselt das Format je Wochentag (`tagesplan.REEL2_FORMATE`, `meta.reel_format`, ab `reel-25`): Mo Deine Woche in einem Wort (Sternzeichen-Rad, ab `reel-26`) ·
  Di 3 Glückspilze (Platz 3/2/1) · Mi Ritual für 3 Zeichen (Kerzenschein) · Do Elemente-Check (3 Zeichen eines Elements) ·
  Fr Stopp bei deinem Zeichen (12 Zeichen im Raster) · Sa Wähl eine Karte (1/2/3, Karten drehen sich um) · So App-Reel.
  Medaillons ab `reel-26` mit Goldring, Lichtpunkten, drehendem Ring + Funken am aktiven Zeichen (`reel._medaillon`). Jedes Format endet mit einer spielerischen Antwort-Frage (🍀, 🕯️, 🔥🌍💨💧, ✅/❌, 1/2/3).
- Ausblick ab `reel-27` (`reel.ausblick`, `posten.reel_ausblick`): Endkarte und Facebook/Instagram-Text der Reels nennen das
  nächste Format („Ma este: …“ beim 1. Reel, „Holnap: …“ beim 2.) + „kövess, hogy ne maradj le“ (vor den Hashtags 4–6).
  Neu-/Vollmond mit Zeichen (`himmel.mondereignis_zeichen`, Sonnenlänge) – Prompt warnt, Mond heute ≠ Vollmond-Zeichen.
- Farbwelten ab `reel-28`/`reel-30` (`reel.welt`, `reel.Szene`, `reel.akzent_fuer`): Welt nach Element des Hook-Zeichens
  (feuer/erde/luft/wasser), Voll-/Neumond mitternacht, Formate fest (`FORMAT_WELT`); Szene nebel/polarlicht/galaxie/staub;
  je Reel GENAU EIN Effekt (strahlen, schleier, wellen, funken, kometen) – Wunsch Attila „Abwechslung, nicht zu viel“.
  Immer: atmender Hintergrund, Impuls+Zoom bei neuem Satz, Schlüsselwort in Gold.
- Echte Videos ab `reel-31` (`stock.py`, Pixabay oder Pexels, nur Motive ohne Menschen): nur wenn Railway `PIXABAY_API_KEY`
  (Pexels gibt seit 24.11. keine neuen Schlüssel aus) bzw. `PEXELS_API_KEY` gesetzt;
  `STOCK_ANTEIL` (Standard 0.5) = Anteil der Reels, fest je Post-ID; Video abgedunkelt + in der Farbwelt getönt, langsamer Zoom,
  Text tiefer (1400), kein gezeichnetes Motiv, nur ruhige Effekte. Cache `STOCK_DIR` (/tmp/soraya-stock). Fehler → gezeichnete Szene.
- Hintergrund je Reel FEST (`reel.hintergrund_plan`/`hintergrund_merken`, `meta.hintergrund` = art video|gezeichnet, welt, szene,
  effekt, video{id,quelle,link,thema}): beim Speichern im Tagesplan bzw. spätestens beim ersten Video festgelegt; Content Studio
  zeigt „🎬 Echtes Video (…) · Original ansehen ↗“ bzw. „✨ Gezeichnet · Welt · Szene · Effekt“. `meta.hintergrund` zählt nicht
  zum Video-Fingerabdruck (`paket._fingerabdruck`).
- Reels auf DE/EN nur freitags (`tagesplan.reels_heute`, Railway `REELS_WOECHENTLICH`, Standard `de,en`, leer = täglich);
  an den anderen Tagen nur Feed-Post + Story (spart Kosten). Ungarisch (Facebook) immer mit 2 Reels.
- Kommentare (`kommentare.py`, Tabelle `soraya_kommentare`, `/kommentare`, „Heute“ → „Kommentare auf Facebook“): liest die
  Kommentare der Facebook-Beiträge der letzten 4 Tage (Recht pages_read_user_content), Antwort-Vorschläge auf Knopfdruck
  (ein Claude-Aufruf für bis zu 10, effort low, gemerkt). Soraya antwortet NICHT selbst (bräuchte pages_manage_engagement).
- **Tagesplan-Automatik und automatisches Posten stehen AUS** – nur Attila schaltet sie ein.
- Tests: siehe `tests/README.md` (nie gegen die echte Datenbank laufen lassen).
