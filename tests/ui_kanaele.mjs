// UI-Test fuer Instagram-Zahlen, TikTok-Hinweis und LinkedIn-Ablauf.
// Start: DEMO_KANAELE=1 python tests/dev_server.py  ->  node tests/ui_kanaele.mjs http://127.0.0.1:8790 /tmp/shots
import { chromium } from "playwright";
const BASE = process.argv[2], OUT = process.argv[3];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium", args: ["--no-proxy-server"] });
const results = []; let ok = true;
const check = (n, c, i = "") => { ok &&= !!c; results.push((c ? "PASS " : "FAIL ") + n + (!c ? "  [" + i + "]" : "")); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

for (const breite of [900, 390]) {
  const ctx = await browser.newContext({ viewport: { width: breite, height: 1000 }, httpCredentials: { username: "soraya", password: "geheim-test" } });
  await ctx.route("**/*", (r) => (new URL(r.request().url()).hostname === "127.0.0.1" ? r.continue() : r.abort()));
  const page = await ctx.newPage();
  const fehler = []; page.on("pageerror", (e) => fehler.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource|ERR_FAILED/.test(m.text()) && fehler.push(m.text()));
  page.on("dialog", (d) => d.accept());
  await page.goto(BASE + "/#posten", { waitUntil: "load" }); await wait(1200);
  const t = await page.textContent("#verbindungen");
  if (breite === 900) {
    check("Posten: Instagram verbunden, keine Zahlen-Warnung (Recht da)", t.includes("soraya.astroguide") && !t.includes("Instagram neu verbinden"), t);
    check("Posten: TikTok ohne video.list -> kein Neu-verbinden-Hinweis", !t.includes("TikTok neu verbinden, um Zahlen zu sehen"), t);
    check("Posten: LinkedIn läuft bald ab -> Knopf 'LinkedIn neu verbinden'", (await page.$$eval("#verbindungen a.knopf", (a) => a.map((x) => x.textContent))).includes("LinkedIn neu verbinden"), "");
    check("Posten: Warnung oben zum LinkedIn-Ablauf", (await page.textContent("#postWarnung")).includes("LinkedIn-Zugang läuft am"), await page.textContent("#postWarnung"));
    await page.$eval("#einstellungenPanel", (d) => { d.open = true; });
    check("Posten: LinkedIn angehakt", await page.isChecked("#plLinkedin"), "");
    check("Testpost: LinkedIn-Knopf für Feed-Post, nicht für Story", (await page.$$eval("#testposts .testpost", (l) => l.map((x) => x.textContent))).some((x) => x.includes("Story") && !x.includes("LinkedIn"))
      && (await page.$$("#testposts button[data-pl='linkedin']")).length === 3, await page.textContent("#testposts"));
    if (OUT) await (await page.$("#verbindungen")).screenshot({ path: OUT + "/posten-verbindungen.png" });
    if (OUT) await (await page.$("#einstellungenPanel")).screenshot({ path: OUT + "/posten-wohin.png" });
  }
  await page.click('.tab[data-tab="wirkung"]'); await wait(1800);
  // Zahlen-Cockpit mit reichen Demo-Daten (3 Plattformen, 30 Tage)
  const kpis = await page.$$eval(".wz-kpi", (k) => k.map((x) => x.querySelector(".v").textContent + "|" + x.querySelector(".trend").className));
  check(`Cockpit (${breite}): 4 Kacheln mit Zahl und Pfeil`, kpis.length === 4 && kpis.every((k) => /^[\d\s.\u202f\u00a0]+\|trend (auf|ab|neutral)$/.test(k)) && kpis.some((k) => /auf|ab/.test(k)), JSON.stringify(kpis));
  const fol = await page.textContent(".wz-follower");
  check(`Cockpit (${breite}): Follower Facebook · Instagram · TikTok mit Zuwachs`, (await page.$$(".wz-follower .f")).length === 3 && (fol.match(/diese Woche/g) || []).length === 3, fol);
  check(`Cockpit (${breite}): Top 3 mit Bild und Punkten`, (await page.$$("ol.top3 li")).length === 3 && (await page.$$("ol.top3 li .wz-daumen img")).length === 3 && (await page.textContent("ol.top3")).includes("Punkte"), "");
  const pkt = await page.$$eval("ol.top3 .pkt b", (b) => b.map((x) => +x.textContent.replace(/\D/g, "")));
  check(`Cockpit (${breite}): Top 3 absteigend`, pkt[0] >= pkt[1] && pkt[1] >= pkt[2], JSON.stringify(pkt));
  check(`Cockpit (${breite}): schwächster Schritt markiert mit Tipp`, (await page.$$(".trichter2 .tr-stufe.schwach")).length === 1 && !(await page.$eval(".weg-tipp", (e) => e.classList.contains("leise"))), await page.textContent(".wz-weg"));
  check(`Cockpit (${breite}): Soraya lernt nennt das beste Format`, (await page.textContent("dl.lernt .mehr dd")).includes("Ritual") && (await page.textContent("dl.lernt .weniger dd")).includes("Rückblick"), await page.textContent("dl.lernt"));
  const erk = await page.$$eval("ol.erkennt li.erk", (l) => l.map((x) => x.textContent.replace(/\s+/g, " ").trim()));
  check(`Soraya erkennt (${breite}): 3–5 Karten mit Zahl`, erk.length >= 3 && erk.length <= 5 && erk.some((x) => /\d/.test(x)) && !erk.some((x) => x.includes("zu wenig Daten")), JSON.stringify(erk));
  await page.click('[data-wr="posts"]'); await wait(300);
  const zeilen = await page.$$eval("table.wz-posts tbody tr", (r) => r.length);
  await page.click('[data-wz-pl="tiktok"]'); await wait(200);
  const tt = await page.$$eval("table.wz-posts tbody tr .post .meta", (r) => r.map((x) => x.textContent));
  check(`Cockpit (${breite}): Filter TikTok zeigt nur Reels`, tt.length > 0 && tt.every((x) => x.includes("Reel")), JSON.stringify(tt));
  await page.click('[data-wz-pl="alle"]'); await page.selectOption("#wzSort", "datum"); await wait(200);
  const daten = await page.$$eval("table.wz-posts tbody tr .post .meta", (r) => r.map((x) => x.textContent.split(" · ")[0]));
  check(`Cockpit (${breite}): sortiert nach Datum`, daten.length === zeilen && daten[0] !== daten[daten.length - 1], JSON.stringify(daten));
  await page.selectOption("#wzSort", "punkte");
  await page.click("table.wz-posts tbody tr:first-child button.wz-titel"); await wait(400);
  const sd = await page.textContent("#wzPost");
  check(`Post-Details (${breite}): Schublade mit Plattform-Zahlen, Punkten und Zeitleiste`, await page.$eval("#wzPost", (d) => d.open) && sd.includes("Zeitleiste") && sd.includes("Gepostet auf")
    && (await page.$$("#wzPost .sd-pl")).length >= 2 && sd.includes("dein Schnitt"), sd.slice(0, 300));
  if (OUT) await page.screenshot({ path: OUT + `/schublade-${breite}.png` });
  await page.keyboard.press("Escape"); await wait(200);
  check(`Post-Details (${breite}): mit Escape zu`, !(await page.$eval("#wzPost", (d) => d.open)), "");
  await page.click('[data-wr="plattformen"]'); await wait(500);
  check(`Plattformen (${breite}): Vergleich in 3 Gruppen, Reichweite je Tag gestapelt, Follower-Linien`, (await page.$$(".pv-gruppe")).length === 3 && (await page.$$eval("#wzTage .hit", (x) => x.length)) === 7
    && (await page.$$("#wzTage .seg")).length >= 5 && (await page.$$("#wzFollower polyline")).length >= 2, "");
  await page.hover("#wzTage .hit >> nth=5"); await wait(150);
  check(`Plattformen (${breite}): Werte beim Zeigen`, !(await page.$eval("#wzTip", (t) => t.classList.contains("hide"))) && (await page.textContent("#wzTip")).includes("erreicht"), "");
  await page.click('[data-wr="lernen"]'); await wait(500);
  check(`Lernen (${breite}): Heatmap mit eingestellten Zeiten, Selbst-Tests, Sprachen`, (await page.$$("table.hm button.hm-zelle")).length >= 5 && (await page.$$("table.hm .hm-marke")).length >= 2
    && (await page.textContent("#wCockpit")).includes("Neugier-Lücke") && (await page.textContent(".wz-spr")).includes("Deutsch"), "");
  if (breite === 390) { const w = await page.evaluate(() => document.documentElement.scrollWidth); check("Handy: Lernen ohne Querscrollen", w <= 390, w); }
  await page.click('[data-wr="plattformen"]'); await wait(300);
  if (breite === 900) {
    await page.click('#wZeitraum [data-tage="30"]'); await wait(1500);
    await page.click('[data-wr="posts"]'); await wait(300);
    check("Cockpit: 30 Tage, mehr Posts in der Tabelle", (await page.textContent("#wzAnzahl")).match(/\d+/) && +(await page.textContent("#wzAnzahl")).match(/\d+/)[0] > 30, await page.textContent("#wzAnzahl"));
    if (OUT) await page.screenshot({ path: OUT + "/cockpit-30.png", fullPage: true });
    await page.click('#wZeitraum [data-tage="7"]'); await wait(1200);
    await page.click('[data-wr="plattformen"]'); await wait(300);
  }
  await page.click("#wDetails > summary"); await wait(2500);
  const ig = await page.textContent("#igPanel");
  check(`Wirkung (${breite}): Instagram-Block mit Follower und Zuwachs`, /1[\s.\u202f\u00a0]?243\s*Follower/.test(ig) && ig.includes("+63 in 7 Tagen"), ig);
  check(`Wirkung (${breite}): Aufrufe, Gefällt mir, Kommentare, Gespeichert`, ["Aufrufe", "Gefällt mir", "Kommentare", "Gespeichert"].every((w) => ig.includes(w)), ig);
  check(`Wirkung (${breite}): Beiträge zugeklappt hinter 'Letzte Beiträge'`, !(await page.$eval("#igPanel details", (d) => d.open)), "");
  if (breite === 900) {
    await page.$eval("#igPanel details", (d) => { d.open = true; }); await wait(200);
    check("Wirkung: Tabelle mit den Beiträgen", (await page.$$eval("#igPanel tbody tr", (r) => r.length)) >= 4, "");
    if (OUT) await (await page.$("#igPanel")).screenshot({ path: OUT + "/wirkung-instagram.png" });
    check("Wirkung: TikTok-Hinweis aufs TikTok Studio", (await page.textContent("#ttPanel")).includes("TikTok Studio"), await page.textContent("#ttPanel"));
    const lern = await page.textContent("#lernPanel");
    check("Wirkung: Lernen nutzt Instagram-Zahlen", lern.includes("mal gespeichert") && lern.includes("Punkte"), lern);
    if (OUT) await (await page.$("#lernPanel")).screenshot({ path: OUT + "/wirkung-lernen.png" });
  } else {
    const w = await page.evaluate(() => document.documentElement.scrollWidth);
    check("Handy: Wirkung ohne Querscrollen", w <= 390, w);
    if (OUT) await page.screenshot({ path: OUT + "/handy-wirkung-instagram.png", fullPage: false, clip: undefined });
    await page.click('.tab[data-tab="posten"]'); await wait(900);
    const w2 = await page.evaluate(() => document.documentElement.scrollWidth);
    check("Handy: Posten ohne Querscrollen", w2 <= 390, w2);
    if (OUT) await (await page.$("#verbindungen")).screenshot({ path: OUT + "/handy-verbindungen.png" });
  }
  if (breite === 900) {
    // "Übernehmen": trägt die Uhrzeit nur ein -- gespeichert wird nichts, kein Schalter wird umgelegt
    await page.click('.tab[data-tab="wirkung"]'); await wait(1200);
    await page.click('[data-wr="ueberblick"]'); await page.click('#wZeitraum [data-tage="30"]'); await wait(1500);
    const erk30 = await page.textContent("ol.erkennt");
    check("Soraya erkennt (30 Tage): Reels um 9 Uhr besser, mit Übernehmen", erk30.includes("Reels um 9 Uhr laufen besser als um 19 Uhr") && (await page.$$("ol.erkennt [data-zeit-platz='reel']")).length === 1, erk30);
    if (OUT) await (await page.$(".wz-erkennt")).screenshot({ path: OUT + "/soraya-erkennt.png" });
    const vorher = (await (await page.request.get(BASE + "/posten")).json()).einstellungen;
    await page.click("ol.erkennt [data-zeit-platz='reel']"); await wait(1500);
    const nachher = (await (await page.request.get(BASE + "/posten")).json()).einstellungen;
    check("Übernehmen: Reel-Zeit 09:00 eingetragen, nicht gespeichert", (await page.inputValue("#zReel")) === "09:00" && await page.$eval("#einstellungenPanel", (d) => d.open)
      && !(await page.$eval("#postUngespeichert", (e) => e.hidden)) && nachher.zeiten.reel === vorher.zeiten.reel && nachher.an === vorher.an, JSON.stringify(nachher.zeiten));
    check("Übernehmen: Schalter unverändert", (await page.isChecked("#postAuto")) === vorher.an, "");
    if (OUT) await (await page.$("#einstellungenPanel")).screenshot({ path: OUT + "/uebernehmen.png" });
  }
  check(`Keine JS-Fehler (${breite})`, fehler.length === 0, fehler.join(" | "));
  await ctx.close();
}
await browser.close();
console.log(results.join("\n") + "\n=> " + (ok ? "ALLE BESTANDEN" : "FEHLER"));
