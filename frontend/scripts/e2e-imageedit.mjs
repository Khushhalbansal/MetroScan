/*
  Editing a filed scan's photographs from the browser, end to end.

  The claim being tested is not "the button works" — it is that the findings on screen
  change to match the new image set. So the flow files a scan from a label with a scale
  card (measurable, Rule 8 decided), then retakes that photograph with a blank frame and
  checks that the millimetre claims are gone from the UI.
*/
import { chromium } from "playwright";

const BASE = "http://localhost:5173";
const [GOOD, BLANK, EXTRA] = process.argv.slice(2);
const PASSWORD = process.env.METROSCAN_PASSWORD ?? "";

const checks = [];
function check(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });

// --- file a measurable scan -----------------------------------------------------
await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await page.fill("#product", "Edit Flow Pack");
await page.setInputFiles('input[type="file"]', GOOD);
await page.click('button[type="submit"]');
await page.waitForSelector(".ledger__row", { timeout: 180000 });
const scanUrl = page.url();

const calibratedBefore = (await page.locator(".exam__bench").innerText()).includes("mm");
check("the filed scan is measurable", calibratedBefore);
check("the image strip is on the examination view", await page.locator(".strip").count() > 0);

const revisionBefore = await page.locator(".strip__note").innerText();
check("the first reading is not labelled a revision", !/reading 2/.test(revisionBefore));

// --- retake the measurable photograph with a blank frame -------------------------
//
// Ordered first, and on its own, so it is discriminating: the scan holds exactly one
// photograph, and replacing it with a frame that reads nothing must take the whole
// measurement with it. Adding the violating label first would have left a scale card
// in the set and proved nothing.
await page.locator(".strip__action", { hasText: "Retake" }).first().click();
await page.setInputFiles(".strip input[type=file] >> nth=1", BLANK);
await page.waitForSelector(".exam__reprocessing", { timeout: 15000 });
check("a re-processing state is shown while the check re-runs", true);
await page.waitForSelector(".exam__reprocessing", { state: "detached", timeout: 180000 });

const afterRetake = await page.locator(".exam").innerText();
check(
  "losing the scale card removes every millimetre claim",
  /No millimetre measurement was possible/.test(afterRetake),
);
check(
  "and invents no violations from a frame that read nothing",
  /0 failing/.test(afterRetake),
  (afterRetake.match(/\d+ failing/) ?? ["?"])[0],
);
check("the reading is now numbered", /reading 2/.test(afterRetake));

// --- add the violating label, which carries its own scale card ---------------------
await page.setInputFiles(".strip input[type=file] >> nth=0", EXTRA);
await page.waitForSelector(".exam__reprocessing", { state: "detached", timeout: 180000 });

const afterAdd = await page.locator(".exam").innerText();
// Counted as strip rows, not by scanning the page for "regions read" — the evidence
// plate's own caption uses that phrase too.
const stripItems = await page.locator(".strip__item").count();
check("the added photograph appears in the strip", stripItems === 2, `${stripItems} item(s)`);
check(
  "adding a measurable photograph restores the measurement",
  !/No millimetre measurement was possible/.test(afterAdd),
);
check(
  "and its violations are found on the re-run",
  /3 failing/.test(afterAdd),
  (afterAdd.match(/\d+ failing/) ?? ["?"])[0],
);

// --- removing the last photograph is refused, in place ----------------------------
await page.locator(".strip__action--remove").first().click();
await page.locator("button", { hasText: "Remove and re-check" }).click();
await page.waitForSelector(".exam__reprocessing", { state: "detached", timeout: 180000 });

const remaining = await page.locator(".strip__item").count();
const removeButtons = page.locator(".strip__action--remove");
const lastDisabled = await removeButtons.first().isDisabled();
check("one photograph remains", remaining === 1, `${remaining} item(s)`);
check("the last photograph cannot be removed", lastDisabled);

// --- history kept -----------------------------------------------------------------
const revisions = await page.evaluate(async (url) => {
  const id = url.split("/").pop();
  const token = localStorage.getItem("metroscan.token");
  const r = await fetch(`/api/v1/scans/${id}/revisions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return r.json();
}, scanUrl);
check(
  "every edit is kept in history with its reason",
  revisions.length === 3 &&
    revisions.map((r) => r.reason).join(",") === "image replaced,image added,image removed",
  revisions.map((r) => r.reason).join(", "),
);
check(
  "the first reading in history still records what it found",
  revisions[0].snapshot.calibration.calibrated === true,
);

check("no uncaught page errors", errors.length === 0, errors.join("; "));

await browser.close();
const failed = checks.filter((c) => !c.ok);
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
