"""
Soraya-Agent — Stufe 1
- Content-Agent: schreibt Social-Media-Posts.
- Recherche (Apify): liest Webseiten aus / durchsucht das Netz.
- Zielgruppen-Agent: erstellt Kundenprofile je Bereich.
- Web-Oberflaeche ("Content Studio") unter "/".
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from content_agent import erstelle_posts
from research_agent import analysiere_zielgruppe
from webseite import hole_webseiten_text
from websuche import quelle_websuche
from reddit import quelle_reddit
from playstore import quelle_playstore, quelle_playstore_ids
from bereiche import (
    BEREICHE, begriffe_fuer, playstore_suche_fuer, titel_fuer,
)
from db import (
    init_db, speichere_posts, lade_posts,
    speichere_zielgruppe, lade_zielgruppen,
)

app = FastAPI(title="Soraya-Agent", version="0.4")


class ContentAnfrage(BaseModel):
    thema: Optional[str] = None
    anzahl: int = 3


class UrlAnfrage(BaseModel):
    url: str
    anzahl: int = 3


class ZielgruppeAnfrage(BaseModel):
    bereich: str
    land: str = "at"
    # Welche Quellen sollen laufen?
    quellen: list[str] = ["google"]
    # Eigene Vorgaben — wenn gesetzt, ersetzen sie die vordefinierten
    eigene_begriffe: list[str] = []
    eigene_playstore: str = ""
    eigene_app_ids: list[str] = []
    eigene_frage: str = ""


@app.on_event("startup")
def beim_start():
    try:
        init_db()
    except Exception as e:
        print(f"[Start] Datenbank noch nicht bereit: {e}")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/bereiche")
def bereiche():
    return {"bereiche": [{"schluessel": k, "titel": v["titel"]} for k, v in BEREICHE.items()]}


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    try:
        posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl)
        return {"erstellt": len(posts), "posts": speichere_posts(posts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/content-von-url")
def content_von_url(anfrage: UrlAnfrage):
    try:
        text = hole_webseiten_text(anfrage.url)
        posts = erstelle_posts(anzahl=anfrage.anzahl, kontext=text)
        gespeichert = speichere_posts(posts)
        return {
            "quelle": anfrage.url,
            "gelesen_zeichen": len(text),
            "erstellt": len(gespeichert),
            "posts": gespeichert,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/content")
def content_ansehen(limit: int = 50):
    try:
        return {"posts": lade_posts(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/zielgruppe")
def zielgruppe_erforschen(anfrage: ZielgruppeAnfrage):
    """Recherchiert einen Bereich in mehreren Quellen und erstellt ein Kundenprofil."""
    try:
        titel = titel_fuer(anfrage.bereich)

        # Eigene Eingaben haben Vorrang vor den vordefinierten Mustern
        begriffe = [b.strip() for b in anfrage.eigene_begriffe if b.strip()] \
            or begriffe_fuer(anfrage.bereich)
        playstore_suche = anfrage.eigene_playstore.strip() \
            or playstore_suche_fuer(anfrage.bereich)
        app_ids = [a.strip() for a in anfrage.eigene_app_ids if a.strip()]

        gewaehlt = anfrage.quellen or ["google"]
        teile, geklappt, fehlgeschlagen = [], [], {}

        def hole(name, fn):
            if name not in gewaehlt:
                return
            print(f"[Recherche] Starte Quelle: {name}", flush=True)
            try:
                text = fn()
                if text and text.strip():
                    teile.append(f"\n\n===== QUELLE: {name.upper()} =====\n{text}")
                    geklappt.append(name)
                    print(f"[Recherche] {name}: {len(text)} Zeichen erhalten", flush=True)
                else:
                    fehlgeschlagen[name] = "keine Ergebnisse"
                    print(f"[Recherche] {name}: KEINE ERGEBNISSE", flush=True)
            except Exception as e:
                fehlgeschlagen[name] = str(e)[:300]
                print(f"[Recherche] {name}: FEHLER -> {e}", flush=True)

        hole("websuche", lambda: quelle_websuche(begriffe, land=anfrage.land))
        hole("reddit", lambda: quelle_reddit(begriffe))
        hole("playstore", lambda: (
            quelle_playstore_ids(app_ids) if app_ids
            else quelle_playstore(playstore_suche)
        ))

        recherche = "".join(teile)
        if not recherche.strip():
            raise RuntimeError(
                "Keine Quelle hat Daten geliefert. Details: " + str(fehlgeschlagen)
            )

        profil = analysiere_zielgruppe(
            titel, recherche, eigene_frage=anfrage.eigene_frage.strip()
        )
        profil["_quellen"] = geklappt
        profil["_gesucht"] = begriffe
        zeile = speichere_zielgruppe(titel, profil)

        return {
            "bereich": titel,
            "gesucht": begriffe,
            "quellen_ok": geklappt,
            "quellen_fehler": fehlgeschlagen,
            "gefunden_zeichen": len(recherche),
            "profil": profil,
            "id": zeile.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/zielgruppen")
def zielgruppen_ansehen(limit: int = 20):
    try:
        return {"zielgruppen": lade_zielgruppen(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soraya · Content Studio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{--ink:#0B0E1A;--panel:#12162A;--panel-2:#161B34;--gold:#C9A24B;
        --champagne:#E7D3A1;--mist:#C3C7D6;--mist-dim:#8A8FA6;--line:rgba(201,162,75,.22)}
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:radial-gradient(1100px 600px at 80% -10%,rgba(201,162,75,.10),transparent 60%),
       radial-gradient(900px 500px at -10% 10%,rgba(90,110,200,.12),transparent 55%),var(--ink);
       color:var(--mist);font-family:'Inter',system-ui,sans-serif;min-height:100vh;line-height:1.6;
       -webkit-font-smoothing:antialiased}
  .wrap{max-width:820px;margin:0 auto;padding:52px 22px 80px}
  header{text-align:center;margin-bottom:34px}
  .eyebrow{font-size:11px;letter-spacing:.34em;text-transform:uppercase;color:var(--gold);margin:0 0 14px}
  h1{font-family:'Cormorant Garamond',serif;font-weight:500;font-size:clamp(36px,7vw,56px);
     line-height:1;color:#F4EEDD;margin:0}
  h1 .star{color:var(--gold);font-size:.6em;vertical-align:middle;margin:0 .28em}
  .sub{color:var(--mist-dim);margin-top:12px;font-size:15px}
  .tabs{display:flex;gap:8px;justify-content:center;margin:26px 0 24px;flex-wrap:wrap}
  .tab{font-family:inherit;font-size:13px;letter-spacing:.14em;text-transform:uppercase;
       background:transparent;border:1px solid var(--line);color:var(--mist-dim);
       padding:10px 18px;border-radius:999px;cursor:pointer;transition:.2s}
  .tab:hover{border-color:var(--gold);color:var(--champagne)}
  .tab.on{background:rgba(201,162,75,.12);border-color:var(--gold);color:var(--champagne)}
  .panel{background:linear-gradient(180deg,var(--panel-2),var(--panel));border:1px solid var(--line);
         border-radius:16px;padding:22px;margin-bottom:18px}
  .panel h2{font-family:'Cormorant Garamond',serif;font-weight:600;font-size:23px;
            color:var(--champagne);margin:0 0 4px}
  .panel p.hint{margin:0 0 16px;font-size:13px;color:var(--mist-dim)}
  label{display:block;font-size:11px;letter-spacing:.16em;text-transform:uppercase;
        color:var(--mist-dim);margin:0 0 7px}
  .row{display:flex;gap:12px;flex-wrap:wrap}
  .row>.grow{flex:1;min-width:180px}
  input,select{width:100%;background:#0C1022;border:1px solid var(--line);color:#EFE7D2;
               border-radius:10px;padding:12px 14px;font-size:15px;font-family:inherit;outline:none}
  input::placeholder{color:#5f647c}
  input:focus,select:focus{border-color:var(--gold)}
  button{font-family:inherit;cursor:pointer;border-radius:10px;font-size:14px;border:1px solid var(--gold);
         background:linear-gradient(180deg,#D8B65E,#C9A24B);color:#1A140A;font-weight:600;
         padding:12px 20px;transition:filter .2s}
  button:hover{filter:brightness(1.07)}
  button:disabled{opacity:.55;cursor:default;filter:none}
  button.ghost{background:transparent;color:var(--gold);border-color:var(--line);font-weight:500}
  button.ghost:hover{border-color:var(--gold)}
  .bar{display:flex;align-items:center;justify-content:space-between;margin:22px 2px 14px}
  .bar h3{font-family:'Cormorant Garamond',serif;font-weight:600;font-size:26px;color:var(--champagne);margin:0}
  #status{min-height:20px;text-align:center;font-size:14px;color:var(--gold);margin:8px 0 4px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;
        margin-bottom:14px;position:relative;overflow:hidden}
  .card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;
                background:linear-gradient(var(--gold),transparent)}
  .plat{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--gold);margin:0 0 10px}
  .txt{color:#E4E6EF;white-space:pre-wrap;margin:0 0 12px}
  .tags{color:var(--champagne);font-size:14px;margin:0 0 14px}
  .foot{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .stamp{font-size:12px;color:var(--mist-dim)}
  .empty{text-align:center;color:var(--mist-dim);padding:38px 10px;
         font-family:'Cormorant Garamond',serif;font-size:22px}
  .empty span{display:block;font-family:'Inter';font-size:13px;margin-top:8px}
  .spin{display:inline-block;width:15px;height:15px;border:2px solid var(--line);
        border-top-color:var(--gold);border-radius:50%;vertical-align:-2px;margin-right:8px}
  @media (prefers-reduced-motion:no-preference){.spin{animation:s .8s linear infinite}}
  @keyframes s{to{transform:rotate(360deg)}}
  .who h4{font-family:'Cormorant Garamond',serif;font-size:20px;color:var(--champagne);
          margin:18px 0 6px;font-weight:600}
  .who h4:first-child{margin-top:0}
  .who ul{margin:0;padding-left:18px}
  .who li{margin:4px 0;color:#DDE0EC}
  .lede{color:#E4E6EF;font-size:16px;margin:0 0 4px}
  .warn{border-left:2px solid #7a6a3a;padding-left:12px;color:var(--mist-dim);font-size:14px}
  footer{text-align:center;color:var(--mist-dim);font-size:12px;margin-top:40px}
  .hide{display:none}
  .quellen{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
  .q{display:flex;align-items:center;gap:7px;border:1px solid var(--line);border-radius:999px;
     padding:8px 14px;cursor:pointer;font-size:13px;color:var(--mist-dim);transition:.2s;user-select:none}
  .q:hover{border-color:var(--gold)}
  .q input{width:auto;margin:0;accent-color:var(--gold)}
  .q.on{background:rgba(201,162,75,.12);border-color:var(--gold);color:var(--champagne)}
  .q small{color:var(--mist-dim);font-size:11px}
  .note{font-size:12px;color:var(--mist-dim);margin:10px 0 0;line-height:1.5}
  .src{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mist-dim);margin:0 0 12px}
  textarea{width:100%;background:#0C1022;border:1px solid var(--line);color:#EFE7D2;border-radius:10px;
           padding:12px 14px;font-size:14px;font-family:inherit;outline:none;resize:vertical;min-height:78px;
           line-height:1.5}
  textarea:focus{border-color:var(--gold)}
  textarea::placeholder{color:#5f647c}
  details{margin-top:18px;border-top:1px solid var(--line);padding-top:16px}
  summary{cursor:pointer;color:var(--gold);font-size:13px;letter-spacing:.14em;text-transform:uppercase;
          list-style:none;outline:none}
  summary::-webkit-details-marker{display:none}
  summary::before{content:"+ ";font-weight:600}
  details[open] summary::before{content:"\2212 "}
  .feld{margin-top:16px}
  .feld .why{font-size:12px;color:var(--mist-dim);margin:4px 0 8px}
  .answer{background:rgba(201,162,75,.07);border:1px solid var(--line);border-radius:10px;
          padding:14px 16px;margin:14px 0 4px;color:#E4E6EF}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="eyebrow">Soraya Luxury Astrology</p>
    <h1>Content<span class="star">&#10022;</span>Studio</h1>
    <p class="sub">Posts schreiben &mdash; und verstehen, fuer wen.</p>
  </header>

  <div class="tabs">
    <button type="button" class="tab on" id="tabPosts">Posts</button>
    <button type="button" class="tab" id="tabWho">Zielgruppen</button>
  </div>

  <!-- ============ POSTS ============ -->
  <div id="viewPosts">
    <div class="panel">
      <h2>Aus einem Thema</h2>
      <p class="hint">Gib ein Stichwort ein, der Rest passiert von selbst.</p>
      <div class="row">
        <div class="grow"><label>Thema</label>
          <input id="thema" placeholder="z. B. Vollmond in der Waage"></div>
        <div><label>Anzahl</label>
          <select id="anzahl1"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div>
      </div>
      <div style="margin-top:16px"><button id="btnThema" onclick="ausThema()">Posts erzeugen</button></div>
    </div>

    <div class="panel">
      <h2>Aus einer Webseite</h2>
      <p class="hint">Eine Quelle einlesen &mdash; Soraya macht daraus eigene Posts.</p>
      <div class="row">
        <div class="grow"><label>Webseite (URL)</label>
          <input id="url" placeholder="https://..."></div>
        <div><label>Anzahl</label>
          <select id="anzahl2"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div>
      </div>
      <div style="margin-top:16px"><button id="btnUrl" onclick="ausUrl()">Aus Webseite erzeugen</button></div>
    </div>

    <div class="bar">
      <h3>Deine Posts</h3>
      <button class="ghost" onclick="ladePosts()">Aktualisieren</button>
    </div>
    <div id="liste"></div>
  </div>

  <!-- ============ ZIELGRUPPEN ============ -->
  <div id="viewWho" class="hide">
    <div class="panel">
      <h2>Kunden verstehen</h2>
      <p class="hint">Waehle einen Bereich. Der Agent durchsucht das Netz und erstellt ein Profil:
         wer diese Menschen sind, was sie beschaeftigt, welche Worte sie benutzen.</p>
      <div class="row">
        <div class="grow"><label>Bereich</label>
          <select id="bereich"></select></div>
        <div><label>Land</label>
          <select id="land">
            <option value="at" selected>&Ouml;sterreich</option>
            <option value="de">Deutschland</option>
            <option value="ch">Schweiz</option>
          </select></div>
      </div>
      <div class="row" style="margin-top:12px">
        <div class="grow"><label>Oder eigener Bereich</label>
          <input id="eigen" placeholder="z. B. Astrologie und Schwangerschaft"></div>
      </div>

      <div style="margin-top:18px">
        <label>Quellen</label>
        <div class="quellen" id="quellen">
          <label class="q on"><input type="checkbox" value="websuche" checked> Websuche</label>
          <label class="q on"><input type="checkbox" value="reddit" checked> Reddit <small>gratis</small></label>
          <label class="q on"><input type="checkbox" value="playstore" checked> Play Store <small>gratis</small></label>
        </div>
        <p class="note">Reddit und Play Store sind komplett kostenlos. Die Websuche laeuft
           ueber deinen Anthropic-Zugang und kostet ein paar Cent pro Recherche.
           Mehr Quellen bedeuten mehr Wartezeit &mdash; rechne mit ein bis zwei Minuten.</p>
      </div>

      <details>
        <summary>Selbst bestimmen, wonach gesucht wird</summary>

        <div class="feld">
          <label>Eigene Suchbegriffe</label>
          <p class="why">Fuer Google und Reddit. Eine Suche pro Zeile. Schreib so, wie
             deine Kunden wirklich suchen wuerden &mdash; also ganze Fragen, keine Schlagworte.</p>
          <textarea id="eBegriffe" placeholder="warum zieht er sich zurueck sternzeichen&#10;horoskop stimmt nicht enttaeuscht&#10;astrologie trennung verarbeiten"></textarea>
        </div>

        <div class="feld">
          <label>Eigene Play-Store-Suche</label>
          <p class="why">Nach welchen Apps soll gesucht werden? Ihre Bewertungen werden ausgewertet.</p>
          <input id="ePlaystore" placeholder="z. B. partnerhoroskop app">
        </div>

        <div class="feld">
          <label>Oder bestimmte Apps direkt</label>
          <p class="why">App-IDs deiner Konkurrenten, eine pro Zeile. Die ID steht in der
             Play-Store-Adresse hinter <em>?id=</em> &mdash; damit triffst du genau die Apps,
             die dich interessieren.</p>
          <textarea id="eAppIds" placeholder="com.chaninicholas.chaniapp&#10;me.sanctuary.app"></textarea>
        </div>

        <div class="feld">
          <label>Deine Frage an die Analyse</label>
          <p class="why">Was willst du aus den Daten konkret herausfinden?</p>
          <textarea id="eFrage" placeholder="z. B. Wuerden diese Menschen fuer eine Astrologie-App Geld ausgeben und wofuer genau?"></textarea>
        </div>
      </details>

      <div style="margin-top:18px"><button id="btnWho" onclick="erforsche()">Bereich erforschen</button></div>
    </div>

    <div class="bar">
      <h3>Deine Profile</h3>
      <button class="ghost" onclick="ladeProfile()">Aktualisieren</button>
    </div>
    <div id="profile"></div>
  </div>

  <div id="status"></div>
  <footer>Soraya &#10022; Content Studio</footer>
</div>

<script>
const $ = (id) => document.getElementById(id);

/* Umschaltung zuerst und unabhaengig vom Rest verdrahten,
   damit sie auch dann geht, wenn weiter unten etwas schiefgeht. */
function zeige(was){
  const p = was === 'posts';
  $('viewPosts').classList.toggle('hide', !p);
  $('viewWho').classList.toggle('hide', p);
  $('tabPosts').classList.toggle('on', p);
  $('tabWho').classList.toggle('on', !p);
  const st = $('status'); if(st) st.textContent = '';
  if(!p && typeof ladeProfile === 'function'){ try{ ladeProfile(); }catch(e){} }
}
$('tabPosts').addEventListener('click', () => zeige('posts'));
$('tabWho').addEventListener('click', () => zeige('who'));
const esc = (s) => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function melde(m){ $('status').textContent = m || ''; }
function busy(btn, on, text){
  btn.disabled = on;
  if(on){ btn.dataset.label = btn.textContent; btn.innerHTML = '<span class="spin"></span>' + text; }
  else if(btn.dataset.label){ btn.textContent = btn.dataset.label; }
}

/* ---------- Posts ---------- */
function renderPosts(posts){
  const box = $('liste');
  if(!posts || !posts.length){
    box.innerHTML = '<div class="empty">Noch keine Posts.<span>Gib oben ein Thema ein und leg los.</span></div>';
    return;
  }
  box.innerHTML = posts.map(p => `<div class="card">
      <p class="plat">${esc(p.platform)}</p>
      <p class="txt">${esc(p.text)}</p>
      <p class="tags">${esc(p.hashtags||'')}</p>
      <div class="foot"><span class="stamp">${(p.created_at||'').slice(0,10)}</span>
      <button class="ghost" onclick="kopiere(this)" data-t="${encodeURIComponent((p.text||'')+'\\n\\n'+(p.hashtags||''))}">Kopieren</button></div>
    </div>`).join('');
}
function kopiere(btn){
  navigator.clipboard.writeText(decodeURIComponent(btn.dataset.t)).then(()=>{
    const a = btn.textContent; btn.textContent = 'Kopiert \\u2713';
    setTimeout(()=>btn.textContent = a, 1400);
  });
}
async function ladePosts(){
  try{ const r = await fetch('/content'); renderPosts((await r.json()).posts); }
  catch(e){ melde('Konnte Posts nicht laden.'); }
}
async function ausThema(){
  const b = $('btnThema'); busy(b, true, 'Die Sterne schreiben \\u2026'); melde('');
  try{
    const r = await fetch('/content', {method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({thema: $('thema').value.trim() || null, anzahl: +$('anzahl1').value})});
    if(!r.ok) throw new Error((await r.json()).detail || 'Fehler');
    await ladePosts(); melde('Fertig \\u2713');
  }catch(e){ melde('Fehler: ' + e.message); } finally{ busy(b, false); }
}
async function ausUrl(){
  const b = $('btnUrl'), url = $('url').value.trim();
  if(!url){ melde('Bitte eine Webseite eingeben.'); return; }
  busy(b, true, 'Lese Seite \\u2026'); melde('');
  try{
    const r = await fetch('/content-von-url', {method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({url, anzahl: +$('anzahl2').value})});
    if(!r.ok) throw new Error((await r.json()).detail || 'Fehler');
    await ladePosts(); melde('Fertig \\u2713');
  }catch(e){ melde('Fehler: ' + e.message); } finally{ busy(b, false); }
}

/* ---------- Zielgruppen ---------- */
function liste(titel, arr){
  if(!arr || !arr.length) return '';
  return `<h4>${titel}</h4><ul>${arr.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
}
function renderProfile(zeilen){
  const box = $('profile');
  if(!zeilen || !zeilen.length){
    box.innerHTML = '<div class="empty">Noch keine Profile.<span>Waehle oben einen Bereich und erforsche ihn.</span></div>';
    return;
  }
  box.innerHTML = zeilen.map(z => {
    const p = z.profil || {};
    return `<div class="card who">
      <p class="plat">${esc(z.bereich)}</p>
      ${p._quellen&&p._quellen.length?`<p class="src">Quellen: ${p._quellen.map(esc).join(' &middot; ')}</p>`:''}
      <p class="lede">${esc(p.wer_sind_sie||'')}</p>
      ${p.antwort_auf_frage?`<div class="answer">${esc(p.antwort_auf_frage)}</div>`:''}
      ${liste('Was sie beschaeftigt', p.beschaeftigt_sie)}
      ${liste('Was sie sich wuenschen', p.wuensche)}
      ${liste('Ihre Sprache', p.sprache)}
      ${liste('Content-Ideen', p.content_ideen)}
      ${liste('Worauf achten', p.worauf_achten)}
      ${liste('Luecke am Markt', p.luecke_am_markt)}
      ${(p.unsicher&&p.unsicher.length)?`<h4>Unsicher</h4><p class="warn">${p.unsicher.map(esc).join(' &middot; ')}</p>`:''}
      ${(p._gesucht&&p._gesucht.length)?`<h4>Gesucht wurde nach</h4><p class="warn">${p._gesucht.map(esc).join(' &middot; ')}</p>`:''}
      <div class="foot" style="margin-top:14px"><span class="stamp">${(z.created_at||'').slice(0,10)}</span></div>
    </div>`;
  }).join('');
}
async function ladeBereiche(){
  try{
    const r = await fetch('/bereiche');
    const d = await r.json();
    $('bereich').innerHTML = d.bereiche.map(b=>`<option value="${b.schluessel}">${esc(b.titel)}</option>`).join('');
  }catch(e){}
}
async function ladeProfile(){
  try{ const r = await fetch('/zielgruppen'); renderProfile((await r.json()).zielgruppen); }
  catch(e){ melde('Konnte Profile nicht laden.'); }
}
try{
  document.querySelectorAll('#quellen input').forEach(cb => {
    cb.addEventListener('change', () => cb.closest('.q').classList.toggle('on', cb.checked));
  });
}catch(e){ console.error('Quellen-Chips', e); }

async function erforsche(){
  const b = $('btnWho');
  const eigen = $('eigen').value.trim();
  const bereich = eigen || $('bereich').value;
  const quellen = [...document.querySelectorAll('#quellen input:checked')].map(c => c.value);
  if(!quellen.length){ melde('Bitte mindestens eine Quelle waehlen.'); return; }
  const zeilen = (id) => $(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
  busy(b, true, 'Recherchiere \\u2026 (kann einige Minuten dauern)'); melde('');
  try{
    const r = await fetch('/zielgruppe', {method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        bereich, land: $('land').value, quellen,
        eigene_begriffe: zeilen('eBegriffe'),
        eigene_playstore: $('ePlaystore').value.trim(),
        eigene_app_ids: zeilen('eAppIds'),
        eigene_frage: $('eFrage').value.trim(),
      })});
    if(!r.ok) throw new Error((await r.json()).detail || 'Fehler');
    const d = await r.json();
    await ladeProfile();
    let m = 'Fertig \\u2713  Quellen: ' + (d.quellen_ok||[]).join(', ');
    const fehler = Object.keys(d.quellen_fehler||{});
    if(fehler.length) m += '  \\u00b7  ohne Ergebnis: ' + fehler.join(', ');
    melde(m);
  }catch(e){ melde('Fehler: ' + e.message); } finally{ busy(b, false); }
}

try{ ladePosts(); }catch(e){ console.error('ladePosts', e); }
try{ ladeBereiche(); }catch(e){ console.error('ladeBereiche', e); }
</script>
</body>
</html>"""
