"""
Soraya-Agent — Stufe 0/1
- Content-Agent: schreibt Social-Media-Posts fuer die Soraya-App.
- Recherche (Apify): liest eine Webseite aus und schreibt Posts daraus.
- Web-Oberflaeche ("Content Studio") direkt unter "/".
Speicherung in der Railway-eigenen PostgreSQL-Datenbank.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from content_agent import erstelle_posts
from apify import hole_webseiten_text
from db import init_db, speichere_posts, lade_posts

app = FastAPI(title="Soraya-Agent", version="0.3")


class ContentAnfrage(BaseModel):
    thema: Optional[str] = None
    anzahl: int = 3


class UrlAnfrage(BaseModel):
    url: str
    anzahl: int = 3


@app.on_event("startup")
def beim_start():
    try:
        init_db()
    except Exception as e:
        print(f"[Start] Datenbank noch nicht bereit: {e}")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.get("/status")
def status():
    return {
        "app": "Soraya-Agent",
        "stufe": "0/1",
        "agenten": ["Content-Agent", "Recherche (Apify)"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/content")
def content_erstellen(anfrage: ContentAnfrage):
    try:
        posts = erstelle_posts(thema=anfrage.thema, anzahl=anfrage.anzahl)
        gespeichert = speichere_posts(posts)
        return {"erstellt": len(gespeichert), "posts": gespeichert}
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


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soraya · Content Studio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#0B0E1A;
    --panel:#12162A;
    --panel-2:#161B34;
    --gold:#C9A24B;
    --champagne:#E7D3A1;
    --mist:#C3C7D6;
    --mist-dim:#8A8FA6;
    --line:rgba(201,162,75,.22);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    background:
      radial-gradient(1100px 600px at 80% -10%, rgba(201,162,75,.10), transparent 60%),
      radial-gradient(900px 500px at -10% 10%, rgba(90,110,200,.12), transparent 55%),
      var(--ink);
    color:var(--mist);
    font-family:'Inter',system-ui,sans-serif;
    min-height:100vh;
    line-height:1.6;
    -webkit-font-smoothing:antialiased;
  }
  .wrap{max-width:780px;margin:0 auto;padding:56px 22px 80px}
  header{text-align:center;margin-bottom:44px}
  .eyebrow{
    font-size:11px;letter-spacing:.34em;text-transform:uppercase;
    color:var(--gold);margin:0 0 14px
  }
  h1{
    font-family:'Cormorant Garamond',serif;font-weight:500;
    font-size:clamp(38px,7vw,58px);line-height:1;letter-spacing:.01em;
    color:#F4EEDD;margin:0
  }
  h1 .star{color:var(--gold);font-size:.6em;vertical-align:middle;margin:0 .28em}
  .sub{color:var(--mist-dim);margin-top:14px;font-size:15px}
  .rule{display:flex;align-items:center;gap:14px;margin:34px 0 26px}
  .rule::before,.rule::after{content:"";height:1px;flex:1;background:var(--line)}
  .rule span{color:var(--gold);font-size:12px;letter-spacing:.2em}
  .panel{
    background:linear-gradient(180deg,var(--panel-2),var(--panel));
    border:1px solid var(--line);border-radius:16px;
    padding:22px;margin-bottom:18px;
  }
  .panel h2{
    font-family:'Cormorant Garamond',serif;font-weight:600;
    font-size:23px;color:var(--champagne);margin:0 0 4px
  }
  .panel p.hint{margin:0 0 16px;font-size:13px;color:var(--mist-dim)}
  label{display:block;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--mist-dim);margin:0 0 7px}
  .row{display:flex;gap:12px;flex-wrap:wrap}
  .row > .grow{flex:1;min-width:180px}
  input,select{
    width:100%;background:#0C1022;border:1px solid var(--line);
    color:#EFE7D2;border-radius:10px;padding:12px 14px;font-size:15px;
    font-family:inherit;outline:none;transition:border-color .2s;
  }
  input::placeholder{color:#5f647c}
  input:focus,select:focus{border-color:var(--gold)}
  button{
    font-family:inherit;cursor:pointer;border-radius:10px;font-size:14px;
    letter-spacing:.02em;border:1px solid var(--gold);
    background:linear-gradient(180deg,#D8B65E,#C9A24B);color:#1A140A;
    font-weight:600;padding:12px 20px;transition:transform .12s,filter .2s;
  }
  button:hover{filter:brightness(1.07)}
  button:active{transform:translateY(1px)}
  button:disabled{opacity:.55;cursor:default;filter:none;transform:none}
  button.ghost{background:transparent;color:var(--gold);border-color:var(--line);font-weight:500}
  button.ghost:hover{border-color:var(--gold)}
  .bar{display:flex;align-items:center;justify-content:space-between;margin:6px 2px 14px}
  .bar h3{font-family:'Cormorant Garamond',serif;font-weight:600;font-size:26px;color:var(--champagne);margin:0}
  #status{min-height:20px;text-align:center;font-size:14px;color:var(--gold);margin:8px 0 4px}
  .card{
    background:var(--panel);border:1px solid var(--line);border-radius:14px;
    padding:20px 20px 16px;margin-bottom:14px;position:relative;overflow:hidden;
  }
  .card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:linear-gradient(var(--gold),transparent)}
  .plat{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--gold);margin:0 0 10px}
  .txt{color:#E4E6EF;white-space:pre-wrap;margin:0 0 12px}
  .tags{color:var(--champagne);font-size:14px;margin:0 0 14px}
  .foot{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .stamp{font-size:12px;color:var(--mist-dim)}
  .empty{text-align:center;color:var(--mist-dim);padding:38px 10px;font-family:'Cormorant Garamond',serif;font-size:22px}
  .empty span{display:block;font-family:'Inter';font-size:13px;margin-top:8px}
  .spin{display:inline-block;width:15px;height:15px;border:2px solid var(--line);border-top-color:var(--gold);border-radius:50%;vertical-align:-2px;margin-right:8px}
  @media (prefers-reduced-motion:no-preference){.spin{animation:s .8s linear infinite}}
  @keyframes s{to{transform:rotate(360deg)}}
  footer{text-align:center;color:var(--mist-dim);font-size:12px;margin-top:40px;letter-spacing:.04em}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="eyebrow">Soraya Luxury Astrology</p>
    <h1>Content<span class="star">&#10022;</span>Studio</h1>
    <p class="sub">Lass die Sterne sprechen — fertige Posts fuer Instagram, Facebook und LinkedIn.</p>
  </header>

  <div class="panel">
    <h2>Aus einem Thema</h2>
    <p class="hint">Gib ein Stichwort ein, der Rest passiert von selbst.</p>
    <div class="row">
      <div class="grow"><label>Thema</label>
        <input id="thema" placeholder="z. B. Vollmond in der Waage" /></div>
      <div><label>Anzahl</label>
        <select id="anzahl1"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div>
    </div>
    <div style="margin-top:16px"><button id="btnThema" onclick="ausThema()">Posts erzeugen</button></div>
  </div>

  <div class="panel">
    <h2>Aus einer Webseite</h2>
    <p class="hint">Eine Quelle einlesen — Soraya macht daraus eigene Posts.</p>
    <div class="row">
      <div class="grow"><label>Webseite (URL)</label>
        <input id="url" placeholder="https://..." /></div>
      <div><label>Anzahl</label>
        <select id="anzahl2"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div>
    </div>
    <div style="margin-top:16px"><button id="btnUrl" onclick="ausUrl()">Aus Webseite erzeugen</button></div>
  </div>

  <div class="rule"><span>&#10022;</span></div>

  <div class="bar">
    <h3>Deine Posts</h3>
    <button class="ghost" onclick="ladePosts()">Aktualisieren</button>
  </div>
  <div id="status"></div>
  <div id="liste"></div>

  <footer>Soraya &#10022; Content Studio</footer>
</div>

<script>
const $ = (id) => document.getElementById(id);

function setBusy(btn, busy, text){
  btn.disabled = busy;
  if(busy){ btn.dataset.label = btn.textContent; btn.innerHTML = '<span class="spin"></span>' + text; }
  else if(btn.dataset.label){ btn.textContent = btn.dataset.label; }
}
function melde(msg){ $('status').textContent = msg || ''; }

function escapeHtml(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function renderPosts(posts){
  const box = $('liste');
  if(!posts || posts.length === 0){
    box.innerHTML = '<div class="empty">Noch keine Posts.<span>Gib oben ein Thema ein und leg los.</span></div>';
    return;
  }
  box.innerHTML = posts.map(p => {
    const datum = (p.created_at || '').slice(0,10);
    const tags = p.hashtags || '';
    const text = escapeHtml(p.text);
    return `<div class="card">
      <p class="plat">${escapeHtml(p.platform||'')}</p>
      <p class="txt">${text}</p>
      <p class="tags">${escapeHtml(tags)}</p>
      <div class="foot">
        <span class="stamp">${datum}</span>
        <button class="ghost" onclick='kopiere(this)' data-t="${encodeURIComponent((p.text||'')+'\\n\\n'+tags)}">Kopieren</button>
      </div>
    </div>`;
  }).join('');
}

function kopiere(btn){
  const t = decodeURIComponent(btn.dataset.t);
  navigator.clipboard.writeText(t).then(()=>{
    const alt = btn.textContent; btn.textContent = 'Kopiert \\u2713';
    setTimeout(()=>btn.textContent = alt, 1400);
  });
}

async function ladePosts(){
  melde('Lade Posts \\u2026');
  try{
    const r = await fetch('/content');
    const d = await r.json();
    renderPosts(d.posts);
    melde('');
  }catch(e){ melde('Konnte Posts nicht laden.'); }
}

async function ausThema(){
  const btn = $('btnThema');
  const thema = $('thema').value.trim();
  const anzahl = parseInt($('anzahl1').value,10);
  setBusy(btn, true, 'Die Sterne schreiben \\u2026');
  melde('');
  try{
    const r = await fetch('/content', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({thema: thema || null, anzahl})
    });
    if(!r.ok){ const e = await r.json(); throw new Error(e.detail || 'Fehler'); }
    await ladePosts();
    melde('Fertig \\u2713');
  }catch(e){ melde('Fehler: ' + e.message); }
  finally{ setBusy(btn, false); }
}

async function ausUrl(){
  const btn = $('btnUrl');
  const url = $('url').value.trim();
  const anzahl = parseInt($('anzahl2').value,10);
  if(!url){ melde('Bitte eine Webseite eingeben.'); return; }
  setBusy(btn, true, 'Lese Seite \\u2026 (kann dauern)');
  melde('');
  try{
    const r = await fetch('/content-von-url', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({url, anzahl})
    });
    if(!r.ok){ const e = await r.json(); throw new Error(e.detail || 'Fehler'); }
    await ladePosts();
    melde('Fertig \\u2713');
  }catch(e){ melde('Fehler: ' + e.message); }
  finally{ setBusy(btn, false); }
}

ladePosts();
</script>
</body>
</html>"""
