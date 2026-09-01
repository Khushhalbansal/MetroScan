import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const [OUT, GOOD] = process.argv.slice(2);
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
await page.fill("#product", "Retention Prompt Pack");
await page.setInputFiles('input[type="file"]', GOOD);
await page.click('button[type="submit"]');
await page.waitForSelector(".ledger__row", { timeout: 180000 });

const panel = page.locator(".retention");
await panel.scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await panel.screenshot({ path: `${OUT}/60-retention-undecided.png` });

// "No — case closed" -> confirm state with the consequence spelled out
await page.locator(".retention button", { hasText: "No — case closed" }).click();
await page.waitForTimeout(250);
await panel.screenshot({ path: `${OUT}/61-retention-confirm.png` });

// confirm it
await page.locator(".retention button", { hasText: "No case is open" }).click();
await page.waitForTimeout(500);
await panel.screenshot({ path: `${OUT}/62-retention-closed.png` });

// flip back to "Yes — keep it"
await page.locator(".retention button", { hasText: "Yes — keep it" }).click();
await page.waitForTimeout(500);
await panel.screenshot({ path: `${OUT}/63-retention-open.png` });

// mobile
await page.setViewportSize({ width: 390, height: 900 });
await panel.scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await panel.screenshot({ path: `${OUT}/64-retention-mobile.png` });

await browser.close();
console.log(problems.length ? `PROBLEMS: ${problems.join("; ")}` : "no console errors");
