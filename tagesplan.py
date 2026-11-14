"""
Tagesplan aus dem Himmel
Jeden Morgen erstellt der Agent aus den echten Himmelsdaten (Mondphase,
Mondzeichen, Neu-/Vollmond, rueckläufige Planeten) die Posts des Tages,
pro Sprache: 1 Feed-Post, 2 Reels mit Skript (verschiedene Blickwinkel), 1 Story --
alles aus EINEM Claude-Aufruf je Sprache.

Ob er jeden Morgen automatisch laeuft, schaltest du im Dashboard (Standard: aus).

Railway-Variablen (alle optional):
  TAGESPLAN_AUTO      "0" = Automatik ganz gesperrt (auch der Schalter wirkt dann nicht)
  TAGESPLAN_SPRACHEN  Standard "de,en,hu,it"
  TAGESPLAN_STUNDE    ab dieser Stunde (Wiener Zeit) wird erstellt, Standard 6
"""

import copy
import json
import os
import random
import re
import threading
import time
from datetime import date, timedelta

import db
import himmel
import lektorat
import redaktion
import symbole
from claude import frage_json
from sprachen import LINK_IN_BIO, SPRACHEN, norm, sprach_anweisung

SYSTEM_PROMPT = """Du bist die Social-Media-Redakteurin der App "Soraya Luxury Astrology Guide"
(persönliches Tageshoroskop aus dem eigenen Geburtshoroskop, Partner-Vergleich in Prozent,
Astro-Chat; ohne Konto zeigt Soraya sofort Sonnen- und Mondzeichen).

Du bekommst die echten Himmelsdaten des Tages und das heutige Format und schreibst daraus den
Tagesplan für Instagram, Facebook und TikTok. Ziel: Menschen hören beim Scrollen auf, fühlen sich
persönlich gemeint, speichern, kommentieren oder teilen – und schauen sich Soraya an.

Ton: elegant, warm, klug, ein bisschen mystisch. Nie reißerisch, keine Angstmacherei, keine
Heils-, Geld- oder Gesundheitsversprechen, keine Garantien.

Fakten:
- Nutze nur die gelieferten Daten (Mondphase, Mondzeichen, Sonne, Neu-/Vollmond, Rückläufigkeiten).
  Erfinde KEINE weiteren Ereignisse, Aspekte, Daten oder Zahlen. Tage-Angaben genau übernehmen.

Was gute Posts ausmacht:
- Der erste Satz ist der Hook: höchstens 12 Wörter und höchstens 100 Zeichen (Instagram zeigt nur
  die ersten ~125 Zeichen, dann „… mehr“), konkret, persönlich („du“), weckt Neugier oder spricht
  Sternzeichen direkt an. Denk dir mehrere Hooks aus und nimm den stärksten.
- Der Hook (auch der große Satz im Reel) sagt selbst schon etwas: ein Gefühl, einen Moment, eine Behauptung, die
  neugierig macht. VERBOTEN sind leere Ankündigungen ohne Inhalt wie „Das ist für euch“, „Heute Abend ist das für
  euch“, „Das erwartet euch heute“, „So fühlt sich heute an“ (ungarisch z. B. „Ma este nektek szól ez“, „Ma ez vár
  rátok“). Statt anzukündigen, sag es: z. B. „Ihr drei sagt heute endlich, was ihr denkt“, „Heute Nacht schlaft ihr
  drei unruhig – zu Recht“, „Ihr habt heute mehr gegeben, als ihr zeigt“.
- Keine Prozentzahlen oder Messwerte im Text (nicht „der Mond ist zu 1 % beleuchtet“) – sag es als Bild: „der Mond
  ist kaum noch zu sehen“, „eine hauchdünne Sichel“. Zahlen stehen schon im Bild.
- Verboten sind leere Floskeln wie „Die Sterne stehen gut“, „Das Universum hat einen Plan“,
  „magische Energie“, „kosmische Schwingungen“, „Manifestiere jetzt“. Lieber ein konkretes Bild
  aus dem Alltag (Gespräch, Nachricht, Entscheidung, Schlaf, Arbeit, Beziehung).
- Lebendig statt Lexikon: wechsle kurze und längere Sätze, schreib wie eine kluge Freundin, die etwas
  Spannendes erzählt – mit einem konkreten Moment, den man vor sich sieht, und einer kleinen Wendung.
- Aufbau des Textes: Die erste Zeile (Hook) steht allein, dann eine Leerzeile („\n\n“). Danach kurze
  Absätze mit 1–2 Sätzen (höchstens ~200 Zeichen), jeweils durch eine Leerzeile getrennt – gut lesbar
  am Handy. Die Frage zum Kommentieren und die Handlungsaufforderung stehen je als eigener Absatz am
  Ende (zuerst die Frage, dann die Handlungsaufforderung). Höchstens 2 Emojis pro Text, gezielt gesetzt (nicht am Satzanfang, keine Emoji-Ketten).
- Klug und mit Tiefe: Jeder Feed-Post enthält eine Wissensschicht – ein gesichertes Detail aus der Mythologie
  (z. B. Venus und Aphrodite, Saturn und die Zeit), der Astronomie (z. B. warum ein Planet rückläufig wirkt) oder
  der Psychologie des Alltags –, in einem verständlichen Satz und verbunden mit dem Leben der Leserin. Nichts
  erfinden: keine Zitate, keine Studien, keine Zahlen, die du nicht sicher weißt.
- Tiefe (Feed-Post und erstes Reel): dazu ein stiller, weiser Gedanke, der bleibt – spirituell und philosophisch
  (Zeit und Wandel, Loslassen, Dankbarkeit, Vergebung, Stille, Verbundenheit, das Vertrauen in den eigenen Rhythmus),
  so wie ihn eine lebenserfahrene, belesene Frau sagen würde. Ohne zu predigen, ohne Religion vorzuschreiben, ohne
  erfundene Zitate oder Namen. Lieber ein eigenes, klares Bild als ein großes Wort.
- Spirituell und weise in ALLEN vier Einträgen (auch Story und zweites Reel): Soraya spricht wie eine weise,
  liebevolle Lehrerin, die den Himmel als Spiegel der Seele liest – jede Konstellation hat einen tieferen Sinn
  (Wachstum, Heilung, Loslassen, Reifen), nichts ist Zufall oder Strafe.
- Nie ein Problem ohne Lösung: Spricht ein Eintrag eine Schwierigkeit an (Spannung, Streit, Müdigkeit, Zweifel,
  ein schwieriger Aspekt, ein rückläufiger Planet, Vollmond-Unruhe), dann IMMER mit (1) dem tieferen Sinn – wozu
  diese Zeit dient – und (2) einem konkreten, sanften Weg für heute: ein kleines Ritual (Kerze, Atem, Wasser,
  Mondlicht, Aufschreiben, Dankbarkeit), ein Satz, den man sich sagt oder jemandem sagt, oder ein einfacher Schritt.
  Die Leserin geht getröstet, gestärkt und mit einer Idee weg, nie beunruhigt. Bei Reels ist die letzte
  Einblendung (Pointe) die Lösung oder die tröstende Einsicht – nicht das Problem; beim Drei-Zeichen-Check bekommt
  jedes Zeichen, das es schwer hat, seinen eigenen kleinen Rat.
- Sprache auf muttersprachlichem, literarischem Niveau: präzise Wörter, ein schöner Satzrhythmus, natürliche
  Wendungen der Zielsprache (nie übersetzt klingen), jeder Satz grammatisch und stilistisch einwandfrei.
- Intuitiver Aufbau (Feed-Post): Hook → Einsicht (mit der Wissensschicht) → ein kleiner, konkreter Schritt für
  heute → die Frage zum Kommentieren → die Handlungsaufforderung.
- Sei überraschend und kreativ: jeder Tag fühlt sich anders an (Erzählform unten). Sinnliche Details
  (Licht, Duft, Stoff, ein Geräusch), ein Augenzwinkern in kleiner Dosis, Sätze, die man einer Freundin
  weiterschickt. Kein Text darf austauschbar wirken.
- Weniger ist mehr: ein konkreter Gedanke, gut erzählt, statt drei angerissener. Keine Füllsätze
  (keine Einleitungen wie „Heute schauen wir uns … an“, keine Zusammenfassung am Ende, keine
  Wiederholung dessen, was schon im Bild steht). Jeder Satz muss etwas Neues bringen.
- Nicht ähnlich beginnen wie an den letzten Tagen (Liste der letzten Anfänge unten), keine
  Lieblingswörter wiederholen.
- Jeder Feed-Post und jede Reel-Bildunterschrift endet mit GENAU EINER leichten Frage zum Kommentieren,
  die man ohne Nachdenken beantwortet: ein Wort, ein Emoji, ein Buchstabe oder das eigene Sternzeichen
  (z. B. „Welches Zeichen bist du? Schreib dein Emoji in die Kommentare 👇“, „A oder B? Sag's mir unten“,
  „Tipp ein 🌙, wenn du das gespürt hast“). In der Sprache des Posts, natürlich formuliert, jeden Tag und
  in jedem Eintrag anders. Keine zweite Frage daneben, keine offenen Fragen, die einen Absatz verlangen.
  Die Frage ist IMMER positiv und öffentlich leicht zu beantworten – niemand soll vor allen etwas Privates
  verraten müssen: NIE nach Namen, Personen, Erlebnissen, Fehlern, Streit, Verletzungen oder „wann hast du
  zuletzt …“ fragen (falsch: „Wessen Name fiel dir zuerst ein?“, „Wann hast du zuletzt Nein gesagt zu jemandem,
  den du liebst?“). Richtig sind Fragen nach dem eigenen Zeichen, ein Emoji, Ja/Nein, A/B, oder ein schöner Wunsch
  zum Annehmen (z. B. „Schreib ✨, wenn du dieses Glück heute annimmst“, „Welches Zeichen bist du? Ich schicke dir
  einen Wunsch zurück“). Sie fühlt sich an wie ein Geschenk, nicht wie ein Verhör.
- Ein Post – eine Botschaft. Halte dich an das heutige Format und den heutigen Hook-Stil.
- Keine Links und keine @-Erwähnungen im Text (der Agent fügt den Link selbst an).
- Wiederhole keine Überschriften der letzten Tage (Liste unten).
- Wer zuschaut: laut den TikTok-Zahlen überwiegend Frauen (über 80 %). Schreib so, dass sie sich gemeint
  fühlen – bevorzugt Liebe und Beziehung, Gefühle, Freundschaft, Selbstwert und Selbstfürsorge, Bauchgefühl,
  Neuanfänge. Ohne Klischees („typisch Frau“), ohne Männer-Bashing, Paare und alle Menschen bleiben mitgemeint.
- Reels sollen Lust machen, morgen wiederzukommen: ein Thema, das man täglich verfolgen will (das eigene
  Zeichen, der Mond von heute). Zuschauer sollen merken, dass jeden Tag etwas Neues für sie kommt.
- Wer liest: rund 90 % Frauen, von Anfang 20 bis über 60. Jeden Tag stehen unten zwei Lebensphasen, die
  heute besonders angesprochen werden: Feed-Post und erstes Reel sprechen die erste an, Story und zweites Reel
  die zweite. Schreib so, dass sich Frauen in dieser Phase wiedererkennen – mit einem konkreten Moment aus
  ihrem Leben –, ohne das Alter zu nennen und ohne die anderen auszuschließen. Klug, warm, auf Augenhöhe:
  nie belehrend, keine Klischees, keine Altersklischees.
- "motiv": das Symbol im Bild – eines aus der Liste unten, passend zur Botschaft des Eintrags. Die vier
  Einträge eines Tages bekommen verschiedene Symbole.
- Kommt ein Zielgruppen-Profil mit: Greife auf, was diese Menschen beschäftigt und wie sie
  sprechen. Sinngemäß in der Sprache des Posts, nicht wörtlich zitieren, nichts dazuerfinden.
- Kommen Beispiele mit, die gut angekommen sind: Lerne aus Thema und Ton, kopiere sie nicht.

Liefere genau vier Einträge, in dieser Reihenfolge:
1. art "post", platform "instagram": Feed-Post. "text": Hook, dann 2 bis 3 kurze Absätze
   (insgesamt 40-90 Wörter, sehr kurze Absätze mit 1-2 Sätzen), dann die eine leichte Frage zum Kommentieren
   als eigener Absatz, zum Schluss die heutige Handlungsaufforderung mit „{link_in_bio}“. "bild_punkte": wenn der Post eine Liste
   ist (z. B. drei Sternzeichen, drei Schritte), bis zu 3 sehr kurze Punkte fürs Bild (je höchstens
   5 Wörter); beim Format „Mitmachen“ 2 bis 3 Antwortmöglichkeiten (je höchstens 5 Wörter, beim
   Sternzeichen-Check die drei Zeichen, z. B. „Skorpion: alles fühlen“) – sie stehen im Bild wie eine
   Umfrage A/B/C, und die Frage zum Kommentieren fragt dann nach dem Buchstaben; sonst [].
   "folien": das Karussell zum Durchwischen (nach dem Titelbild): genau 3 Folien, die den Post in
   Schritten erzählen – je "titel" (höchstens 6 Wörter; bei Sternzeichen der Name des Zeichens) und
   "text" (höchstens 14 Wörter, ein konkreter Gedanke – es steht groß im Bild). Jede Folie muss allein verständlich und
   wertvoll sein; die letzte macht neugierig auf das persönliche Horoskop.
2. art "reel", platform "tiktok": Kurzvideo (12-18 Sekunden, Text-Video ohne Sprecher).
   "skript": "hook" (erste Einblendung, höchstens 8 Wörter, stoppt das Scrollen; nennt IMMER mindestens ein
   Sternzeichen beim Namen, am besten am Anfang, z. B. „Skorpion, morgen beginnt in dir etwas Neues“ – Reels ohne
   Sternzeichen bekommen nur einen Bruchteil der Aufrufe),
   "einblendungen" (3 Texte, je höchstens 8 Wörter, erzählen die Botschaft in Schritten mit
   Spannung bis zum Schluss, der letzte ist die Pointe; bei Sternzeichen beginnt jede Einblendung
   mit dem Namen des Zeichens und einem Doppelpunkt), "szenen" (3 kurze Bild-Ideen, falls jemand selbst filmt),
   "schluss" (kurzer Schlusssatz, der neugierig auf das persönliche Horoskop macht, OHNE
   „{link_in_bio}“ oder andere Link-Hinweise – das Video zeigt darunter schon den Knopf, und es
   läuft auch auf Facebook). "text": Bildunterschrift mit Substanz (40-80 Wörter): erster Satz ein Hook, dann 2 bis 3
   sehr kurze Absätze, die mehr erzählen als das Video – ein konkretes Bild, die Einsicht des Tages und der stille,
   weise Gedanke; nennt das Video Sternzeichen, nenn sie auch im Text beim Namen. Zum Schluss als eigener Absatz die
   eine leichte Frage zum Kommentieren (anders als beim Feed-Post). "bild_punkte": [].
3. art "story", platform "instagram": ein kurzer Satz zur Tagesenergie plus eine Frage, auf die
   man per Nachricht antworten kann (z. B. „Antworte mit 🌙 oder ☀️“), höchstens 20 Wörter.
   "bild_punkte": genau 2 Antwortmöglichkeiten für die Frage, je höchstens 3 Wörter, beginnend mit
   einem passenden Emoji (z. B. „🔥 Ja, total“, „🌙 Eher nicht“) – sie stehen als Knöpfe im Bild.
4. art "reel", platform "tiktok": ZWEITES Reel des Tages – ein anderer Blickwinkel als
   das erste Reel, nicht dieselbe Botschaft und nicht derselbe Hook. IMMER ein Drei-Zeichen-Check (bringt mit Abstand
   die meisten Aufrufe und Kommentare – Leserinnen bleiben stehen, wenn sie ihr Zeichen sehen): drei Sternzeichen, die
   heute besonders betroffen sind, je Zeichen eine Einblendung. Der Hook beginnt GENAU so: die drei Namen mit Komma,
   dann ein Doppelpunkt, dann die konkrete Aussage, was die drei heute im Lebensthema des Tages verbindet
   (z. B. „Stier, Waage, Krebs: heute dreht sich alles ums Geld“) – die Namen erscheinen im Bild klein über dem Satz;
   nie bloß „das ist für euch“. Der "titel" sind die drei Namen. Als Frage IMMER „Welches Zeichen bist du?“ (nur das Zeichen
   schreiben), höchstens freundlich umformuliert – nie eine andere, persönlichere Frage. Etwa 15-18 Sekunden: genau 3 Einblendungen (je Zeichen eine), damit jede Leserin ihr Zeichen in Ruhe findet. "skript": "hook" (höchstens 8 Wörter), "einblendungen" (2 bis 3 Texte, je
   höchstens 8 Wörter, der letzte ist die Pointe), "szenen" (2 bis 3 kurze Bild-Ideen), "schluss" (kurz, ohne
   „{link_in_bio}“). "text": Bildunterschrift (35-70 Wörter): Hook, dann beim Drei-Zeichen-Check je Zeichen ein eigener
   kurzer Absatz mit dem Namen des Zeichens und einem treffenden, warmen Satz (sonst 2 kurze Absätze mit Einsicht und
   Gedanke), zum Schluss als eigener Absatz die eine leichte Frage zum Kommentieren (anders als bei Feed-Post und
   erstem Reel). "bild_punkte": [], "folien": [].

Für jeden Eintrag:
- "titel": Bild-Überschrift, höchstens 6 Wörter, ohne Hashtags und Emojis.
- "untertitel": der Kernsatz, höchstens 8 Wörter – steht beim Feed-Post im Bild unter der Überschrift: er
  ergänzt sie (die Einsicht oder das Versprechen des Posts), wiederholt sie nicht.
- "hashtags": 5 Hashtags in der Sprache des Posts, mit # (Instagram nimmt höchstens 5), so wie Menschen
  wirklich suchen – keine erfundenen Wortketten: zuerst die 2 zum heutigen Thema bzw. Sternzeichen
  (z. B. #scorpioseason, #venusretrograde, #vollmond), dann 1 großer (z. B. #astrology, #horoskop), dann
  2 Nischen-Hashtags (z. B. #lovehoroscope, #moonritual). Die wichtigsten zuerst (Facebook zeigt nur die
  ersten 3). Story: 2-3 Hashtags. Soraya ergänzt je Plattform selbst Sternzeichen und Such-Hashtags.
- Suchwörter (Instagram, TikTok und Pinterest sind auch Suchmaschinen): Der Text nennt natürlich, worum es
  geht – den Namen des Sternzeichens, „Horoskop“, „Vollmond“, „Venus rückläufig“ usw. –, am besten im Hook
  oder im zweiten Satz. Nie aufgezählt oder gestopft, es bleibt ein schöner Text.
- Bei "post" und "story" bleibt "skript" leer: hook "", szenen [], einblendungen [], schluss "".
- Bei "reel" und "story" ist "folien" []."""

