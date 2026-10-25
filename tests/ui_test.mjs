import { chromium } from "playwright";
const BASE = process.argv[2], OUT = process.argv[3];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium", args: ["--no-proxy-server"] });
const results = []; let ok = true;
const check = (n, c, i = "") => { ok &&= !!c; results.push((c ? "PASS " : "FAIL ") + n + (!c ? "  [" + i + "]" : "")); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function seite(breite = 900, anmeldung = true) {
  const ctx = await browser.newContext({ viewport: { width: breite, height: 1000 }, permissions: ["clipboard-read", "clipboard-write"], ...(anmeldung ? { httpCredentials: { username: "soraya", password: "geheim-test" } } : {}) });
  await ctx.route("**/*", (r) => { const h = new URL(r.request().url()).hostname; return h === "127.0.0.1" ? r.continue() : r.abort(); });
  const page = await ctx.newPage();
  const fehler = []; page.on("pageerror", (e) => fehler.push(e.message)); page.on("console", (m) => m.type() === "error" && !/Failed to load resource|ERR_FAILED/.test(m.text()) && fehler.push(m.text()));
  page.on("dialog", (d) => d.accept());
  const antwort = await page.goto(BASE + "/", { waitUntil: "load" });
  return { ctx, page, fehler, antwort };
}

// Ohne Anmeldung gesperrt
{ const r = await fetch(BASE + "/");
  check("Ohne Anmeldung: 401 mit Anmeldefenster", r.status === 401 && /Basic/.test(r.headers.get("www-authenticate") || ""), r.status); }

const { ctx, page, fehler } = await seite(900);
await wait(800);
check("Heute: Himmel geladen", /Zunehmende Sichel · Mond in Skorpion/.test(await page.textContent("#himmelText")), await page.textContent("#himmelText"));
check("Heute: Vollmond in 2 Tagen", /Vollmond .* \(in 2 Tagen\)/.test(await page.textContent("#himmelText")), "");
check("Heute: vier Sprachen, noch nichts erstellt", (await page.$$eval("#laeufe .lauf.fehlt", (x) => x.length)) === 4, "");
check("Automatik: standardmäßig aus", !(await page.isChecked("#planAuto")) && (await page.textContent("#planInfo")).includes("nichts von selbst"), await page.textContent("#planInfo"));
await page.check("#planAuto"); await wait(700);
check("Automatik: einschalten (mit Rückfrage)", await page.isChecked("#planAuto") && (await page.textContent("#planInfo")).startsWith("An:"), await page.textContent("#planInfo"));
await page.uncheck("#planAuto"); await wait(700);
check("Automatik: wieder aus", !(await page.isChecked("#planAuto")) && (await page.textContent("#status")).includes("Automatik ist aus"), await page.textContent("#status"));

check("Kopf: schmal (höchstens 80 px)", (await page.$eval(".kopfzeile", (e) => e.offsetHeight)) <= 80, await page.$eval(".kopfzeile", (e) => e.offsetHeight));
await page.click("#btnPlanJetzt");
await wait(1200);
check("Heute: Läufe werden angezeigt", (await page.$$eval("#laeufe .lauf.laeuft, #laeufe .lauf.fertig", (x) => x.length)) >= 1, await page.textContent("#laeufe"));
check("Heute: Knopf gesperrt, solange es läuft", await page.$eval("#btnPlanJetzt", (b) => b.disabled), "");
for (let i = 0; i < 40; i++) { if ((await page.$$eval("#laeufe .lauf.fertig, #laeufe .lauf.fehler", (x) => x.length)) === 4) break; await wait(500); }
check("Fehler: IT im Fehlerkasten mit Meldung", /IT:\s*Der Anthropic-Schlüssel/.test(await page.textContent("#planFehler")) && await page.isVisible("#planFehler"), await page.textContent("#planFehler"));
check("Fehler: Knopf heißt 'Nochmal versuchen'", (await page.textContent("#btnPlanJetzt")).trim() === "Nochmal versuchen", await page.textContent("#btnPlanJetzt"));
if (OUT) await page.screenshot({ path: OUT + "/ui-fehler.png" });
await page.click("#btnPlanJetzt"); await wait(800);
for (let i = 0; i < 40; i++) { if ((await page.$$eval("#laeufe .lauf.fertig", (x) => x.length)) === 4) break; await wait(500); }
check("Heute: alle 4 Sprachen fertig (sofort wiederholt)", (await page.$$eval("#laeufe .lauf.fertig", (x) => x.length)) === 4, await page.textContent("#laeufe"));
check("Fehler: Kasten wieder weg", !(await page.isVisible("#planFehler")), "");
check("Heute: Knopf zeigt 'Alles erstellt ✓' und ist gesperrt", (await page.textContent("#btnPlanJetzt")).includes("Alles erstellt") && await page.$eval("#btnPlanJetzt", (b) => b.disabled), await page.textContent("#btnPlanJetzt"));
check("Heute: Fortschrittsbox sichtbar (nicht vom Ladebalken-Stil verdeckt)", (await page.$eval("#fortschritt", (e) => e.offsetHeight)) > 30, await page.$eval("#fortschritt", (e) => e.offsetHeight));
check("Karte: Status 'Nicht posten' wählbar", (await page.$$eval('#heuteListe .card:first-child [data-aktion="status"] option', (o) => o.map((x) => x.textContent))).includes("Nicht posten"), "");
check("Heute: Fortschritt 0 von 16", /Heute: 0 von 16 gepostet · 0 freigegeben/.test(await page.textContent("#fortschritt")), await page.textContent("#fortschritt"));
check("Heute: 4 Karten auf Deutsch (Post, Reel, 2. Reel, Story)", JSON.stringify(await page.$$eval("#heuteListe .card .kopf .tag:first-child", (x) => x.map((e) => e.textContent))) === JSON.stringify(["Feed-Post", "Reel", "2. Reel", "Story"]), JSON.stringify(await page.$$eval("#heuteListe .card .kopf .tag:first-child", (x) => x.map((e) => e.textContent))));
check("Heute: Kommentar-Frage vor der Handlungsaufforderung ergänzt", /👇|🌙|✨|\?/.test((await page.textContent("#heuteListe .card:first-child")).split("Link in Bio")[0].slice(-120)), "");
check("Heute geht raus: vier Zeilen mit 2. Reel", (await page.$$eval("#raus > li[data-id]", (l) => l.length)) === 4 && (await page.textContent("#raus")).includes("2. Reel"), await page.textContent("#raus"));
for (let i = 0; i < 20 && !(await page.textContent("#heuteListe .card:first-child .wirk")); i++) await wait(250);
check("Karte: Zahlen über den Post-Link", /34 Besuche.*9 Schnellstarts.*3 × Registrieren.*2 neue Konten/.test(await page.textContent("#heuteListe .card:first-child .wirk")), await page.textContent("#heuteListe .card:first-child .wirk"));
check("Karte ohne Link-Daten: keine leere Zeile", !(await page.isVisible("#heuteListe .card:nth-child(2) .wirk")), "");
await page.click('#heuteListe .card:first-child [data-aktion="link"]'); await wait(300);
check("Karte: Link kopieren", (await page.evaluate(() => navigator.clipboard.readText())) === "https://www.sorayaluxuryastroguide.com/?q=p1&lang=de", await page.evaluate(() => navigator.clipboard.readText()));
check("Cockpit: drei Kacheln mit Stand", (await page.$$("#cockpit .kachel")).length === 3 && (await page.textContent("#cockpit")).includes("Posten aus"), await page.textContent("#cockpit"));
for (let i = 0; i < 20 && !(await page.$("#wochenbericht .wochen-karte")); i++) await wait(250);
check("Wochenbericht: Karte 'Letzte Woche' auf Heute", (await page.textContent("#wochenbericht")).includes("Letzte Woche") && (await page.textContent("#wochenbericht")).includes("Soraya testet diese Woche"), await page.textContent("#wochenbericht"));
if (OUT) await (await page.$("#wochenbericht")).screenshot({ path: OUT + "/ui-wochenbericht.png" });
await page.click("#wochenbericht [data-woche-zu]"); await wait(400);
check("Wochenbericht: wegklicken", !(await page.$("#wochenbericht .wochen-karte")), "");
{ const r = await page.evaluate(() => fetch("/wirkung/wochenbericht").then((x) => x.json()));
  check("Wochenbericht: bleibt weg (gemerkt)", r.zeigen === false, JSON.stringify(r)); }
await page.waitForFunction(() => { const i = document.querySelector("#heuteListe .vorschau img"); return i && i.complete && i.naturalWidth === 300; }, null, { timeout: 30000 }).catch(() => {});
check("Karte: Vorschaubild vom Server (300 px)", await page.$eval("#heuteListe .vorschau img", (i) => i.naturalWidth) === 300, "");
check("Heute: Karte zeigt das Format des Tages", /Deine Woche|Sternzeichen im Fokus|Liebe & Beziehung|Astro-Wissen|Ritual|Mitmachen|Rückblick|Großes Ereignis/.test(await page.textContent("#heuteListe .card .kopf")), await page.textContent("#heuteListe .card .kopf"));
check("Heute: leichter Hinweis bei zu kurzem Feed-Text (geht trotzdem raus)", (await page.textContent("#heuteListe .card:first-child")).includes("geht trotzdem automatisch raus") && (await page.textContent("#heuteListe .card:first-child")).includes("Text zu kurz"), "");
check("Heute: Bild-Punkte sichtbar", (await page.textContent("#heuteListe .card:first-child")).includes("Im Bild: Skorpion: ehrlich sein"), "");
check("Heute: Tagesplan-Sprachen wählbar (4 an)", (await page.$$("#planSprachen input:checked")).length === 4, "");
check("Heute: deutsche Karte zeigt passende Zielgruppe (Österreich)", (await page.textContent("#heuteListe .card .kopf")).includes("Für: Liebe"), await page.textContent("#heuteListe .card .kopf"));
check("Heute: Reel zeigt Skript", /Hook:.*Spürst du es auch/.test(await page.textContent("#heuteListe")), "");
if (OUT) await page.screenshot({ path: OUT + "/ui-heute.png", fullPage: true });
await page.click('#heuteSprachen [data-s="hu"]'); await wait(600);
check("Heute: Ungarisch umschalten", (await page.textContent("#heuteListe")).includes("A Hold erőt gyűjt"), "");
await page.click('#heuteSprachen [data-s="de"]'); await wait(600);

// Bild (zeichnet jetzt der Server)
const pixel = (sel, x, y, w, h, test) => page.$eval(sel, async (img, [x, y, w, h, test]) => {
  await img.decode().catch(() => {});
  const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext("2d"); g.drawImage(img, 0, 0);
  const d = g.getImageData(x, y, w || c.width, h || c.height).data; let n = 0;
  for (let i = 0; i < d.length; i += 4) if (new Function("r", "g", "b", "return " + test)(d[i], d[i + 1], d[i + 2])) n++;
  return n; }, [x, y, w, h, test]);
const speichere = async (name) => { if (!OUT) return; const fs = await import("node:fs");
  const r = await page.evaluate(async () => { const b = await (await fetch(document.querySelector("#bild").src)).arrayBuffer(); return Array.from(new Uint8Array(b)); });
  fs.writeFileSync(OUT + "/" + name, Buffer.from(r)); };
await page.click('#heuteListe .card:first-child [data-aktion="bild"]');
await page.waitForFunction(() => document.querySelector("#bild")?.complete && document.querySelector("#bild").naturalWidth > 0, null, { timeout: 15000 });
let groesse = await page.$eval("#bild", (c) => [c.naturalWidth, c.naturalHeight]);
check("Bild: Feed-Post startet im Feed-Format 1080x1350", groesse.join("x") === "1080x1350", groesse.join("x"));
const bunt = await pixel("#bild", 0, 0, 0, 0, "r > 200 && g > 180");
check("Bild: Inhalt gezeichnet (Mond, Schrift)", bunt > 2000, bunt);
await speichere("bild-feed.jpg");
await page.click('[data-format="story"]');
await page.waitForFunction(() => document.querySelector("#bild").naturalHeight === 1920 && document.querySelector("#bild").complete, null, { timeout: 15000 });
groesse = await page.$eval("#bild", (c) => [c.naturalWidth, c.naturalHeight]);
check("Bild: Story-Format 1080x1920", groesse.join("x") === "1080x1920", groesse.join("x"));
await speichere("bild-story.jpg");
const [download] = await Promise.all([page.waitForEvent("download"), page.click("#bLaden")]);
check("Bild: Herunterladen liefert JPG", /^soraya-\d{4}-\d\d-\d\d-post-de-story\.jpg$/.test(download.suggestedFilename()), download.suggestedFilename());
await page.click("#bZu");

// Video zum Reel
check("Video: Knopf nur beim Reel", (await page.$$("#heuteListe [data-aktion=video]")).length === 2, "");
await page.click('#heuteListe [data-aktion="video"]'); await wait(800);
check("Video: Fortschritt sichtbar", (await page.textContent("#vBox")).includes("Video wird erstellt"), await page.$eval("#vBox", (e) => e.innerHTML.slice(0, 300)));
await page.waitForSelector("#vVideo", { timeout: 120000 });
// Test-Chromium kann kein H.264 abspielen (echtes Chrome/Safari/Handy schon) -> Datei selbst pruefen
const vkopf = await page.evaluate(async () => { const src = document.querySelector("#vVideo").src; const r = await fetch(src);
  const b = new Uint8Array(await r.arrayBuffer()); return [r.headers.get("content-type"), String.fromCharCode(...b.slice(4, 8)), b.length]; });
check("Video: fertig, MP4 im Player", vkopf[0] === "video/mp4" && vkopf[1] === "ftyp" && vkopf[2] > 100000, vkopf.join(" "));
const [vdl] = await Promise.all([page.waitForEvent("download"), page.click("#vLaden")]);
check("Video: Herunterladen liefert MP4", /^soraya-\d{4}-\d\d-\d\d-reel-de\.mp4$/.test(vdl.suggestedFilename()), vdl.suggestedFilename());
if (OUT) await vdl.saveAs(OUT + "/reel-de.mp4");
await page.click("#vZu");
await page.click('#heuteListe [data-aktion="video"]'); await wait(900);
check("Video: zweites Öffnen sofort fertig (Zwischenspeicher)", (await page.$$("#vVideo")).length === 1, "");
await page.click("#vZu");

// Freigeben mit einem Klick
await page.click('#heuteListe .card:nth-child(3) [data-schnell="freigegeben"]'); await wait(900);
check("Schnell-Freigabe", (await page.textContent("#heuteListe .card:nth-child(3) .st")) === "Freigegeben" && (await page.$$('#heuteListe .card:nth-child(3) [data-schnell="entwurf"]')).length === 1, await page.textContent("#heuteListe .card:nth-child(3) .st"));
await page.click('#heuteListe .card:nth-child(3) [data-schnell="entwurf"]'); await wait(900);
check("Freigabe zurücknehmen", (await page.textContent("#heuteListe .card:nth-child(3) .st")) === "Entwurf", "");
// Status, Bearbeiten
await page.selectOption('#heuteListe .card:nth-child(2) [data-aktion="status"]', "freigegeben"); await wait(700);
check("Status: freigegeben gespeichert", (await page.textContent("#heuteListe .card:nth-child(2) .st")) === "Freigegeben", "");
check("Heute: Fortschritt zählt Freigabe", /0 von 16 gepostet · 1 freigegeben/.test(await page.textContent("#fortschritt")), await page.textContent("#fortschritt"));
check("Karte: kein Löschen-Knopf mehr direkt auf der Karte", (await page.$$("#heuteListe [data-aktion=loeschen]")).length === 0, "");
// Story-Bild: Frage steht im Bild (helle Schrift im unteren Mittelteil)
await page.click('#heuteListe .card:nth-child(4) [data-aktion="bild"]');
await page.waitForFunction(() => document.querySelector("#bild")?.complete && document.querySelector("#bild").naturalWidth > 0, null, { timeout: 15000 });
const frageHell = await pixel("#bild", 160, 1150, 760, 420, "r > 210 && b > 210");
check("Bild: Story-Frage steht im Bild", frageHell > 1500, frageHell);
await speichere("bild-story-frage.jpg");
await page.click("#bZu");
await page.click('#heuteListe .card:first-child [data-aktion="bearbeiten"]');
await page.fill("#eTitel", "Mein eigener Titel"); await page.click("#eSpeichern"); await wait(700);
check("Bearbeiten: Titel gespeichert", (await page.textContent("#heuteListe .card:first-child .titel")) === "Mein eigener Titel", "");

// Plan
await page.click('.tab[data-tab="plan"]'); await wait(900);
check("Plan: heutiger Tag markiert", (await page.$$eval(".tag-kopf.heute", (x) => x.length)) === 1, "");
check("Plan: 16 Posts geplant", /16\s*geplant/.test(await page.textContent("#planZaehler")), await page.textContent("#planZaehler"));
check("Plan: kompakte Zeilen, zugeklappt", (await page.$$eval("#planListe > details.pz", (x) => x.length)) === 16 && (await page.$$eval("#planListe > details.pz[open]", (x) => x.length)) === 0, "");
check("Plan: Tagesstand je Sprache am heutigen Tag", (await page.$$eval(".tag-kopf.heute .tagstand .fertig", (x) => x.length)) === 4, "");
await page.click("#btnAufklappen"); await wait(200);
check("Plan: Alle aufklappen", (await page.$$eval("#planListe > details.pz[open]", (x) => x.length)) === 16, "");
await page.click("#btnAufklappen"); await wait(200);
// Wochenpaket
await page.click("#btnPaket"); await wait(300);
check("Paket: Dialog mit 4 Sprachen", (await page.$$("#pSprachen input:checked")).length === 4, "");
for (const s of ["de", "en", "hu"]) await page.uncheck(`#pSprachen input[value="${s}"]`);
await page.click("#pStart"); await wait(900);
check("Paket: leer -> Hinweis", (await page.textContent("#pStand")).includes("keine passenden Posts"), await page.textContent("#pStand"));
await page.check('#pSprachen input[value="de"]'); await page.uncheck('#pSprachen input[value="it"]');
await page.click("#pStart");
await page.waitForSelector("#pLaden:not(.hide)", { timeout: 120000 });
check("Paket: fertig (1 freigegebener DE-Post)", /Fertig ✓ 1 Posts/.test(await page.textContent("#pStand")), await page.textContent("#pStand"));
const [zdl] = await Promise.all([page.waitForEvent("download"), page.click("#pLaden")]);
check("Paket: ZIP herunterladen", /^Soraya-Woche_\d{4}-\d\d-\d\d_bis_\d{4}-\d\d-\d\d\.zip$/.test(zdl.suggestedFilename()), zdl.suggestedFilename());
if (OUT) await zdl.saveAs(OUT + "/wochenpaket.zip");
await page.click("#pZu");
await page.locator("#planListe > details.pz summary").first().click(); await wait(200);
check("Plan: eine Zeile aufklappen zeigt die Karte", await page.locator("#planListe > details.pz").first().locator(".card .txt").isVisible(), "");
await page.selectOption("#planSprache", "it"); await wait(700);
check("Plan: Filter Italienisch", (await page.$$eval("#planListe .card", (x) => x.length)) === 4, "");
await page.selectOption("#planSprache", ""); await page.selectOption("#planStatus", "freigegeben"); await wait(700);
check("Plan: Filter Freigegeben", (await page.$$eval("#planListe .card", (x) => x.length)) === 1, "");
await page.selectOption("#planStatus", ""); await wait(500);
// Datum verschieben auf morgen
const morgen = await page.evaluate(() => { const d = new Date(); d.setDate(d.getDate() + 1); return iso(d); });
const offeneId = await page.locator("#planListe > details.pz[open]").first().getAttribute("data-pz");
await page.fill(`#planListe details[data-pz="${offeneId}"] [data-aktion="datum"]`, morgen);
await page.$eval(`#planListe details[data-pz="${offeneId}"] [data-aktion="datum"]`, (e) => e.dispatchEvent(new Event("change", { bubbles: true }))); await wait(800);
const morgenAnzahl = await page.evaluate((m) => [...document.querySelectorAll("#planListe .card")].filter((c) => c.querySelector('[data-aktion="datum"]').value === m).length, morgen);
check("Plan: Post auf morgen verschoben", morgenAnzahl === 1, morgenAnzahl);
await page.click("#wocheVor"); await wait(700);
check("Plan: nächste Woche leer oder mit verschobenem Post", (await page.textContent("#wocheLabel")).includes("–"), "");
await page.click("#wocheZurueck"); await wait(600);
if (OUT) await page.screenshot({ path: OUT + "/ui-plan.png", fullPage: false });
// Loeschen (im Bearbeiten-Dialog)
const vorher = await page.$$eval("#planListe .card", (x) => x.length);
const letzte = page.locator("#planListe > details.pz").last();
await letzte.evaluate((d) => { d.open = true; }); await letzte.locator('[data-aktion="bearbeiten"]').click(); await page.click("#eLoeschen"); await wait(800);
check("Plan: Löschen über Bearbeiten", (await page.$$eval("#planListe .card", (x) => x.length)) === vorher - 1, "");

// Vorplanen
await page.click("#btnVorplanen"); await wait(1000);
check("Vorplanen: Stand wird angezeigt", /Vorplanen/.test(await page.textContent("#vorplanStand")), await page.textContent("#vorplanStand"));
for (let i = 0; i < 60; i++) { if (/abgeschlossen/.test(await page.textContent("#vorplanStand"))) break; await wait(1000); }
check("Vorplanen: 28 von 28 fertig", /abgeschlossen: 28 von 28 fertig/.test(await page.textContent("#vorplanStand")), await page.textContent("#vorplanStand"));
await page.click("#wocheVor"); await wait(800);
const tageMitPlan = await page.$$eval(".tag-kopf", (k) => k.filter((x) => x.querySelectorAll(".tagstand .fertig").length === 4).length);
check("Vorplanen: nächste Woche hat vorgeplante Tage", tageMitPlan >= 1, tageMitPlan);
await page.click("#wocheZurueck"); await wait(600);
if (OUT) await page.screenshot({ path: OUT + "/ui-plan-kompakt.png", fullPage: false });

// Studio
await page.click('.tab[data-tab="studio"]'); await wait(500);
await page.fill("#thema", "Venus rückläufig"); await page.selectOption("#sprache1", "it");
await page.click("#btnThema");
await page.waitForFunction(() => [...document.querySelectorAll("#studioListe .card")].filter((c) => c.textContent.includes("IT")).length >= 3, null, { timeout: 20000 }).catch(() => {});
check("Studio: 3 Posts auf Italienisch erstellt", (await page.$$eval("#studioListe .card", (x) => x.filter((c) => c.textContent.includes("IT")).length)) === 3, "");
check("Studio: Himmel-Posts erscheinen hier nicht", !(await page.textContent("#studioListe")).includes("Himmel"), "");

await page.click('.tab[data-tab="plan"]'); await wait(800);
check("Plan: Ideen ohne Datum eingeklappt unten", /Ideen ohne Datum \(3\)/.test(await page.textContent("details.ideen summary")) && !(await page.$eval("details.ideen", (d) => d.open)), "");

// Wirkung: vier Unterreiter (Überblick, Posts, Plattformen, Lernen), Rohdaten unter Plattformen
await page.click('.tab[data-tab="wirkung"]'); await wait(1500);
check("Wirkung: 4 Unterreiter, Überblick zuerst", JSON.stringify(await page.$$eval("#wReiter [role=tab]", (x) => x.map((e) => e.textContent))) === JSON.stringify(["Überblick", "Posts", "Plattformen", "Lernen"])
  && (await page.getAttribute('[data-wr="ueberblick"]', "aria-selected")) === "true", "");
check("Cockpit: 4 Kacheln (Erreicht, Reaktionen, Besuche, Neue Konten)", JSON.stringify(await page.$$eval(".wz-kpi .l", (x) => x.map((e) => e.firstChild.textContent.trim()))) === JSON.stringify(["Erreicht", "Reaktionen", "Besuche", "Neue Konten"]), await page.textContent(".wz-kpis"));
check("Cockpit: Vergleich neutral ohne Vordaten", (await page.textContent(".wz-kpi:first-child .trend")).includes("kein Vergleich"), await page.textContent(".wz-kpi:first-child .trend"));
check("Cockpit: Weg vom Post zum Konto als Trichter in 4 Stufen", (await page.$$eval(".trichter2 .tr-stufe", (x) => x.length)) === 4, "");
check("Cockpit: Soraya lernt in 3 Sätzen", JSON.stringify(await page.$$eval("dl.lernt dt", (x) => x.map((e) => e.textContent))) === JSON.stringify(["Mehr davon", "Weniger davon", "Nächster Test"]), "");
check("Cockpit: ehrlich bei wenig Daten", (await page.textContent("dl.lernt")).includes("Noch zu wenig Daten"), await page.textContent("dl.lernt"));
check("Soraya erkennt: ehrliche Karte 'zu wenig Daten'", (await page.$$eval("ol.erkennt li.erk.duenn", (x) => x.length)) === 1 && (await page.textContent("ol.erkennt")).includes("zu wenig Daten"), await page.textContent(".wz-erkennt"));
check("Cockpit: Rohdaten nur unter Plattformen", await page.$eval("#wDetails", (d) => d.hidden), "");
await page.click('[data-wr="posts"]'); await wait(300);
check("Posts: freundlicher Leerzustand", (await page.textContent("#wzPosts")).includes("nichts gepostet"), await page.textContent("#wzPosts"));
await page.click('[data-wr="lernen"]'); await wait(300);
check("Lernen: Leerzustand ohne Posts", (await page.textContent("#wCockpit")).includes("Noch nichts zum Lernen"), await page.textContent("#wCockpit"));
await page.click('[data-wr="plattformen"]'); await wait(400);
check("Plattformen: Standard 7 Tage, 7 Tagesfelder", (await page.getAttribute('#wZeitraum [data-tage="7"]', "aria-pressed")) === "true" && (await page.$$eval("#wzTage .hit", (x) => x.length)) === 7, "");
check("Plattformen: Leerzustände (keine Reichweite, Bio-Link-Besuche, keine Plattform verbunden)", (await page.textContent(".wz-pv")).includes("Noch keine Reichweite gemessen") && (await page.textContent(".wz-pv")).includes("51")
  && (await page.textContent("#wzFollower")).includes("Noch keine Plattform verbunden") && (await page.$$("#wzTage path.bes")).length >= 1, await page.textContent(".wz-pv"));
check("Plattformen: Rohdaten zugeklappt", !(await page.$eval("#wDetails", (d) => d.hidden)) && !(await page.$eval("#wDetails", (d) => d.open)), "");
await page.click('#wZeitraum [data-tage="30"]'); await wait(1200);
check("Cockpit: Zeitraum 30 Tage", (await page.$$eval("#wzTage .hit", (x) => x.length)) === 30 && /\d+\. [A-ZÄÖÜ][a-zä]+ – \d+\. [A-ZÄÖÜ][a-zä]+/.test(await page.textContent("#wZeitraumText")), await page.textContent("#wZeitraumText"));
await page.click("#wDetails > summary"); await wait(1500);
check("Wirkung: Zeitraum mit deutschem Datum", /\d+\. [A-ZÄÖÜ][a-zä]+ – \d+\. [A-ZÄÖÜ][a-zä]+/.test(await page.textContent("#wirkungInhalt .panel .hint")), await page.textContent("#wirkungInhalt .panel .hint"));
check("Wirkung: 5 Kennzahl-Kacheln (App)", (await page.$$eval("#wirkungInhalt .kpi", (x) => x.length)) === 5, "");
check("Wirkung: 30 Tagesbalken-Trefferflächen", (await page.$$eval("#verlauf .hit", (x) => x.length)) === 30, "");
await page.hover("#verlauf .hit >> nth=29"); await wait(200);
check("Wirkung: Tooltip beim Zeigen", !(await page.$eval("#tip", (t) => t.classList.contains("hide"))), "");
check("Wirkung: Trichter mit 5 Stufen", (await page.$$eval("#wirkungInhalt .trichter .stufe", (x) => x.length)) >= 5, "");
check("Wirkung: Tabelle vorhanden", (await page.$$eval("#wirkungInhalt .panel > details table.tabelle tbody tr", (x) => x.length)) === 30, "");
const herkunft = await page.$$eval("table.herkunft tbody tr", (r) => r.map((z) => [...z.cells].map((c) => c.innerText.replace(/\s+/g, " ").trim()).join("|")));
// Post 1 wurde oben im Plan-Test geloescht -> wird als "(gelöscht)" gefuehrt
check("Wirkung: Herkunft – Post vorne (mehr Konten), Bio-Link danach", herkunft.length === 2 && /^Post 1 \(gelöscht\)\|34\|0\|9\|3\|2$/.test(herkunft[0]) && herkunft[1] === "Bio-Link Instagram|51|12|0|0|1", JSON.stringify(herkunft));
check("Wirkung: Bio-Links zum Kopieren", (await page.$$eval(".linkzeile code", (c) => c.map((x) => x.textContent))).join() === "https://www.sorayaluxuryastroguide.com/?q=bio-ig,https://www.sorayaluxuryastroguide.com/?q=bio-tt,https://www.sorayaluxuryastroguide.com/?q=bio-fb,https://www.sorayaluxuryastroguide.com/?q=bio-li", "");
await page.selectOption("#wKennzahl", "link_besuche"); await wait(300);
const linkBalken = await page.$$eval("#verlauf path", (p) => p.length);
check("Wirkung: Kennzahl 'Besuche über deine Links' (3 Tage mit Besuchen)", linkBalken === 3, linkBalken);
check("Cockpit: Besuche pro Tag aus den Links", (await page.$$eval("#wzTage path.bes", (p) => p.length)) === 3, await page.$$eval("#wzTage path.bes", (p) => p.length));
await page.selectOption("#wKennzahl", "aktive_nutzer"); await wait(200);
if (OUT) await page.screenshot({ path: OUT + "/ui-wirkung.png", fullPage: true });
await page.click('#wZeitraum [data-tage="7"]'); await wait(1500);
check("Wirkung: Zeitraum 7 Tage (auch in den Details)", (await page.$$eval("#verlauf .hit", (x) => x.length)) === 7, "");
await page.selectOption("#wKennzahl", "neue_konten"); await wait(400);
check("Wirkung: Kennzahl wechseln", (await page.textContent("#wirkungInhalt .legende")).includes("Neue Konten"), "");
await page.goto(BASE + "/#wirkung", { waitUntil: "load" }); await wait(1500);
check("Wirkung: Unterreiter und Zeitraum bleiben gemerkt", (await page.getAttribute('[data-wr="plattformen"]', "aria-selected")) === "true" && (await page.getAttribute('#wZeitraum [data-tage="7"]', "aria-pressed")) === "true", "");
await page.click('[data-wr="ueberblick"]'); await wait(300);

// Zielgruppen-Tab laedt
await page.click('.tab[data-tab="who"]'); await wait(700);
check("Zielgruppen: Bereiche geladen", (await page.$$eval("#bereich option", (x) => x.length)) >= 5, "");
check("Zielgruppen: zwei Profile mit Land", (await page.$$eval("#profile .card.who .plat", (x) => x.map((e) => e.textContent).join("|"))).includes("Ungarn"), "");
{ const info = await page.textContent("#tpInfo");
  check("Zielgruppen: ohne Markierung je Sprache automatisch (Land zuerst)", info.includes("automatisch") && info.includes("HU Szerelem") && info.includes("DE Liebe"), info); }
const zgLiebe = await page.$eval("#profile .card.who:last-child", (e) => e.dataset.zg);
await page.check(`input[data-imtp="${zgLiebe}"]`); await wait(700);
{ const info = await page.textContent("#tpInfo");
  check("Zielgruppen: markiertes Profil gilt für alle Sprachen", info.includes("DE Liebe") && info.includes("HU Liebe") && !info.includes("automatisch"), info);
  check("Zielgruppen: Häkchen bleibt nach dem Neuladen", await page.isChecked(`input[data-imtp="${zgLiebe}"]`), "");
  check("Zielgruppen: Sprachen am Profil", (await page.textContent(`.card.who[data-zg="${zgLiebe}"] .imtp`)).includes("DE · EN · HU · IT"), "");
  check("Zielgruppen: Meldung", (await page.textContent("#status")).includes("Tagesplan"), ""); }
const zgHu = await page.$eval("#profile .card.who:first-child", (e) => e.dataset.zg);
await page.check(`input[data-imtp="${zgHu}"]`); await wait(700);
{ const info = await page.textContent("#tpInfo");
  check("Zielgruppen: ungarisches Profil für HU, sonst Liebe", info.includes("HU Szerelem") && info.includes("DE Liebe"), info); }
if (OUT) await page.screenshot({ path: OUT + "/zielgruppen.png", fullPage: false });
await page.uncheck(`input[data-imtp="${zgHu}"]`); await page.uncheck(`input[data-imtp="${zgLiebe}"]`); await wait(900);
check("Zielgruppen: Häkchen wieder weg", !(await page.isChecked(`input[data-imtp="${zgLiebe}"]`)) && (await page.textContent("#tpInfo")).includes("automatisch"), "");

// Posten
await page.click('.tab[data-tab="posten"]'); await wait(900);
check("Posten: standardmäßig aus", !(await page.isChecked("#postAuto")) && (await page.textContent("#postInfo")).startsWith("Aus:"), await page.textContent("#postInfo"));
check("Posten: ohne Meta-App Hinweis auf Railway-Variablen", (await page.textContent("#verbindungen")).includes("META_APP_ID") && (await page.$$("#verbindungen a.knopf:not(.hide)")).length === 0, "");
check("Posten: Rückruf-Adresse angezeigt", (await page.textContent("#verbindungen")).includes("/meta/rueckruf/facebook"), "");
{ const t0 = await page.textContent("#verbindungen");
check("Posten: fünf Verbindungen (Facebook, Instagram, TikTok, LinkedIn, Pinterest)", (await page.$$eval("#verbindungen .verbindung", (x) => x.length)) === 5, "");
check("Posten: Pinterest-Einrichtung mit Rückruf und Sandbox", ["developers.pinterest.com", "/pinterest/rueckruf", "PINTEREST_APP_ID", "PINTEREST_SANDBOX", "Standard access"].every((w) => t0.includes(w)), "");
}
{ const t = await page.textContent("#verbindungen");
  check("Posten: TikTok-Einrichtung mit Produkten, Rechten und Rückruf", ["Login Kit", "Content Posting API", "user.info.basic", "video.upload", "video.publish", "Sandbox", "/tiktok/rueckruf", "TIKTOK_CLIENT_KEY"].every((w) => t.includes(w)), "");
  check("Posten: LinkedIn-Einrichtung mit Seite, Produkten und Rückruf", ["Unternehmensseite", "Share on LinkedIn", "OpenID Connect", "/linkedin/rueckruf", "LINKEDIN_CLIENT_ID"].every((w) => t.includes(w)), "");
  check("Posten: Einrichtung zugeklappt", !(await page.$$eval("#verbindungen details.einricht", (d) => d.some((x) => x.open))), ""); }
check("Posten: LinkedIn-Häkchen standardmäßig aus", !(await page.isChecked("#plLinkedin")), "");
await page.$$eval("#verbindungen details.einricht", (d) => d.forEach((x) => { x.open = true; }));
if (OUT) await (await page.$("#verbindungen")).screenshot({ path: OUT + "/posten-einrichtung-tiktok-linkedin.png" });
await page.$$eval("#verbindungen details.einricht", (d) => d.forEach((x) => { x.open = false; }));
check("Posten: Einrichtung zeigt Schritt 1 mit Kopier-Adressen", await page.isVisible("#einrichtungPanel") && (await page.$$eval("#einrichtungSchritte li", (l) => l.length)) === 5
  && (await page.$eval("#einrichtungSchritte li.jetzt", (l) => l.textContent)).includes("datenschutz.html") && (await page.$$("#einrichtungSchritte [data-kopie]")).length === 3, "");
check("Posten: Testpost-Knöpfe ohne Verbindung gesperrt", (await page.$$("#testposts button[data-jetzt]")).length > 0
  && (await page.$$eval("#testposts button[data-jetzt]", (b) => b.every((x) => x.disabled))), await page.textContent("#testposts"));
check("Posten: Standard EN, Zeiten (mit 2. Reel)", (await page.inputValue("#postSprache")) === "en" && (await page.inputValue("#zReel")) === "19:00" && (await page.inputValue("#zReel2")) === "19:30", "");
await page.check("#postAuto"); await wait(900);
check("Posten: einschalten mit Rückfrage", await page.isChecked("#postAuto") && (await page.textContent("#postInfo")).startsWith("An: EN"), await page.textContent("#postInfo"));
check("Posten: Warnung ohne Verbindung und ohne Tagesplan-Automatik", (await page.textContent("#postWarnung")).includes("keine Plattform") && (await page.textContent("#postWarnung")).includes("Tagesplan"), await page.textContent("#postWarnung"));
await page.$eval("#einstellungenPanel", (d) => { d.open = true; });   // Einstellungen sind zugeklappt
await page.fill("#zReel", "20:15"); await page.fill("#zReel2", "21:05"); await page.click("#postSpeichern"); await wait(800);
check("Posten: Zeiten speichern", (await page.textContent("#postInfo")).includes("Reel 20:15") && (await page.textContent("#postInfo")).includes("2. Reel 21:05"), await page.textContent("#postInfo"));
check("Posten: keine Termine ohne Verbindung", (await page.textContent("#termine")).includes("Keine Termine"), "");
if (OUT) await page.screenshot({ path: OUT + "/posten.png", fullPage: true });
await page.uncheck("#postAuto"); await wait(700);
check("Posten: wieder aus", !(await page.isChecked("#postAuto")) && (await page.textContent("#status")).includes("aus"), await page.textContent("#status"));
check("Keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
await ctx.close();

// Handy-Breite
{ const { ctx, page, fehler } = await seite(390);
  await wait(800);
  check("Handy: Kopf höchstens 120 px", (await page.$eval(".kopfzeile", (e) => e.offsetHeight)) <= 120, await page.$eval(".kopfzeile", (e) => e.offsetHeight));
  for (const t of ["heute", "plan", "studio", "who", "posten", "wirkung"]) {
    await page.click(`.tab[data-tab="${t}"]`); await wait(900);
    const w = await page.evaluate(() => document.documentElement.scrollWidth);
    check(`Handy: ${t} ohne Querscrollen`, w <= 390, w);
    if (OUT && (t === "heute" || t === "wirkung")) await page.screenshot({ path: OUT + `/handy-${t}.png`, fullPage: false });
  }
  check("Handy: keine JS-Fehler", fehler.length === 0, fehler.join(" | "));
  await ctx.close(); }

await browser.close();
console.log(results.join("\n") + "\n=> " + (ok ? "ALLE BESTANDEN" : "FEHLER"));
