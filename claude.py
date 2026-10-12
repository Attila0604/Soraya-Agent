"""
Gemeinsame Claude-Anbindung fuer alle Agent-Teile (offizielles Anthropic-SDK).

- frage_json(): Antwort als JSON nach festem Schema (strukturierte Ausgabe),
  dadurch kein kaputtes JSON mehr.
- suche_text(): Claude recherchiert selbst im Netz (Web-Search-Werkzeug).
- Ablehnungen (stop_reason "refusal") werden sauber gemeldet; bei Modellen,
  die es unterstuetzen, uebernimmt automatisch ein Ersatzmodell
  (server-seitige Fallbacks).

Modell per Railway-Variable ANTHROPIC_MODEL, sonst claude-opus-5-5.
"""

from __future__ import annotations

import json
import os
import re

import anthropic

STANDARD_MODELL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Modelle mit server-seitigem Ersatzmodell bei Ablehnung
_MIT_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
# Modelle mit dem neuen Websuche-Werkzeug (dynamische Filterung)
_NEUE_WEBSUCHE = re.compile(r"^claude-(opus-(5-5|5|4-8|4-7|4-6)|sonnet-(5-5|5|4-6))$")

_client: anthropic.Anthropic | None = None


def modell() -> str:
    return (os.environ.get("ANTHROPIC_MODEL") or "").strip() or STANDARD_MODELL


def _modern(name: str) -> bool:
    """Aktuelle Modelle: kennen effort und strukturierte Ausgabe."""
    return bool(re.match(r"^claude-(opus|sonnet|haiku|fable|mythos)-(5|4-[6-9])", name))


def _client_holen() -> anthropic.Anthropic:
    global _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY fehlt. Bitte in Railway unter Variables setzen.")
    if _client is None:
        _client = anthropic.Anthropic(timeout=240.0, max_retries=2)
    return _client


def _senden(**kw):
    """Schickt die Anfrage; uebersetzt API-Fehler in verstaendliche Meldungen."""
    client = _client_holen()
    name = kw["model"]
    try:
        if name in _MIT_FALLBACK:
            return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kw)
        return client.messages.create(**kw)
    except anthropic.AuthenticationError:
        raise RuntimeError("Der Anthropic-Schlüssel (ANTHROPIC_API_KEY) ist ungültig.")
    except anthropic.NotFoundError:
        raise RuntimeError(f"Modell '{name}' nicht gefunden. Bitte ANTHROPIC_MODEL in Railway prüfen.")
    except anthropic.RateLimitError:
        raise RuntimeError("Claude ist gerade ausgelastet (Rate-Limit). Bitte in ein paar Minuten erneut.")
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"Claude hat die Anfrage zurückgewiesen: {e.message}")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude-Fehler {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Keine Verbindung zu Claude. Bitte später erneut versuchen.")


def _pruefe_stopp(antwort) -> None:
    if antwort.stop_reason == "refusal":
        details = getattr(antwort, "stop_details", None)
        kategorie = getattr(details, "category", None) if details else None
        raise RuntimeError("Claude hat diese Anfrage abgelehnt"
                           + (f" (Kategorie: {kategorie})." if kategorie else "."))
    if antwort.stop_reason == "max_tokens":
        raise RuntimeError("Die Antwort war zu lang und wurde abgeschnitten. Bitte weniger auf einmal anfordern.")


def _text(antwort) -> str:
    return "".join(b.text for b in antwort.content if getattr(b, "type", "") == "text").strip()


def _json_lesen(inhalt: str) -> dict:
    if inhalt.startswith("```"):
        inhalt = inhalt.strip("`")
        if inhalt.lstrip().lower().startswith("json"):
            inhalt = inhalt.lstrip()[4:]
        inhalt = inhalt.strip()
    try:
        return json.loads(inhalt)
    except json.JSONDecodeError:
        raise RuntimeError("Claude hat kein sauberes JSON geliefert: " + inhalt[:300])


def frage_json(system: str, frage: str, schema: dict, *, effort: str = "medium",
               max_tokens: int = 16000) -> dict:
    """Eine Anfrage, Antwort garantiert als JSON nach `schema`."""
    name = modell()
    kw = dict(model=name, max_tokens=max_tokens, system=system,
              messages=[{"role": "user", "content": frage}])
    if _modern(name):
        kw["output_config"] = {"effort": effort, "format": {"type": "json_schema", "schema": schema}}
    else:
        kw["system"] = (system + "\n\nAntworte AUSSCHLIESSLICH mit gültigem JSON nach diesem Schema, "
                        "ohne Markdown:\n" + json.dumps(schema, ensure_ascii=False))
    antwort = _senden(**kw)
    _pruefe_stopp(antwort)
    inhalt = _text(antwort)
    if not inhalt:
        raise RuntimeError("Claude hat keinen Text geliefert.")
    return _json_lesen(inhalt)


def suche_text(system: str, frage: str, *, max_suchen: int = 6, effort: str = "medium") -> str:
    """Claude sucht selbst im Netz und liefert die Fundstuecke als Text."""
    name = modell()
    werkzeug = "web_search_20260209" if _NEUE_WEBSUCHE.match(name) else "web_search_20250305"
    nachrichten = [{"role": "user", "content": frage}]
    kw = dict(model=name, max_tokens=16000, system=system,
              tools=[{"type": werkzeug, "name": "web_search", "max_uses": max_suchen}])
    if _modern(name):
        kw["output_config"] = {"effort": effort}
    teile = []
    for _ in range(4):  # lange Recherchen pausiert die API zwischendurch (pause_turn)
        antwort = _senden(messages=nachrichten, **kw)
        _pruefe_stopp(antwort)
        teile.append(_text(antwort))
        if antwort.stop_reason != "pause_turn":
            break
        nachrichten = nachrichten + [{"role": "assistant", "content": antwort.content}]
    inhalt = "\n".join(t for t in teile if t).strip()
    if not inhalt:
        raise RuntimeError("Die Websuche hat nichts geliefert.")
    return inhalt