_SKRIPT = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "szenen": {"type": "array", "items": {"type": "string"}},
        "einblendungen": {"type": "array", "items": {"type": "string"}},
        "schluss": {"type": "string"},
    },
    "required": ["hook", "szenen", "einblendungen", "schluss"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "thema": {"type": "string"},
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "art": {"type": "string", "enum": ["post", "reel", "story"]},
                    "platform": {"type": "string", "enum": ["instagram", "tiktok", "facebook"]},
                    "titel": {"type": "string"},
                    "untertitel": {"type": "string"},
                    "text": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "bild_punkte": {"type": "array", "items": {"type": "string"}},
                    "skript": _SKRIPT,
                    "folien": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"titel": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["titel", "text"], "additionalProperties": False}},
                    "motiv": {"type": "string", "enum": list(symbole.MOTIVE)},
                },
                "required": ["art", "platform", "titel", "untertitel", "text", "hashtags", "bild_punkte", "skript",
                             "folien", "motiv"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["thema", "posts"],
    "additionalProperties": False,
}


def sprachen() -> list[str]:
    """Sprachen des Tagesplans: Auswahl im Dashboard, sonst TAGESPLAN_SPRACHEN, sonst alle."""
    try:
        gewaehlt = db.lade_einstellung("tagesplan_sprachen", None)
    except Exception:
        gewaehlt = None
    if gewaehlt:
        return [s for s in SPRACHEN if s in gewaehlt] or ["de"]
    roh = os.environ.get("TAGESPLAN_SPRACHEN") or ",".join(SPRACHEN)
    gewaehlt = [norm(s) for s in roh.split(",") if s.strip()]
    return [s for s in SPRACHEN if s in gewaehlt] or ["de"]


