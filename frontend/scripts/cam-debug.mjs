import { chromium } from "playwright";

const Y4M = process.argv[2];
const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    ...(Y4M ? [`--use-file-for-fake-video-capture=${Y4M}`] : []),
  ],
});
const context = await browser.newContext({ permissions: ["camera"] });
const page = await context.newPage();
page.on("console", (m) => console.log("console:", m.type(), m.text()));
page.on("pageerror", (e) => console.log("pageerror:", e.message));

await page.goto("http://localhost:5173", { waitUntil: "networkidle" });

const result = await page.evaluate(async () => {
  try {
    const s = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 2560 }, height: { ideal: 1440 } },
      audio: false,
    });
    const track = s.getVideoTracks()[0];
    const settings = track.getSettings();
    const v = document.createElement("video");
    v.srcObject = s;
    v.muted = true;
    v.playsInline = true;
    document.body.appendChild(v);
    await v.play().catch((e) => ({ playError: String(e) }));
    await new Promise((r) => setTimeout(r, 2500));
    return { ok: true, settings, videoWidth: v.videoWidth, videoHeight: v.videoHeight, readyState: v.readyState };
  } catch (e) {
    return { ok: false, name: e.name, message: e.message };
  }
});
console.log("RESULT:", JSON.stringify(result, null, 2));
await browser.close();
