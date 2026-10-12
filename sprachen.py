"""
Sprachen des Agents: de, en, hu, it (wie die App).
Astro-Begriffe stimmen mit der App ueberein (i18n.js in soraya-web).
"""

from datetime import date

SPRACHEN = ["de", "en", "hu", "it"]
NAMEN = {"de": "Deutsch", "en": "English", "hu": "Magyar", "it": "Italiano"}

_ANWEISUNG = {
    "de": "Schreibe alle Texte auf Deutsch (du-Form, österreichischer und deutscher Markt).",
    "en": "Write all texts in natural, idiomatic English (informal 'you'; UK and international market).",
    "hu": "Minden szöveget természetes, gördülékeny magyar nyelven írj, tegező formában (magyar piac).",
    "it": "Scrivi tutti i testi in italiano naturale e scorrevole, dando del tu (mercato italiano).",
}

LINK_IN_BIO = {"de": "Link in Bio", "en": "Link in bio", "hu": "Link a bióban", "it": "Link in bio"}

_SIGN_KEYS = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
_SIGNS = {
    "de": ["Widder", "Stier", "Zwillinge", "Krebs", "Löwe", "Jungfrau", "Waage", "Skorpion", "Schütze", "Steinbock", "Wassermann", "Fische"],
    "en": ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"],
    "hu": ["Kos", "Bika", "Ikrek", "Rák", "Oroszlán", "Szűz", "Mérleg", "Skorpió", "Nyilas", "Bak", "Vízöntő", "Halak"],
    "it": ["Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine", "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci"],
}
_PLANETS = {
    "Mercury": {"de": "Merkur", "en": "Mercury", "hu": "Merkúr", "it": "Mercurio"},
    "Venus": {"de": "Venus", "en": "Venus", "hu": "Vénusz", "it": "Venere"},
    "Mars": {"de": "Mars", "en": "Mars", "hu": "Mars", "it": "Marte"},
    "Jupiter": {"de": "Jupiter", "en": "Jupiter", "hu": "Jupiter", "it": "Giove"},
    "Saturn": {"de": "Saturn", "en": "Saturn", "hu": "Szaturnusz", "it": "Saturno"},
    "Uranus": {"de": "Uranus", "en": "Uranus", "hu": "Uránusz", "it": "Urano"},
    "Neptune": {"de": "Neptun", "en": "Neptune", "hu": "Neptunusz", "it": "Nettuno"},
    "Pluto": {"de": "Pluto", "en": "Pluto", "hu": "Plútó", "it": "Plutone"},
}
_PHASES = {
    "de": ["Neumond", "Zunehmende Sichel", "Erstes Viertel", "Zunehmender Mond", "Vollmond", "Abnehmender Mond", "Letztes Viertel", "Abnehmende Sichel"],
    "en": ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"],
    "hu": ["Újhold", "Növő holdsarló", "Első negyed", "Növő Hold", "Telihold", "Fogyó Hold", "Utolsó negyed", "Fogyó holdsarló"],
    "it": ["Luna nuova", "Luna crescente", "Primo quarto", "Gibbosa crescente", "Luna piena", "Gibbosa calante", "Ultimo quarto", "Luna calante"],
}
_MONATE = {
    "de": ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "hu": ["január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október", "november", "december"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
}


def norm(sprache: str | None) -> str:
    s = (sprache or "de").strip().lower()[:2]
    return s if s in SPRACHEN else "de"


def sprach_anweisung(sprache: str) -> str:
    return _ANWEISUNG[norm(sprache)]


def zeichen(key: str, sprache: str) -> str:
    if key in _SIGN_KEYS:
        return _SIGNS[norm(sprache)][_SIGN_KEYS.index(key)]
    return key or ""


def planet(key: str, sprache: str) -> str:
    return _PLANETS.get(key, {}).get(norm(sprache), key or "")


def mondphase(index: int, sprache: str) -> str:
    namen = _PHASES[norm(sprache)]
    return namen[index] if isinstance(index, int) and 0 <= index < len(namen) else ""


def datum_lang(d: date, sprache: str) -> str:
    s = norm(sprache)
    monat = _MONATE[s][d.month - 1]
    if s == "de":
        return f"{d.day}. {monat} {d.year}"
    if s == "en":
        return f"{d.day} {monat} {d.year}"
    if s == "hu":
        return f"{d.year}. {monat} {d.day}."
    return f"{d.day} {monat} {d.year}"


def datum_kurz(d: date, sprache: str) -> str:
    s = norm(sprache)
    monat = _MONATE[s][d.month - 1]
    if s == "de":
        return f"{d.day}. {monat}"
    if s == "hu":
        return f"{monat} {d.day}."
    return f"{d.day} {monat}"