def gesperrt() -> bool:
    """TAGESPLAN_AUTO=0 in Railway sperrt die Automatik unabhaengig vom Schalter."""
    return (os.environ.get("TAGESPLAN_AUTO") or "").strip() == "0"


def automatisch() -> bool:
    """Schalter im Dashboard (Standard: aus). Bei einem Datenbankfehler lieber nichts erstellen."""
    if gesperrt():
        return False
    try:
        return bool(db.lade_einstellung("tagesplan_auto", False))
    except Exception as e:
        print(f"[Tagesplan] Schalter nicht lesbar, Automatik bleibt aus: {e}", flush=True)
        return False


def sprachen_setzen(liste: list[str]) -> list[str]:
    gewaehlt = [s for s in SPRACHEN if s in {str(x).strip().lower()[:2] for x in liste}]   # Unbekanntes ignorieren
    if not gewaehlt:
        raise ValueError("Mindestens eine Sprache wählen.")
    db.setze_einstellung("tagesplan_sprachen", gewaehlt)
    return sprachen()


def automatik_setzen(an: bool) -> bool:
    db.setze_einstellung("tagesplan_auto", bool(an))
    return automatisch()


def startstunde() -> int:
    try:
        return max(0, min(23, int(os.environ.get("TAGESPLAN_STUNDE") or 6)))
    except ValueError:
        return 6


# Recherche-Land -> Sprache der Posts (welches Profil passt zu welcher Sprache)
LAND_SPRACHE = {"at": "de", "de": "de", "ch": "de", "hu": "hu", "it": "it", "uk": "en", "us": "en"}


def zielgruppen_je_sprache(zeilen: list[dict] | None = None) -> dict:
    """Welches Profil der Tagesplan je Sprache nutzt: markierte Profile (passendes Land
    zuerst, sonst das neueste markierte). Ist keines markiert, je Sprache automatisch:
    passendes Land, sonst ein Profil ohne Land, sonst keines -- so schreibt z. B. Englisch
    nicht fuer ein ungarisches Profil, nur weil es kein englisches gibt.
    Antwort: {sprache: {"id", "bereich", "automatisch"}} -- leer, wenn es keine Profile gibt."""
    if zeilen is None:
        zeilen = db.lade_zielgruppen(limit=50)
    markiert = [z for z in zeilen if z.get("im_tagesplan")]
    kandidaten = markiert or zeilen
    auswahl = {}
    for s in SPRACHEN:
        passend = [z for z in kandidaten if LAND_SPRACHE.get(z.get("land") or "") == s]
        ohne_land = [] if markiert else [z for z in kandidaten if not z.get("land")]
        z = (passend or ohne_land or (kandidaten if markiert else []) or [None])[0]
        if z:
            auswahl[s] = {"id": z["id"], "bereich": z["bereich"], "automatisch": not markiert}
    return auswahl


def _punkte(werte, n: int) -> str:
    if isinstance(werte, str):
        werte = [werte]
    werte = [str(w).strip() for w in (werte or []) if str(w).strip()][:n]
    return "; ".join(w[:160] for w in werte)


def zielgruppen_text(zeile: dict | None) -> str:
    """Kurzfassung eines Profils fuer den Prompt (nur das, was beim Schreiben hilft)."""
    if not zeile:
        return ""
    p = zeile.get("profil") or {}
    teile = [
        ("Wer sie sind", (p.get("wer_sind_sie") or "").strip()[:400]),
        ("Was sie beschäftigt", _punkte(p.get("beschaeftigt_sie") or p.get("beschäftigt_sie"), 4)),
        ("Ihre Worte", _punkte(p.get("sprache"), 6)),
        ("Was sie sich wünschen", _punkte(p.get("wuensche"), 3)),
        ("Worauf achten", _punkte(p.get("worauf_achten"), 3)),
    ]
    zeilen = [f"- {k}: {v}" for k, v in teile if v]
    if not zeilen:
        return ""
    return f"Zielgruppe (Recherche „{zeile.get('bereich')}“):\n" + "\n".join(zeilen)


