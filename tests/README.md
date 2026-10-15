# Tests für den Soraya-Agent

Alle Tests laufen lokal mit Attrappen (kein Claude, kein Meta, keine Engine) gegen eine eigene Postgres.

```bash
# Postgres (z. B. lokal auf Port 55432, Datenbank "agenttest", Benutzer "agent")
export TEST_DATABASE_URL=postgresql://agent@127.0.0.1:55432/agenttest

pip install -r requirements.txt pytest httpx
python -m pytest -q tests/test_agent.py          # ~50 Tests, ca. 1 Minute (rendert ein echtes Reel)

# UI-Test (Playwright, Chromium unter /opt/pw-browsers/chromium oder CHROMIUM=...)
python tests/dev_server.py &                      # Dashboard mit Attrappen auf Port 8790
npm i playwright && node tests/ui_test.mjs http://127.0.0.1:8790 /tmp/shots
```

Achtung: `test_agent.py` und `dev_server.py` löschen beim Start die Agent-Tabellen in der
Test-Datenbank – nie mit der echten `DATABASE_URL` starten.
