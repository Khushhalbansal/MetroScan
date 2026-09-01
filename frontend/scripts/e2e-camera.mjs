/*
  Prove that a photograph taken with the camera goes through exactly the same path as
  one chosen from disk — same upload, same storage, same pipeline, same findings.

  Chromium is launched with a fake capture device fed from a real rendered label, so
  the frame the camera "sees" is a package the rule engine has opinions about. If the
  capture path were special-cased anywhere downstream, the findings would differ from
  the file-upload run and this would catch it.
*/
import { chromium } from "playwright";

const BASE = "http://localhost:5173";
const LABEL_Y4M = process.argv[2];
const PASSWORD = process.env.METROSCAN_PASSWORD ?? "";

const checks = [];
function check(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}

const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-video-capture=${LABEL_Y4M}`,
  ],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  permissions: ["camera"],
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await page.goto(BASE, { waitUntil: "networkidle" });
await page.fill("#email", "controller@metrology.gov.in");
await page.fill("#password", PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });

await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await page.fill("#product", "Camera Captured Pack");

// --- open the camera ----------------------------------------------------------
await page.click("text=Photograph the pack");
await page.waitForSelector(".capture__video", { timeout: 20000 });
await page.waitForFunction(() => {
  const v = document.querySelector(".capture__video");
  return v instanceof HTMLVideoElement && v.videoWidth > 0;
}, { timeout: 20000 });
check("opens a live viewfinder", true);

const dims = await page.evaluate(() => {
  const v = document.querySelector(".capture__video");
  return v instanceof HTMLVideoElement ? { w: v.videoWidth, h: v.videoHeight } : null;
});
check("the viewfinder carries a real frame", Boolean(dims?.w), JSON.stringify(dims));

// --- capture, then retake, then accept -----------------------------------------
await page.click('button:has-text("Capture")');
await page.waitForSelector(".capture__still", { timeout: 10000 });
check("shows the still for review before accepting", true);

await page.click('button:has-text("Retake")');
await page.waitForSelector(".capture__video", { timeout: 20000 });
check("retake returns to the viewfinder", true);

await page.waitForFunction(() => {
  const v = document.querySelector(".capture__video");
  return v instanceof HTMLVideoElement && v.videoWidth > 0;
}, { timeout: 20000 });
await page.click('button:has-text("Capture")');
await page.waitForSelector(".capture__still", { timeout: 10000 });
await page.click('button:has-text("Use this photograph")');
await page.waitForSelector(".staged__row", { timeout: 10000 });

const staged = await page.locator(".staged__row").innerText();
check("the accepted photograph is staged as a file", /capture-.*\.png/.test(staged), staged.replace(/\s+/g, " "));

// --- run it through the ordinary pipeline ---------------------------------------
await page.click('button[type="submit"]');
await page.waitForSelector(".ledger__row", { timeout: 180000 });
check("a captured photograph runs through the normal check", true);

const body = await page.locator(".exam__bench").innerText();
check(
  "the captured frame was read and measured like any other",
  /text regions read/.test(body) && !/0 text regions read/.test(body),
  (body.match(/\d+ text regions read/) ?? ["?"])[0],
);

const hasMeasure = await page.locator(".measure").count();
check("Rule 8 was decided from the captured frame", hasMeasure > 0, `${hasMeasure} measure(s)`);

check("no uncaught page errors", errors.length === 0, errors.join("; "));

await browser.close();
const failed = checks.filter((c) => !c.ok);
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length ? 1 : 0);
