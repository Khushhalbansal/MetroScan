/*
  The whole system, driven the way an officer would drive it:

    sign in -> photograph a package -> read the findings -> disagree with one ->
    see both verdicts kept -> prepare the report

  This is the check that the five layers are actually joined up. Unit tests on either
  side of a seam pass happily while the seam itself is broken.
*/
import { chromium } from "playwright";

const BASE = "http://localhost:5173";
const LABEL = process.argv[2];
const PASSWORD = process.env.METROSCAN_PASSWORD ?? "";

const checks = [];
function check(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

// --- sign in ------------------------------------------------------------------
await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });
check("signs in and lands on the enforcement overview", true);

// --- a wrong password must not get in ------------------------------------------
{
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await p.goto(BASE, { waitUntil: "networkidle" });
  await p.fill("#email", "controller@metrology.gov.in");
  await p.fill("#password", "definitely-not-the-password");
  await p.click('button[type="submit"]');
  await p.waitForSelector('[role="alert"]', { timeout: 10000 });
  const message = await p.locator('[role="alert"]').innerText();
  check(
    "refuses a wrong password without saying which half was wrong",
    /do not match an active account/.test(message),
    message,
  );
  await ctx.close();
}

// --- run a compliance check ----------------------------------------------------
await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await page.fill("#product", "E2E Roasted Chana Masala");
await page.setInputFiles('input[type="file"]', LABEL);
await page.click('button[type="submit"]');
await page.waitForSelector(".ledger__row", { timeout: 120000 });
check("runs a compliance check and shows the ledger", true);

const scanUrl = page.url();

// --- the Measure is on the page, with real millimetres --------------------------
const measureText = await page.locator('[data-rule="FONT_HEIGHT_NET_QUANTITY"]').innerText();
check(
  "renders the Rule 8 finding as a measurement",
  /1\.00 mm/.test(measureText) && /2\.0 mm/.test(measureText),
  measureText.replace(/\s+/g, " ").slice(0, 120),
);

// --- the verdict before any human touches it ------------------------------------
const verdictBefore = await page.locator(".verdict").first().innerText();
check("shows the automated verdict", /NON-COMPLIANT/i.test(verdictBefore), verdictBefore);

// --- disagree with one finding ---------------------------------------------------
await page.locator('[data-rule="MRP_SINGLE_VALUE"] .ledger__overrule').click();
await page.waitForSelector(".dialog");
await page.click('.dialog__choice:has-text("PASS")');
await page.fill(
  ".dialog__reason",
  "Second price is a promotional sticker over the original MRP, verified on the pack.",
);
await page.click('.dialog__actions button[type="submit"]');
await page.waitForSelector(".ledger__override", { timeout: 20000 });

const overrideText = await page.locator('[data-rule="MRP_SINGLE_VALUE"]').innerText();
check(
  "keeps the software's finding beside the officer's",
  /Recorded as\s+FAIL/.test(overrideText.replace(/\s+/g, " ")) &&
    /promotional sticker/.test(overrideText),
  overrideText.replace(/\s+/g, " ").slice(0, 140),
);

const afterNote = await page.locator(".exam__after").innerText();
check(
  "says what the software found once an officer has overruled it",
  /the software found/i.test(afterNote),
  afterNote.replace(/\s+/g, " "),
);

// --- the record survives a reload -------------------------------------------------
await page.reload({ waitUntil: "networkidle" });
await page.waitForSelector(".ledger__override", { timeout: 20000 });
check("the decision is still there after a reload", true);

// --- prepare the report -----------------------------------------------------------
await page.click('button:has-text("Prepare report")');
await page.waitForSelector('a:has-text("Save PDF")', { timeout: 60000 });
const href = await page.locator('a:has-text("Save PDF")').getAttribute("href");
check("prepares a downloadable report", Boolean(href?.startsWith("blob:")), href ?? "");

// --- the repository lists it -------------------------------------------------------
await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
const firstRow = await page.locator(".repo__link").first().innerText();
check(
  "the scan appears in the repository with its coverage",
  /E2E Roasted Chana Masala/.test(firstRow) && /decided/.test(firstRow),
  firstRow.replace(/\s+/g, " "),
);

check("no uncaught page errors", errors.length === 0, errors.join("; "));

await browser.close();

const failed = checks.filter((c) => !c.ok);
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
console.log(`scan: ${scanUrl}`);
process.exit(failed.length ? 1 : 0);
