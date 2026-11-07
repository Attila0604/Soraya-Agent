"""Baut inhalte/zeichen_pins.json aus den Sternzeichen-Seiten der Landingpage (Repo soraya-landing).

Aufruf:  python3 tools/zeichen_pins_bauen.py ../soraya-landing
Daraus entstehen die zeitlosen Sternzeichen-Pins auf Pinterest (pin_extras.py) -- dieselben Texte wie auf den
Zeichen-Seiten, auf die die Pins verlinken.
"""
import json
import pathlib
import sys

REIHE = ["Ari", "Tau", "Gem", "Can", "Leo", "Vir", "Lib", "Sco", "Sag", "Cap", "Aqu", "Pis"]
FELDER = ("key", "slug", "name", "intro", "meta_description", "staerken", "schwaechen", "passt_gut", "faq")


def main(landing: str) -> None:
    basis = pathlib.Path(landing) / "inhalte" / "zeichen"
    aus = {}
    for ordner in sorted(p for p in basis.iterdir() if p.is_dir()):
        zeichen = {}
        for datei in ordner.glob("*.json"):
            d = json.loads(datei.read_text(encoding="utf-8"))
            zeichen[d["key"]] = {k: d.get(k) for k in FELDER}
        aus[ordner.name] = [zeichen[k] for k in REIHE]
    ziel = pathlib.Path(__file__).resolve().parent.parent / "inhalte" / "zeichen_pins.json"
    ziel.write_text(json.dumps(aus, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{ziel}: {', '.join(f'{s} {len(v)}' for s, v in aus.items())}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../soraya-landing")
