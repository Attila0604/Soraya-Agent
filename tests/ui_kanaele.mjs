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
    check("Posten: TikTok ohne video.list -> 'TikTok neu verbinden, um Zahlen zu sehen'", t.includes("TikTok neu verbinden, um Zahlen zu sehen"), t);
    check("Posten: LinkedIn läuft bald ab -> Knopf 'LinkedIn neu verbinden'", (await page.$$eval("#verbindungen a.knopf", (a) => a.map((x) => x.textContent))).includes("LinkedIn neu verbinden"), "");
    check("Posten: Warnung oben zum LinkedIn-Ablauf", (await page.textContent("#postWarnung")).includes("LinkedIn-Zugang läuft am"), await page.textContent("#postWarnung"));
    await page.$eval("#einstellungenPanel", (d) => { d.open = true; });
    check("Posten: LinkedIn angehakt", await page.isChecked("#plLinkedin"), "");
    check("Testpost: LinkedIn-Knopf für Feed-Post, nicht für Story", (await page.$$eval("#testposts .testpost", (l) => l.map((x) => x.textContent))).some((x) => x.includes("Story") && !x.includes("LinkedIn"))
      && (await page.$$("#testposts button[data-pl='linkedin']")).length === 2, await page.textContent("#testposts"));
    if (OUT) await (await page.$("#verbindungen")).screenshot({ path: OUT + "/posten-verbindungen.png" });
    if (OUT) await (await page.$("#einstellungenPanel")).screenshot({ path: OUT + "/posten-wohin.png" });
  }
  await page.click('.tab[data-tab="wirkung"]'); await wait(1800);
  const ig = await page.textContent("#igPanel");
  check(`Wirkung (${breite}): Instagram-Block mit Follower und Zuwachs`, /1[\s.\u202f\u00a0]?243\s*Follower/.test(ig) && ig.includes("+63 in 7 Tagen"), ig);
  check(`Wirkung (${breite}): Aufrufe, Gefällt mir, Kommentare, Gespeichert`, ["Aufrufe", "Gefällt mir", "Kommentare", "Gespeichert"].every((w) => ig.includes(w)), ig);
  check(`Wirkung (${breite}): Beiträge zugeklappt hinter 'Letzte Beiträge'`, !(await page.$eval("#igPanel details", (d) => d.open)), "");
  if (breite === 900) {
    await page.$eval("#igPanel details", (d) => { d.open = true; }); await wait(200);
    check("Wirkung: Tabelle mit 3 Beiträgen", (await page.$$eval("#igPanel tbody tr", (r) => r.length)) === 3, "");
    if (OUT) await (await page.$("#igPanel")).screenshot({ path: OUT + "/wirkung-instagram.png" });
    await page.$eval("details.wmehr", (d) => { d.open = true; }); await wait(300);
    check("Wirkung: TikTok-Hinweis neu verbinden", (await page.textContent("#ttPanel")).includes("TikTok neu verbinden, um Zahlen zu sehen"), await page.textContent("#ttPanel"));
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
  check(`Keine JS-Fehler (${breite})`, fehler.length === 0, fehler.join(" | "));
  await ctx.close();
}
await browser.close();
console.log(results.join("\n") + "\n=> " + (ok ? "ALLE BESTANDEN" : "FEHLER"));