# Erzaehlform des Tages: damit sich jeder Tag anders anfuehlt (Feed-Post und erstes Reel; der Rest frei)
ERZAEHLFORMEN = [
    ("geschichte", "Mini-Geschichte: eine kleine Szene mit einer Frau (ohne Namen) in einem konkreten Moment – "
                   "das Handy in der Hand, der Tee wird kalt –, dann die Wendung, die der Himmel heute bringt."),
    ("brief", "Brief an dich: wie eine kurze, warme Nachricht an eine Freundin („Liebe Waage, …“ oder „Du, …“), "
              "persönlich und leise."),
    ("bild", "Ein starkes Bild: eine einzige Metapher, die den ganzen Text trägt (z. B. der Mond als Lichtschalter, "
             "die Woche als offenes Fenster) – überraschend, nicht kitschig."),
    ("fakt", "Überraschender Fakt: ein echtes, wenig bekanntes Detail über Mond, Planeten oder Sternzeichen (nur "
             "Gesichertes, nichts erfinden) – und was es heute für dich bedeutet."),
    ("erlaubnis", "Erlaubnis: „Du darfst heute …“ – kleine, befreiende Erlaubnisse, die gut tun."),
    ("gegensatz", "Gegensatz: „Nicht … – sondern …“: ein verbreiteter Gedanke wird sanft umgedreht."),
    ("sinne", "Mit allen Sinnen: Licht, Duft, Stoff, Geräusch – der Text lässt den Moment fühlen, bevor er etwas erklärt."),
]


def erzaehlform(tag: date, sprache: str) -> tuple[str, str]:
    return random.Random(f"form-{tag.isoformat()}-{sprache}").choice(ERZAEHLFORMEN)


# Lebensthema des Tages: zwei verschiedene je Tag (Feed + 1. Reel / Story + 2. Reel), rotiert ueber zwei Wochen,
# damit nicht jeden Abend wieder "loslassen" oder "endlich sagen, was du fuehlst" kommt
LEBENSTHEMEN = [
    "Geld und Wert: was du dir gönnst, was du verlangst, was dir etwas wert ist",
    "Freundinnen: eine alte Freundschaft, eine Nachricht, die fällt, wer dich wirklich kennt",
    "Familie: Mutter, Schwester, Kinder, alte Rollen am Familientisch",
    "Arbeit und Berufung: ein Gespräch mit der Chefin, ein Projekt, Anerkennung, Pausen",
    "Körper und Rhythmus: Schlaf, Bewegung, Hunger, Müdigkeit – freundlich, ohne Heilversprechen",
    "Zuhause: ein Raum, aufräumen, ein Lieblingsplatz, Ordnung und Chaos",
    "Flirten und Verliebtsein: Blicke, Nachrichten, Herzklopfen, ein erstes Treffen",
    "Lange Partnerschaft: Alltag zu zweit, kleine Gesten, ein Streit und die Versöhnung",
    "Mut und Neuanfang: etwas zum ersten Mal tun, eine Entscheidung, ein Ja",
    "Kreativität und Freude: spielen, gestalten, tanzen, etwas nur für dich",
    "Erinnerungen: ein Lied, ein Geruch, ein Foto, wer du früher warst",
    "Grenzen: Nein sagen, Erwartungen anderer, Zeit für dich verteidigen",
    "Intuition und Träume: Bauchgefühl, Zeichen im Alltag, ein Traum, der nachklingt",
    "Reisen und Weite: Fernweh, ein Spaziergang, ein neuer Weg, raus aus der Routine",
]


def lebensthemen(tag: date, sprache: str) -> tuple[str, str]:
    import zlib
    n = len(LEBENSTHEMEN)
    i = (tag.toordinal() + zlib.crc32(sprache.encode())) % n
    return LEBENSTHEMEN[i], LEBENSTHEMEN[(i + 5) % n]


def botschaften_text(sprache: str) -> str:
    """Hooks und Kernsaetze der letzten Tage -- heute ein anderes Thema, nicht dieselbe Botschaft in neuen Worten."""
    try:
        zeilen = db.letzte_texte(sprache, 4)
    except Exception:  # noqa: BLE001
        return ""
    saetze = []
    for z in zeilen:
        sk = z.get("skript") or {}
        for t in [sk.get("hook"), *(sk.get("einblendungen") or [])[-1:], z.get("titel")]:
            t = str(t or "").strip()
            if t and t not in saetze:
                saetze.append(t)
    if not saetze:
        return ""
    return ("Botschaften der letzten Tage (Hooks, Pointen, Überschriften) – heute ein ANDERES Thema und eine andere "
            "Botschaft, nicht dasselbe in neuen Worten (z. B. nicht schon wieder „endlich sagen, was du fühlst“ oder "
            "„etwas loslassen“, wenn das schon dran war):\n" + "\n".join(f"- {t}" for t in saetze[:24]))


# Lebensphasen der Leserinnen: jeden Tag zwei im Wechsel (Feed + 1. Reel / Story + 2. Reel)
LEBENSPHASEN = [
    ("20er", "Anfang 20 bis Anfang 30: Dating und erste große Liebe, Selbstfindung, Studium oder Berufsstart, Freundinnen, "
             "der Druck, schon alles wissen zu müssen"),
    ("30er", "Mitte 30: Partnerschaft oder bewusst allein, Familie gründen oder nicht, Karriere und Balance, "
             "Selbstwert, wenig Zeit für sich"),
    ("40er", "Um die 40 und darüber: Neuanfang, Loslassen, Trennung oder neue Liebe, Kinder werden selbstständig, "
             "endlich die eigenen Wünsche ernst nehmen"),
    ("50plus", "50 und älter: Gelassenheit und Lebenserfahrung, neue Freiheit, Zeit für sich, Veränderungen des Körpers "
               "feinfühlig, Enkel, Freundschaften, späte Liebe"),
]


def lebensphasen(tag: date, reif: bool = False) -> tuple[tuple[str, str], tuple[str, str]]:
    """Zwei Lebensphasen fuer den Tag. reif: nur 40er/50plus (z. B. wenn die Sprache nur auf Facebook laeuft)."""
    if reif:
        a, b = LEBENSPHASEN[2], LEBENSPHASEN[3]
        return (a, b) if tag.toordinal() % 2 == 0 else (b, a)
    i = tag.toordinal() % len(LEBENSPHASEN)
    return LEBENSPHASEN[i], LEBENSPHASEN[(i + 2) % len(LEBENSPHASEN)]


# Wer auf welcher Plattform liest (aus den Kommentaren und Zahlen von Attilas Konten)
PUBLIKUM = {
    "facebook": "Facebook: vor allem Frauen zwischen etwa 45 und 70 – lebenserfahren, warmherzig, spirituell offen, "
                "kommentieren gern mit ihrem Sternzeichen. Themen: Partnerschaft nach vielen Jahren oder späte Liebe, "
                "Kinder und Enkel, Freundinnen, Dankbarkeit, innere Ruhe, Loslassen, gesunder Rhythmus (ohne "
                "Heilversprechen). Ruhige, würdevolle Sprache, keine Jugendsprache, kein „POV“, keine Anglizismen.",
    "tiktok": "TikTok: vor allem junge Frauen (etwa 18–35) – schnell, direkt, nahbar, gern ein Alltags-Moment zum "
              "Wiedererkennen (Dating, Freundschaft, Selbstwert, Neuanfang).",
    "instagram": "Instagram: Frauen etwa 25–45 – ästhetisch, nachdenklich, speichern gern Rituale und Erklärungen.",
    "pinterest": "Pinterest: Frauen, die nach Ritualen, Ideen und Sternzeichen-Wissen suchen und sie sich merken.",
    "linkedin": "LinkedIn: berufliches Umfeld – sachlich, klug, ohne Esoterik-Klischees.",
}


def publikum_fuer(sprache: str) -> list[str]:
    """Auf welchen eingeschalteten Plattformen diese Sprache heute gepostet wird (aus den Posten-Einstellungen)."""
    try:
        import posten
        e = posten.einstellungen()
    except Exception:  # noqa: BLE001 -- ohne Einstellungen: keine eigene Ansprache
        return []
    pls = [p for p, an in (e.get("plattformen") or {}).items() if an]
    tag = himmel.heute()
    return [p for p in pls if any(posten.sprache_fuer(tag, a, e, p) == sprache for a in posten.ARTEN)]


