/* Screenshot one specific scan's examination view, including the Measure in place. */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const [OUT, SCAN_ID] = process.argv.slice(2);
const BASE = "http://localhost:5173";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 2,
});
const page = await context.newPage();

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", process.env.METROSCAN_PASSWORD ?? "");
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });

await page.goto(`${BASE}/scans/${SCAN_ID}`, { waitUntil: "networkidle" });
await page.waitForSelector(".measure", { timeout: 20000 });
await page.waitForTimeout(1200);

await page.screenshot({ path: `${OUT}/10-exam-findings.png` });
await page.screenshot({ path: `${OUT}/11-exam-full.png`, fullPage: true });

// The Measure, close up, with its row active
const row = page.locator('[data-rule="FONT_HEIGHT_NET_QUANTITY"]');
await row.scrollIntoViewIfNeeded();
await row.hover();
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/12-measure.png` });
await row.screenshot({ path: `${OUT}/13-measure-row.png` });

console.log("done");
await browser.close();
