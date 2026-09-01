import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = process.argv[2];
const BASE = "http://localhost:5173";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 2 });
const problems = [];
page.on("pageerror", (e) => problems.push(e.message));
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("response", (r) => {
  if (r.url().includes("/guidance/") && !r.ok()) problems.push(`plate ${r.status()} ${r.url()}`);
});

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", process.env.METROSCAN_PASSWORD ?? "");
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });

await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await page.click(".plate-set__toggle");
await page.waitForSelector(".plate__figure");
await page.waitForTimeout(700);

await page.locator(".plate-set").screenshot({ path: `${OUT}/40-plates.png` });
await page.screenshot({ path: `${OUT}/41-newscan-full.png`, fullPage: true });

await page.setViewportSize({ width: 390, height: 900 });
await page.waitForTimeout(400);
await page.locator(".plate-set").screenshot({ path: `${OUT}/42-plates-mobile.png` });

await browser.close();
console.log(problems.length ? `PROBLEMS: ${problems.join("; ")}` : "no console errors, all plates loaded");