# erlaubte Endungen nach dem Zeichennamen (Ungarisch: Mérlegek, Bikának, Rákok ...; sonst Plural/Genitiv)
_ENDUNG = r"(?:ok|ek|ök|ak|nak|nek|knak|knek|ként|ban|ben|ra|re|hoz|hez|höz|on|en|ön|t|ot|et|öt|at|é|ék|s|'s|’s|e|i|n)?"


def zeichen_im_text(text: str) -> set[int]:
    """Welche Sternzeichen (Index 0-11) ein Text beim Namen nennt -- in allen vier Sprachen."""
    import re as _re
    import medien
    klein = str(text or "").lower()
    gefunden = set()
    lang = {"a": "á", "e": "é", "o": "ó", "ö": "ő"}          # Ungarisch: Bika -> Bikának, Skorpió bleibt
    for i, namen in enumerate(medien.ZEICHEN_NAMEN):
        namen = set(namen) | {n[:-1] + lang[n[-1]] for n in namen if n[-1] in lang}
        if any(_re.search(rf"(?<![\w]){_re.escape(n)}{_ENDUNG}(?![\w])", klein) for n in namen):
            gefunden.add(i)
    return gefunden


def zeichen_rotation(sprache: str) -> tuple[list[int], list[int]]:
    """(zuletzt im Mittelpunkt, laenger nicht dran) -- damit nicht jeden Tag dieselben Zeichen kommen."""
    try:
        zeilen = db.letzte_texte(sprache, 4)
    except Exception:  # noqa: BLE001
        return [], []
    zuletzt: dict[int, int] = {}                     # Zeichen -> wie oft in den letzten Tagen
    for z in zeilen:
        sk = z.get("skript") or {}
        teile = [z.get("titel"), (z.get("text") or "").split("\n")[0], sk.get("hook")] + list(sk.get("einblendungen") or [])
        for i in zeichen_im_text(" | ".join(str(t or "") for t in teile)):
            zuletzt[i] = zuletzt.get(i, 0) + 1
    oft = sorted(zuletzt, key=lambda i: -zuletzt[i])
    frei = [i for i in range(12) if i not in zuletzt]
    return oft, frei


def zeichen_text(sprache: str, info: dict | None = None) -> str:
    oft, frei = zeichen_rotation(sprache)
    heute = [z for z in (info or {}).get("zeichen_heute") or [] if z.get("punkte", 0) > 0]
    if heute:
        # echte Astrologie (Engine): welche Zeichen heute angesprochen sind -- davon die, die laenger nicht dran waren, zuerst
        kandidaten = heute[:7]
        kandidaten = [z for z in kandidaten if z["idx"] not in oft[:6]] + [z for z in kandidaten if z["idx"] in oft[:6]]
        zeilen = "\n".join(f"- {z['name']}: " + "; ".join(z["gruende"]) + (" (war zuletzt schon dran)" if z["idx"] in oft[:6] else "")
                           for z in kandidaten)
        return ("Welche Sternzeichen heute astrologisch wirklich angesprochen sind (aus der Engine berechnet, stärkste zuerst):\n"
                + zeilen + "\nFür den Drei-Zeichen-Check und das Mitmachen nimm drei Zeichen aus DIESER Liste – bevorzugt "
                "solche, die zuletzt nicht dran waren – und gib jedem Zeichen seinen echten Grund (z. B. „Stier: der Mond steht dir "
                "heute gegenüber …“, in eigenen Worten, ohne Fachjargon). Nichts dazuerfinden, was nicht in den Himmelsdaten steht.")
    if not oft:
        return ""
    from sprachen import zeichen as _name, _SIGN_KEYS
    namen = lambda xs: ", ".join(_name(_SIGN_KEYS[i], sprache) for i in xs)      # noqa: E731
    text = (f"Sternzeichen, die in den letzten Tagen schon im Mittelpunkt standen: {namen(oft)} – stell sie heute NICHT "
            "wieder in den Mittelpunkt (auch nicht im Drei-Zeichen-Check), selbst wenn sie gut ankamen.")
    if frei:
        text += (f" Länger nicht dran waren: {namen(frei)} – nimm für den Drei-Zeichen-Check und das Mitmachen bevorzugt "
                 "Zeichen von dieser Liste (passend zum heutigen Himmel, z. B. über das Element oder die Mondphase). "
                 "Über die Woche soll jedes der zwölf Zeichen drankommen.")
    return text


ART_NAMEN = {"story": "Story", "post": "Feed-Post", "reel": "erstes Reel", "reel2": "zweites Reel"}


def tageszeit(uhr: str) -> str:
    try:
        h = int(str(uhr).split(":")[0])
    except ValueError:
        return ""
    return ("früh am Morgen" if h < 9 else "am Vormittag" if h < 12 else "mittags" if h < 14
            else "am Nachmittag" if h < 18 else "am Abend" if h < 22 else "spät am Abend")


def zeiten_text() -> str:
    """Wann welcher Eintrag erscheint (Uhrzeiten aus den Posten-Einstellungen) -- damit kein Morgen-Post "heute Abend" sagt."""
    try:
        import posten
        z = posten.einstellungen().get("zeiten") or {}
    except Exception:  # noqa: BLE001
        return ""
    teile = [f"{ART_NAMEN[k]} {z[k]} Uhr ({tageszeit(z[k])})" for k in ("story", "reel", "post", "reel2") if z.get(k)]
    if not teile:
        return ""
    return ("Wann die Einträge erscheinen (Ortszeit Wien): " + ", ".join(teile) + ". Schreib passend zu dieser Tageszeit: "
            "ein Morgen-Post sagt nicht „heute Abend“, ein Abend-Post nicht „heute Morgen“. Morgens und mittags darf es um "
            "das gehen, was der Tag bringt. Abends ist der Tag fast vorbei: dann NICHT ankündigen, was „heute auf euch "
            "wartet“ oder „was euch heute erwartet“, sondern auf den Tag zurückblicken, den Abend und die Nacht begleiten "
            "oder neugierig auf morgen machen – immer über das heutige Lebensthema (nicht jeden Abend „loslassen“ oder "
            "„zur Ruhe kommen“); auch die Frage zum Kommentieren passt zur Abendstimmung.")


# Woerter fuer Abend/Nacht bzw. Morgen in den vier Sprachen (Pruefung: passt der Text zur Uhrzeit des Postens?)
_ABEND = re.compile(r"\b(heute abend|heute nacht|tonight|this evening|ma este|ma éjjel|ma éjszaka|estére|stasera|stanotte)\b",
                    re.IGNORECASE)
_MORGEN = re.compile(r"\b(heute morgen|heute früh|this morning|ma reggel|reggel óta|stamattina|questa mattina)\b", re.IGNORECASE)
TAGESZEIT = "Tageszeit passt nicht"


def platz_von(post: dict) -> str:
    return "reel2" if post.get("art") == "reel" and post.get("_reel_nr") == 2 else (post.get("art") or "post")


def tageszeit_befunde(post: dict, zeiten: dict) -> list[str]:
    """Ein Post, der frueh morgens erscheint, spricht nicht vom Abend (und umgekehrt)."""
    uhr = zeiten.get(platz_von(post))
    try:
        h = int(str(uhr).split(":")[0])
    except (TypeError, ValueError):
        return []
    sk = post.get("skript") or {}
    alles = " ".join([post.get("titel") or "", post.get("text") or "", sk.get("hook") or ""] + list(sk.get("einblendungen") or []))
    if h < 14 and _ABEND.search(alles):
        return [f"{TAGESZEIT}: erscheint um {uhr} Uhr, spricht aber vom Abend („{_ABEND.search(alles).group(0)}“) – "
                "schreib für den Morgen bzw. den ganzen Tag"]
    if h >= 17 and _MORGEN.search(alles):
        return [f"{TAGESZEIT}: erscheint um {uhr} Uhr, spricht aber vom Morgen („{_MORGEN.search(alles).group(0)}“)"]
    return []


STIL = "Stil"
_PROZENT = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|százalék\w*|prozent|percent|per ?cento)", re.IGNORECASE)
_FALSCHES_WORT = {"hu": re.compile(r"\bmelyik jel\b|\bcsillagjel\b|\bjeled\b", re.IGNORECASE)}   # richtig: jegy
_WOERTLICH = {"hu": re.compile(r"\bszó szerint\b", re.IGNORECASE), "de": re.compile(r"\bbuchstäblich\b", re.IGNORECASE),
              "en": re.compile(r"\bliterally\b", re.IGNORECASE), "it": re.compile(r"\bletteralmente\b", re.IGNORECASE)}


