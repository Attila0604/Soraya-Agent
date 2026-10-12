"""
Web-Recherche ueber Claude — ohne zweiten Dienst.
Claude sucht selbst im Netz und sammelt die Fundstuecke.
Laeuft ueber denselben Anthropic-Key, den der Content-Agent nutzt.
"""

from claude import suche_text

SAMMEL_PROMPT = """Du bist Rechercheur. Deine Aufgabe ist SAMMELN, nicht analysieren.

Suche im Netz zu den vorgegebenen Fragen und notiere, was du findest:
- Welche Fragen stellen Menschen zu diesem Thema?
- Welche Formulierungen und Begriffe benutzen sie selbst?
- Welche Sorgen, Wünsche oder Kritikpunkte tauchen auf?
- Was schreiben Foren, Ratgeber und Erfahrungsberichte?

Gib eine nüchterne Liste von Fundstücken zurück, Stichpunkt für Stichpunkt.
Keine Zusammenfassung, keine Empfehlungen, keine eigene Meinung.
Wenn du zu etwas nichts findest, schreib das dazu."""

LAENDER = {"at": "Österreich", "de": "Deutschland", "ch": "Schweiz",
           "hu": "Ungarn", "it": "Italien", "uk": "Vereinigtes Königreich", "us": "USA"}


def quelle_websuche(begriffe: list[str], land: str = "at", max_zeichen: int = 9000) -> str:
    fragen = "\n".join(f"- {b}" for b in begriffe if b.strip())
    land_text = LAENDER.get(land, land)
    inhalt = suche_text(
        SAMMEL_PROMPT,
        f"Markt: Schwerpunkt {land_text}.\n\nRecherchiere zu diesen Fragen:\n{fragen}",
        max_suchen=6,
    )
    return inhalt[:max_zeichen]
