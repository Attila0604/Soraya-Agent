"""
Vordefinierte Recherche-Bereiche.
Jeder Bereich bringt eigene Suchbegriffe (Google/Reddit) und Hashtags
(Instagram/TikTok) mit.
"""

BEREICHE = {
    "beziehung": {
        "titel": "Liebe & Beziehung",
        "begriffe": [
            "passt mein sternzeichen zu ihm",
            "synastrie partner horoskop deutung",
        ],
        "hashtags": ["synastrie", "sternzeichenliebe"],
    },
    "selbstfindung": {
        "titel": "Selbstfindung & Persoenlichkeit",
        "begriffe": [
            "geburtshoroskop was sagt es ueber mich",
            "aszendent bedeutung persoenlichkeit",
        ],
        "hashtags": ["geburtshoroskop", "selbstfindung"],
    },
    "beruf": {
        "titel": "Beruf & Entscheidungen",
        "begriffe": [
            "astrologie berufswahl entscheidung",
            "horoskop karriere deutung",
        ],
        "hashtags": ["astrologie", "karriere"],
    },
    "mond": {
        "titel": "Mondphasen & Rituale",
        "begriffe": [
            "vollmond ritual anleitung",
            "neumond wuensche schreiben",
        ],
        "hashtags": ["vollmond", "neumond"],
    },
    "einsteiger": {
        "titel": "Astrologie-Einsteiger",
        "begriffe": [
            "astrologie fuer anfaenger erklaert",
            "horoskop lesen lernen",
        ],
        "hashtags": ["astrologie", "sternzeichen"],
    },
    "skeptiker": {
        "titel": "Skeptiker & Kritik",
        "begriffe": [
            "ist astrologie unsinn",
            "astrologie kritik wissenschaft",
        ],
        "hashtags": ["astrologie"],
    },
    "apps": {
        "titel": "Astrologie-Apps (Wettbewerb)",
        "begriffe": [
            "beste astrologie app deutsch",
            "horoskop app erfahrungen bewertung",
        ],
        "hashtags": ["astrologyapp"],
        "playstore": "astrologie horoskop app",
    },
}


def _eintrag(bereich: str) -> dict:
    return BEREICHE.get((bereich or "").strip().lower(), {})


def begriffe_fuer(bereich: str) -> list[str]:
    e = _eintrag(bereich)
    if e:
        return e["begriffe"]
    return [f"{bereich} astrologie", f"{bereich} horoskop erfahrungen"]


def hashtags_fuer(bereich: str) -> list[str]:
    e = _eintrag(bereich)
    if e:
        return e.get("hashtags", ["astrologie"])
    wort = (bereich or "astrologie").split()[0].lower()
    return [wort, "astrologie"]


def playstore_suche_fuer(bereich: str) -> str:
    e = _eintrag(bereich)
    return e.get("playstore", "astrologie horoskop app")


def titel_fuer(bereich: str) -> str:
    e = _eintrag(bereich)
    return e.get("titel", bereich)