def stil_befunde(post: dict, sprache: str) -> list[str]:
    """Fest gepruefte Stilfehler, die Claude trotz Regel immer wieder macht -> ein Korrekturdurchgang."""
    sk = post.get("skript") or {}
    alles = " ".join([post.get("text") or "", sk.get("hook") or ""] + list(sk.get("einblendungen") or []))
    out = []
    m = _PROZENT.search(alles)
    if m:
        out.append(f"{STIL}: Prozentzahl im Text („{m.group(0)}“) – sag es als Bild")
    f = _FALSCHES_WORT.get(sprache)
    if f and f.search(alles):
        out.append(f"{STIL}: „{f.search(alles).group(0)}“ – das Sternzeichen heißt auf Ungarisch „jegy“ / „csillagjegy“")
    w = _WOERTLICH.get(sprache)
    if w and w.search(alles):
        out.append(f"{STIL}: „{w.search(alles).group(0)}“ (englisch „literally“) – weglassen")
    return out


ZEICHEN_FEHLT = "Sternzeichen fehlt"


def zeichen_befunde(post: dict) -> list[str]:
    """Reels mit Sternzeichen-Namen laufen viel besser (Facebook-Zahlen 08.11.: 8.600 statt 250 Aufrufe):
    erstes Reel nennt im Hook mindestens ein Zeichen, das zweite ist ein Drei-Zeichen-Check."""
    if post.get("art") != "reel":
        return []
    hook = (post.get("skript") or {}).get("hook") or ""
    n = len(zeichen_im_text(hook))
    if post.get("_reel_nr") == 2 and n < 3:
        return [f"{ZEICHEN_FEHLT}: das zweite Reel ist ein Drei-Zeichen-Check – der Hook beginnt mit drei Sternzeichen "
                "(„Name, Name, Name: Aussage“)"]
    if post.get("_reel_nr") != 2 and n < 1:
        return [f"{ZEICHEN_FEHLT}: der Hook des ersten Reels nennt kein Sternzeichen beim Namen"]
    return []


def _posten_zeiten() -> dict:
    try:
        import posten
        return posten.einstellungen().get("zeiten") or {}
    except Exception:  # noqa: BLE001
        return {}


def nur_facebook(plattformen: list[str] | None) -> bool:
    return bool(plattformen) and set(plattformen) == {"facebook"}


# Einmal pro Woche (Sonntag) zeigt das zweite Reel eine Funktion der App -- weiter als Drei-Zeichen-Check,
# denn das Format bringt die meisten Aufrufe. Die Funktion wechselt jede Woche.
APP_REEL_TAG = 6                       # Sonntag
APP_FUNKTIONEN = [
    ("mondzeichen", "dein Mondzeichen in 10 Sekunden (Schnellstart: nur Geburtsdatum, ohne Konto) – zeigt, wie man "
                    "fühlt, was man braucht, warum man anders tickt als das Sonnenzeichen sagt"),
    ("partner", "der Partner-Vergleich in Prozent – wie gut zwei Menschen wirklich zusammenpassen (Liebe, Alltag, Streit)"),
    ("horoskop", "das persönliche Tageshoroskop – jeden Tag aus dem eigenen Geburtshoroskop berechnet, nicht nur fürs Sternzeichen (auch Woche und Monat)"),
    ("radix", "das Geburtshoroskop mit Deutung – Aszendent, Mond und alle Planeten, Kapitel für Kapitel erklärt"),
]


def app_funktion(tag: date) -> tuple[str, str] | None:
    """Am App-Reel-Tag die Funktion dieser Woche, sonst None."""
    if tag.weekday() != APP_REEL_TAG:
        return None
    return APP_FUNKTIONEN[tag.isocalendar()[1] % len(APP_FUNKTIONEN)]


def app_reel_text(tag: date) -> str:
    f = app_funktion(tag)
    if not f:
        return ""
    return ("HEUTE ist das zweite Reel das wöchentliche App-Reel: weiter ein Drei-Zeichen-Check (Hook „Name, Name, Name: "
            f"Aussage“), aber die drei Zeichen führen zu einer Funktion der Soraya-App: {f[1]}. Die Einblendungen "
            "zeigen je Zeichen, was diese Funktion gerade ihm verrät (konkret, neugierig machend, nichts versprechen, was die "
            "App nicht kann); die letzte Einblendung nennt die Funktion beim Namen. \"schluss\": eine Einladung, es selbst "
            "auszuprobieren (gratis, ohne Link-Hinweis – das Schlussbild zeigt, wo man die App findet). Bildunterschrift: "
            "wie beim Drei-Zeichen-Check, dazu ein Satz, wie einfach es geht. Kein Werbeton – neugierig und warm.")


def publikum_text(plattformen: list[str]) -> str:
    zeilen = [PUBLIKUM[p] for p in plattformen if p in PUBLIKUM]
    if not zeilen:
        return ""
    return ("Wo diese Texte erscheinen und wer dort liest – schreib genau für diese Menschen (Ton, Themen, Beispiele):\n"
            + "\n".join(f"- {z}" for z in zeilen))


def _frage(info: dict, sprache: str, bisherige: list[str], zielgruppe: dict | None, thema: dict,
           vorbilder: list[str], erkenntnis: str = "", anfaenge: list[str] | None = None,
           phasen: tuple | None = None, form: tuple | None = None, zuletzt_motive: list[str] | None = None,
           publikum: str = "", zeiten: str = "", zeichen_hinweis: str = "", themen: tuple | None = None,
           botschaften: str = "") -> str:
    profil = zielgruppen_text(zielgruppe)
    phasen = phasen or lebensphasen(himmel.heute())
    themen = themen or lebensthemen(himmel.heute(), sprache)
    return (
        "Himmelsdaten für den Tag des Posts (bereits in der Zielsprache benannt):\n"
        f"{himmel.als_text(info)}\n\n"
        f"{redaktion.thema_text(thema, LINK_IN_BIO[sprache])}\n\n"
        + (f"{publikum}\n\n" if publikum else "")
        + (f"{zeiten}\n\n" if zeiten else "")
        + (f"{zeichen_hinweis}\n\n" if zeichen_hinweis else "")
        + (f"{profil}\n\n" if profil else "")
        + ("Diese eigenen Posts kamen zuletzt am besten an (Besuche, neue Konten, Reaktionen):\n"
           + "\n".join(f"- {v}" for v in vorbilder) + "\n\n" if vorbilder else "")
        + (f"{erkenntnis}\n\n" if erkenntnis else "")
        + "Überschriften der letzten Tage (nicht wiederholen):\n"
        + ("\n".join(f"- {t}" for t in bisherige) if bisherige else "- (noch keine)")
        + ("\n\nAnfänge (erste Zeilen) der letzten Tage – nicht ähnlich beginnen:\n"
           + "\n".join(f"- {a}" for a in anfaenge) if anfaenge else "")
        + (f"\n\n{botschaften}" if botschaften else "")
        + "\n\nLebensthema heute – darum dreht sich der konkrete Moment, verbunden mit dem Himmel (auch beim "
          "Drei-Zeichen-Check: was die drei Zeichen in diesem Bereich heute erleben):\n"
        + f"1. (Feed-Post, erstes Reel) {themen[0]}\n2. (Story, zweites Reel) {themen[1]}"
        + f"\n\nErzählform heute (Feed-Post und erstes Reel): {(form or ERZAEHLFORMEN[0])[1]}"
        + "\n\nLebensphasen heute:\n"
        + f"1. (Feed-Post, erstes Reel) {phasen[0][1]}\n2. (Story, zweites Reel) {phasen[1][1]}"
        + "\n\nSymbole für \"motiv\" (jeder der Posts bekommt ein ANDERES Symbol; nimm auch gern die selteneren):\n"
        + "\n".join(f"- {k}: {v}" for k, v in symbole.BEDEUTUNG.items())
        + (f"\nZuletzt benutzt (diesmal möglichst andere): {', '.join(dict.fromkeys(zuletzt_motive))}" if zuletzt_motive else "")
        + f"\n\n{sprach_anweisung(sprache)}"
    )


