"""
Vordefinierte Recherche-Bereiche fuer die Zielgruppen-Analyse.
Jeder Bereich hat Suchbegriffe, die typische Fragen echter Menschen abbilden.
"""

BEREICHE = {
    "beziehung": {
        "titel": "Liebe & Beziehung",
        "begriffe": [
            "passt mein sternzeichen zu ihm",
            "synastrie partner horoskop deutung",
            "astrologie beziehung probleme",
        ],
    },
    "selbstfindung": {
        "titel": "Selbstfindung & Persoenlichkeit",
        "begriffe": [
            "geburtshoroskop was sagt es ueber mich",
            "aszendent bedeutung persoenlichkeit",
            "astrologie selbsterkenntnis",
        ],
    },
    "beruf": {
        "titel": "Beruf & Entscheidungen",
        "begriffe": [
            "astrologie berufswahl entscheidung",
            "guenstiger zeitpunkt entscheidung astrologie",
            "horoskop karriere deutung",
        ],
    },
    "mond": {
        "titel": "Mondphasen & Rituale",
        "begriffe": [
            "vollmond ritual anleitung",
            "neumond wuensche schreiben",
            "mondkalender bedeutung alltag",
        ],
    },
    "einsteiger": {
        "titel": "Astrologie-Einsteiger",
        "begriffe": [
            "astrologie fuer anfaenger erklaert",
            "was bedeutet mein sternzeichen wirklich",
            "horoskop lesen lernen",
        ],
    },
    "skeptiker": {
        "titel": "Skeptiker & Kritik",
        "begriffe": [
            "ist astrologie unsinn",
            "warum glauben menschen an horoskope",
            "astrologie kritik wissenschaft",
        ],
    },
    "apps": {
        "titel": "Astrologie-Apps (Wettbewerb)",
        "begriffe": [
            "beste astrologie app deutsch",
            "horoskop app erfahrungen bewertung",
            "astrologie app kostenlos vergleich",
        ],
    },
}


def begriffe_fuer(bereich: str) -> list[str]:
    """Liefert Suchbegriffe: entweder vordefiniert oder aus dem freien Text."""
    schluessel = (bereich or "").strip().lower()
    if schluessel in BEREICHE:
        return BEREICHE[schluessel]["begriffe"]
    # Freier Bereich: daraus sinnvolle Suchvarianten bauen
    return [
        f"{bereich} astrologie",
        f"{bereich} horoskop bedeutung",
        f"{bereich} erfahrungen",
    ]
