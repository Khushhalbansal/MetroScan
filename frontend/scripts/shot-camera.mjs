import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const [OUT, Y4M] = process.argv.slice(2);
const BASE = "http://localhost:5173";
mkdirSync(OUT, { recursive: true });

async function open(args, permissions) {
  const browser = await chromium.launch({ args });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
    deviceScaleFactor: 2,
    permissions,
  });
  const page = await context.newPage();
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.fill("#email", "controller@metrology.gov.in");
  await page.fill("#password", process.env.METROSCAN_PASSWORD ?? "");
  await page.click('button[type="submit"]');
  await page.waitForURL("**/dashboard", { timeout: 20000 });
  await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
  return { browser, page };
}

// --- working camera -----------------------------------------------------------
{
  const { browser, page } = await open(
    [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-video-capture=${Y4M}`,
    ],
    ["camera"],
  );
  await page.screenshot({ path: `${OUT}/30-newscan.png`, fullPage: true });

  await page.click("text=Photograph the pack");
  await page.waitForFunction(() => {
    const v = document.querySelector(".capture__video");
    return v instanceof HTMLVideoElement && v.videoWidth > 0;
  }, { timeout: 20000 });
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/31-viewfinder.png` });

  await page.click('button:has-text("Capture")');
  await page.waitForSelector(".capture__still");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/32-review.png` });

  await page.click('button:has-text("Use this photograph")');
  await page.waitForSelector(".staged__row");
  await page.screenshot({ path: `${OUT}/33-staged.png`, fullPage: true });
  await browser.close();
}

// --- camera refused -----------------------------------------------------------
{
  const { browser, page } = await open([], []);
  await page.evaluate(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: () => Promise.reject(new DOMException("no", "NotAllowedError")),
      },
      configurable: true,
    });
  });
  await page.click("text=Photograph the pack");
  await page.waitForSelector('[role="status"]');
  await page.screenshot({ path: `${OUT}/34-camera-refused.png` });
  await browser.close();
}

console.log("done");