def _aufbereiten(daten: dict, sprache: str, thema_name: str = "") -> list[dict]:
    posts, reels = [], 0
    for i, p in enumerate(daten.get("posts", [])[:4]):
        skript = p.get("skript") or {}
        punkte = [x.strip() for x in (p.get("bild_punkte") or []) if x and x.strip()][:3]
        folien = [{"titel": str(f.get("titel") or "").strip()[:80], "text": str(f.get("text") or "").strip()[:260]}
                  for f in (p.get("folien") or []) if str(f.get("titel") or f.get("text") or "").strip()][:4]
        posts.append({
            **{k: v for k, v in p.items() if k not in ("bild_punkte", "folien", "motiv")},
            "_motiv": p.get("motiv"),
            "sprache": sprache,
            "skript": skript if p.get("art") == "reel" and (skript.get("hook") or skript.get("szenen")) else None,
            "_bild_punkte": punkte if p.get("art") == "post" else (punkte[:2] if p.get("art") == "story" and len(punkte) >= 2 else []),
            "_folien": folien if p.get("art") == "post" and len(folien) >= 2 else [],
        })
        if p.get("art") == "reel":
            reels += 1
            if reels > 2:                       # hoechstens zwei Reels am Tag
                posts.pop()
                continue
            if reels == 2:
                posts[-1]["_reel_nr"] = 2
        if p.get("art") in ("post", "reel"):
            # genau eine leichte Frage zum Kommentieren -- falls Claude sie vergessen hat
            umfrage = len(punkte) if p.get("art") == "post" and thema_name == "Mitmachen" else 0
            posts[-1]["text"] = redaktion.mit_kommentar_frage(
                posts[-1].get("text") or "", sprache, f"{sprache}-{thema_name}-{i}-{p.get('titel') or ''}", umfrage)
    return posts


def schreibe_posts(info: dict, sprache: str, bisherige: list[str], zielgruppe: dict | None = None,
                   thema: dict | None = None, vorbilder: list[str] | None = None, erkenntnis: str = "",
                   anfaenge: list[str] | None = None, zuletzt_motive: list[str] | None = None,
                   plattformen: list[str] | None = None) -> list[dict]:
    """Ein Claude-Aufruf: die vier Eintraege des Tages in einer Sprache. Bei schweren Befunden
    der Qualitaetspruefung (z. B. falsche Sprache, heikle Versprechen) genau ein Korrekturdurchgang."""
    tag = date.fromisoformat(info["datum"]) if info.get("datum") else himmel.heute()
    thema = thema or redaktion.wochenthema(tag, info)
    system = SYSTEM_PROMPT.replace("{link_in_bio}", LINK_IN_BIO[sprache])
    frage = _frage(info, sprache, bisherige, zielgruppe, thema, vorbilder or [], erkenntnis, anfaenge,
                   lebensphasen(tag, reif=nur_facebook(plattformen)), erzaehlform(tag, sprache), zuletzt_motive,
                   publikum_text(plattformen or []), zeiten_text(), zeichen_text(sprache, info),
                   lebensthemen(tag, sprache), "\n\n".join(t for t in (botschaften_text(sprache), app_reel_text(tag)) if t))
    # vier ausfuehrliche Eintraege + Denken: grosszuegiges Limit, damit nichts abgeschnitten wird
    posts = _aufbereiten(frage_json(system, frage, SCHEMA, effort="high", max_tokens=48000), sprache, thema["name"])
    zeiten = _posten_zeiten()
    pruefe = lambda p: redaktion.pruefe_post(p, sprache) + tageszeit_befunde(p, zeiten) + stil_befunde(p, sprache) \
        + zeichen_befunde(p)  # noqa: E731
    befunde = {i: pruefe(p) for i, p in enumerate(posts)}
    anzahl = lambda bf: sum(1 for b in bf.values() if hart(b))      # noqa: E731
    if anzahl(befunde):
        hinweis = "\n".join(f"- {posts[i].get('art')}: {'; '.join(b)}" for i, b in befunde.items() if b)
        korrigiert = _aufbereiten(frage_json(
            system, frage + "\n\nDein erster Entwurf hatte diese Probleme, vermeide sie:\n" + hinweis,
            SCHEMA, effort="high", max_tokens=48000), sprache, thema["name"])
        if korrigiert:
            neu = {i: pruefe(p) for i, p in enumerate(korrigiert)}
            if anzahl(neu) <= anzahl(befunde):          # nur nehmen, wenn es nicht schlechter geworden ist
                posts, befunde = korrigiert, neu
    if not posts:
        raise RuntimeError("Claude hat keine Posts geliefert.")
    # Was jetzt noch hart daneben ist (z. B. 2. Reel ohne drei Zeichen, Morgen-Post mit "heute Abend"):
    # nur diesen einen Eintrag gezielt nachbessern lassen, hoechstens zweimal
    for i in range(len(posts)):
        for _ in range(NACHBESSERN_MAX):
            if not hart(befunde[i]):
                break
            try:
                neu = nachbessern(system, frage, posts[i], befunde[i], sprache, thema["name"])
            except Exception as ex:  # noqa: BLE001 -- dann bleibt der Eintrag, wie er ist
                print(f"[Tagesplan] Nachbessern {sprache} {posts[i].get('art')}: {ex}", flush=True)
                break
            if neu:
                posts[i], befunde[i] = neu, pruefe(neu)
    # Muttersprachliches Lektorat (Standard: Ungarisch) -- danach Pruefung neu; bringt es einen harten Fehler
    # zurueck (z. B. die drei Zeichen aus dem Hook entfernt), gilt fuer diesen Eintrag die Fassung davor
    vorher = copy.deepcopy(posts)
    if lektorat.pruefen(posts, sprache):
        for i, p in enumerate(posts):
            b = pruefe(p)
            if hart(b) and not hart(befunde[i]):
                posts[i] = vorher[i]
            else:
                befunde[i] = b
    for i, p in enumerate(posts):
        p["_pruefung"] = befunde.get(i) or []
        p["_thema"] = thema["name"]
    return posts


NACHBESSERN_MAX = 2


def hart(befunde: list[str]) -> bool:
    """Befunde, die einen neuen Versuch rechtfertigen (ohne das Posten zu blockieren, ausser redaktion.schwer)."""
    return redaktion.schwer(befunde) or redaktion.leer(befunde) or any(
        x.startswith((TAGESZEIT, STIL, ZEICHEN_FEHLT)) for x in befunde)


def nachbessern(system: str, frage: str, post: dict, befunde: list[str], sprache: str, thema_name: str) -> dict | None:
    """Ein einzelner Eintrag wird gezielt ueberarbeitet (kleiner, guenstiger Aufruf)."""
    item = SCHEMA["properties"]["posts"]["items"]
    schema = {"type": "object", "properties": {"post": item}, "required": ["post"], "additionalProperties": False}
    roh = {k: v for k, v in post.items() if not k.startswith("_") and k != "sprache"}
    roh["skript"] = post.get("skript") or {"hook": "", "szenen": [], "einblendungen": [], "schluss": ""}
    roh["bild_punkte"], roh["folien"], roh["motiv"] = post.get("_bild_punkte") or [], post.get("_folien") or [], post.get("_motiv") or ""
    welcher = "das ZWEITE Reel des Tages" if post.get("_reel_nr") == 2 else f"der Eintrag „{post.get('art')}“"
    auftrag = (f"\n\nÜberarbeite jetzt NUR {welcher}. Er hat diese Probleme – behebe sie vollständig und behalte alles "
               "andere (Thema, Ton, Länge, Sprache) bei:\n- " + "\n- ".join(befunde)
               + "\n\nDer Eintrag bisher (JSON):\n" + json.dumps(roh, ensure_ascii=False))
    d = frage_json(system, frage + auftrag, schema, effort="medium", max_tokens=16000)
    neu = _aufbereiten({"posts": [d.get("post") or {}]}, sprache, thema_name)
    if not neu or neu[0].get("art") != post.get("art"):
        return None
    if post.get("_reel_nr"):
        neu[0]["_reel_nr"] = post["_reel_nr"]
    return neu[0]


def _zielgruppe_fuer(sprache: str) -> dict | None:
    """Das Profil fuer diese Sprache; ein Datenbankfehler hier soll den Tagesplan nicht stoppen."""
    try:
        zeilen = db.lade_zielgruppen(limit=50)
        wahl = zielgruppen_je_sprache(zeilen).get(sprache)
        return next((z for z in zeilen if wahl and z["id"] == wahl["id"]), None)
    except Exception as e:
        print(f"[Tagesplan] Zielgruppe nicht geladen: {e}", flush=True)
        return None


