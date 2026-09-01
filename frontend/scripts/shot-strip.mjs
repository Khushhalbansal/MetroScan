import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const [OUT, GOOD, EXTRA] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });
const BASE = "http://localhost:5173";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
const problems = [];
page.on("pageerror", (e) => problems.push(e.message));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", process.env.METROSCAN_PASSWORD ?? "");
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });

await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await page.fill("#product", "Strip Shot Pack");
await page.setInputFiles('input[type="file"]', GOOD);
await page.click('button[type="submit"]');
await page.waitForSelector(".ledger__row", { timeout: 180000 });

// Add a second photograph first — Remove is correctly disabled while a scan holds
// only one, so the confirm state is unreachable until there are two.
await page.locator(".strip").scrollIntoViewIfNeeded();
await page.setInputFiles(".strip input[type=file] >> nth=0", EXTRA);
await page.waitForSelector(".exam__reprocessing", { timeout: 15000 });
await page.waitForTimeout(250);
await page.screenshot({ path: `${OUT}/52-reprocessing.png` });
await page.waitForSelector(".exam__reprocessing", { state: "detached", timeout: 180000 });

await page.locator(".strip").scrollIntoViewIfNeeded();
await page.waitForTimeout(400);
await page.locator(".exam__evidence").screenshot({ path: `${OUT}/50-strip.png` });

// confirm state
await page.locator(".strip__action--remove").first().click();
await page.waitForTimeout(300);
await page.locator(".strip").screenshot({ path: `${OUT}/51-strip-confirm.png` });
await page.locator("button", { hasText: "Keep it" }).click();

await page.setViewportSize({ width: 390, height: 900 });
await page.locator(".strip").scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await page.locator(".strip").screenshot({ path: `${OUT}/53-strip-mobile.png` });

await browser.close();
console.log(problems.length ? `PROBLEMS: ${problems.join("; ")}` : "no console errors");
