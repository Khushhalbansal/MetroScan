import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = process.argv[2];
const BASE = "http://localhost:5173";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", process.env.METROSCAN_PASSWORD ?? "");
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });
await page.waitForSelector(".dash__title, .notice--problem", { timeout: 20000 });
console.log("body:", (await page.locator(".bench").innerText()).slice(0, 400));
await page.waitForTimeout(900);

await page.screenshot({ path: `${OUT}/20-dashboard.png` });
await page.screenshot({ path: `${OUT}/21-dashboard-full.png`, fullPage: true });

await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/22-dashboard-mobile.png`, fullPage: true });

await browser.close();
console.log(errors.length ? `ERRORS: ${errors.join("; ")}` : "no console errors");