def erstelle(sprache: str, *, tag: date | None = None, erzwingen: bool = False, manuell: bool = False) -> dict:
    """Erstellt den Tagesplan fuer eine Sprache (falls noch nicht vorhanden)."""
    sprache = norm(sprache)
    tag = tag or himmel.heute()
    if not db.beanspruche_tagesplan(tag, sprache, erzwingen=erzwingen, manuell=manuell):
        return {"sprache": sprache, "status": "schon_da"}
    try:
        # Bei "Alle neu erstellen" werden die alten Entwuerfe erst NACH dem erfolgreichen Schreiben ersetzt --
        # geht das Schreiben schief, bleiben sie erhalten (vorher waren sie dann einfach weg)
        info = himmel.aufbereiten(himmel.hole_himmel(tag), tag, sprache)
        zielgruppe = _zielgruppe_fuer(sprache)
        thema = redaktion.wochenthema(tag, info)
        try:
            bewertet = redaktion.bewerte(db.lade_post)
        except Exception:
            bewertet = []
        # gleicher Tag und gleiche Sprache -> gleiche Wahl (auch beim Neu-Erstellen nachvollziehbar)
        redaktion.selbsttest(thema, bewertet, random.Random(f"{tag.isoformat()}-{sprache}"))
        vorbilder = redaktion.gut_angekommen(db.lade_post, sprache, bewertet=bewertet)
        erkenntnis = redaktion.erkenntnis_text(redaktion.erkenntnisse(bewertet), thema["name"])
        try:
            anfaenge = db.letzte_anfaenge(sprache)
        except Exception:
            anfaenge = []
        try:
            zuletzt_motive = db.letzte_motive(sprache)
        except Exception:
            zuletzt_motive = []
        plattformen = publikum_fuer(sprache)
        posts = schreibe_posts(info, sprache, db.letzte_titel(sprache), zielgruppe, thema, vorbilder, erkenntnis,
                               anfaenge, zuletzt_motive, plattformen)
        if erzwingen:
            db.loesche_tagesplan_entwuerfe(tag, sprache)
            # was schon gepostet ist (oder gerade rausgeht), bleibt -- fuer diesen Platz keinen zweiten Entwurf anlegen
            belegt = {(q.get("art"), (q.get("meta") or {}).get("reel_nr") == 2)
                      for q in db.lade_posts(von=tag, bis=tag) if q.get("sprache") == sprache and q.get("quelle") == "himmel"}
            posts = [p for p in posts if (p.get("art"), p.get("_reel_nr") == 2) not in belegt]
        try:   # Serien-Nummer: der wievielte Post dieses Formats in dieser Sprache (z. B. "Ritual · Folge 12")
            folge = None if thema["name"].startswith("Großes Ereignis") else db.zaehle_format(sprache, thema["name"], tag) + 1
        except Exception:
            folge = None
        gespeichert, phasen = [], lebensphasen(tag, reif=nur_facebook(plattformen))
        # Symbole: heute jedes nur einmal; die von gestern/vorgestern moeglichst auch nicht (wenn genug andere passen)
        heute_motive: set[str] = set()
        for nr, p in enumerate(posts):
            meta = himmel.bild_meta(info) | {"thema": p.pop("_thema"), "pruefung": p.pop("_pruefung"),
                                             "hook_stil": thema["hook_stil"]["schluessel"],
                                             "aufforderung": thema["aufforderung"]["schluessel"]}
            korrigiert = p.pop("_lektorat", [])
            if korrigiert:
                meta["lektorat"] = korrigiert   # vom Sprach-Lektorat geaendert (alt → neu)
            punkte = p.pop("_bild_punkte", [])
            if punkte:
                meta["bild_punkte"] = punkte
            folien = p.pop("_folien", [])
            if folien:
                meta["folien"] = folien
            if folge:
                meta["folge"] = folge
            if p.pop("_reel_nr", None) == 2:
                meta["reel_nr"] = 2               # zweites Reel des Tages (eigene Uhrzeit beim Posten)
                if app_funktion(tag):
                    meta["app_reel"] = app_funktion(tag)[0]   # woechentliches App-Reel (Funktion der Woche)
            if thema.get("variante"):
                meta["variante"] = thema["variante"]
            if zielgruppe:
                meta["zielgruppe"] = zielgruppe["bereich"]
            meta["motiv"] = symbole.waehle(p.pop("_motiv", None), meta["thema"], tag.toordinal(), p.get("art"), nr,
                                           meiden=heute_motive | set(zuletzt_motive[:8]))
            heute_motive.add(meta["motiv"])
            zweite = p.get("art") == "story" or meta.get("reel_nr") == 2
            meta["lebensphase"] = phasen[1 if zweite else 0][0]
            if not zweite and p.get("art") in ("post", "reel"):
                meta["erzaehlform"] = erzaehlform(tag, sprache)[0]
            gespeichert += db.speichere_posts([p], quelle="himmel", geplant_fuer=tag, meta=meta)
        db.tagesplan_fertig(tag, sprache, info)
        print(f"[Tagesplan] {tag} {sprache}: {len(gespeichert)} Posts", flush=True)
        return {"sprache": sprache, "status": "fertig", "posts": len(gespeichert)}
    except Exception as e:
        db.tagesplan_fehler(tag, sprache, str(e))
        print(f"[Tagesplan] {tag} {sprache}: FEHLER {e}", flush=True)
        return {"sprache": sprache, "status": "fehler", "fehler": str(e)}


def erstelle_im_hintergrund(liste: list[str], *, erzwingen: bool = False) -> None:
    """Fuer den Knopf im Dashboard: laeuft weiter, waehrend die Seite den Stand abfragt."""
    def lauf():
        for s in liste:
            erstelle(s, erzwingen=erzwingen, manuell=True)
    threading.Thread(target=lauf, name="tagesplan-knopf", daemon=True).start()


_vorplanen_sperre = threading.Lock()


def vorplanen(tage: int = 7, liste: list[str] | None = None) -> dict:
    """Die naechsten Tage (ab morgen) im Hintergrund vorplanen, Tag fuer Tag, damit jeder Tag
    die Ueberschriften der Vortage kennt. Schon erstellte Tage kosten nichts (werden uebersprungen)."""
    tage = max(1, min(int(tage), 14))
    liste = liste or sprachen()
    erster = himmel.heute() + timedelta(days=1)
    daten = [erster + timedelta(days=i) for i in range(tage)]
    if not _vorplanen_sperre.acquire(blocking=False):
        return {"gestartet": False, "grund": "Vorplanen läuft bereits."}

    def lauf():
        try:
            for tag in daten:
                for s in liste:
                    erstelle(s, tag=tag, manuell=True)
        finally:
            _vorplanen_sperre.release()
    threading.Thread(target=lauf, name="tagesplan-vorplanen", daemon=True).start()
    return {"gestartet": True, "von": daten[0].isoformat(), "bis": daten[-1].isoformat(), "sprachen": liste}


def pruefe_faellige(jetzt_stunde: int | None = None) -> list[dict]:
    """Einmal pro Durchlauf des Zeitplans: fehlende Tagesplaene von heute und morgen erstellen.
    Morgen wird schon heute geschrieben -- so bleibt ein ganzer Abend Zeit zum Pruefen und Stoppen."""
    if not automatisch():
        return []
    stunde = jetzt_stunde if jetzt_stunde is not None else himmel.stunde_jetzt()
    if stunde < startstunde():
        return []
    heute = himmel.heute()
    return [erstelle(s, tag=t) for t in (heute, heute + timedelta(days=1)) for s in sprachen()]


def zeitplan_starten(intervall_sekunden: int = 600) -> None:
    """Hintergrund-Schleife: alle 10 Minuten nachsehen, ob der Tagesplan fehlt."""
    def schleife():
        time.sleep(20)  # dem Start Zeit lassen (Datenbank, Healthcheck)
        while True:
            try:
                pruefe_faellige()
            except Exception as e:
                print(f"[Tagesplan] Zeitplan-Fehler: {e}", flush=True)
            time.sleep(intervall_sekunden)
    threading.Thread(target=schleife, name="tagesplan-zeitplan", daemon=True).start()
