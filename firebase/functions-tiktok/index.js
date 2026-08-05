// TikTok tag scraper — Playwright captures /api/challenge/item_list responses
// from https://www.tiktok.com/tag/{hashtag}. Returns videos as JSON; does NOT
// write to Firestore (the Python orchestrator handles persistence + fan-out).
//
// Call (public endpoint, MVP):
//   POST /scrapeTikTokTag  { hashtag: "stelz", limit: 200, minViews: 0 }
//   →   { hashtag, detail, videos, diag }

const { onRequest } = require("firebase-functions/v2/https");
const chromium = require("@sparticuz/chromium");
const { chromium: pwChromium } = require("playwright-core");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Apify Residential Proxy — TikTok aggressively blocks datacenter IPs.
// Routing Playwright traffic through residential exits (Apify rotates per
// session) is the only durable fix. Country-NL aligns egress with the brand's
// audience (Dutch hashtags look natural from Dutch IPs).
// Token comes from functions-tiktok/.env (auto-loaded by Firebase Functions).
const PROXY_HOST = "proxy.apify.com";
const PROXY_PORT = 8000;
const PROXY_GROUPS = "RESIDENTIAL";
const PROXY_COUNTRY = "NL";

// Real Chrome 130 on macOS — keep this in sync with sec-ch-ua below.
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";

const EXTRA_HEADERS = {
  "Accept-Language": "en-US,en;q=0.9,nl;q=0.6",
  "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"macOS"',
  "Upgrade-Insecure-Requests": "1",
};

// Init script injected into every page to defeat headless fingerprints that
// TikTok looks at when deciding whether to serve content or a captcha.
const STEALTH_INIT = `
  // 1. navigator.webdriver should be undefined, not true.
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  // 2. Languages should look like a real browser, not [].
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'nl'] });
  // 3. Plugins/mime types — headless returns 0; real Chrome has at least a few.
  Object.defineProperty(navigator, 'plugins', {
    get: () => [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ],
  });
  // 4. WebGL vendor/renderer — headless returns "Google Inc." / "Google SwiftShader".
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (param) {
    if (param === 37445) return 'Intel Inc.';      // UNMASKED_VENDOR_WEBGL
    if (param === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
    return getParameter.call(this, param);
  };
  // 5. Permissions API — headless returns "denied" for notifications.
  const orig = window.navigator.permissions && window.navigator.permissions.query;
  if (orig) {
    window.navigator.permissions.query = (p) =>
      p && p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : orig.call(window.navigator.permissions, p);
  }
  // 6. chrome runtime stub — real Chrome has window.chrome with .runtime.
  if (!window.chrome) window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
`;

const mapVideo = (v) => ({
  id: v.id,
  desc: v.desc || "",
  author: v.author?.uniqueId || "",
  authorName: v.author?.nickname || "",
  avatar: v.author?.avatarThumb || "",
  cover: v.video?.cover || v.video?.dynamicCover || "",
  duration: v.video?.duration ?? null,
  playCount: v.stats?.playCount ?? null,
  diggCount: v.stats?.diggCount ?? null,
  commentCount: v.stats?.commentCount ?? null,
  shareCount: v.stats?.shareCount ?? null,
  createTime: v.createTime ?? null,
  url: `https://www.tiktok.com/@${v.author?.uniqueId}/video/${v.id}`,
});

async function launchBrowser(proxyConfig) {
  const opts = {
    args: [
      ...chromium.args,
      "--disable-blink-features=AutomationControlled",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--single-process",
    ],
    executablePath: await chromium.executablePath(),
    headless: true,
    proxy: proxyConfig,
  };
  // EFAULT on spawn is occasionally transient (container hasn't finished
  // extracting /tmp/chromium yet). Retry up to 2 times with a small delay.
  let lastErr;
  for (let i = 0; i < 3; i++) {
    try {
      return await pwChromium.launch(opts);
    } catch (e) {
      lastErr = e;
      if (!String(e?.message || "").includes("EFAULT")) throw e;
      console.warn(`[launchBrowser] EFAULT attempt ${i + 1}, retrying…`);
      await sleep(800 * (i + 1));
    }
  }
  throw lastErr;
}

async function scrapeOnce(hashtag, limit, apifyToken) {
  const tag = String(hashtag).replace(/^#/, "").trim().toLowerCase();
  const isOk = (j) => j?.statusCode === 0 || j?.status_code === 0 || j?.status === 0;
  const diag = {
    landedUrl: null,
    captchaDetected: false,
    itemListResponses: 0,
    itemListNonOk: 0,
    itemListZero: 0,
    detailResponseSeen: false,
    landedTitle: null,
    blockedReason: null,
    elapsedMs: 0,
    proxy: apifyToken ? `apify:${PROXY_GROUPS}/${PROXY_COUNTRY}` : "none",
  };
  const captured = { detail: null, videos: [] };
  const t0 = Date.now();

  // Per-session sticky residential IP — Apify session syntax keeps the same
  // exit IP for a tag's whole scrape (smoother for TikTok's bot detection),
  // but the next scrape gets a fresh IP.
  const sessionId = `tt_${tag.replace(/[^a-z0-9]/g, "")}_${Math.floor(Math.random() * 1e9).toString(36)}`;
  const proxyConfig = apifyToken
    ? {
        server: `http://${PROXY_HOST}:${PROXY_PORT}`,
        username: `groups-${PROXY_GROUPS},country-${PROXY_COUNTRY},session-${sessionId}`,
        password: apifyToken,
      }
    : undefined;
  const browser = await launchBrowser(proxyConfig);
  try {
    const context = await browser.newContext({
      userAgent: UA,
      locale: "en-US",
      timezoneId: "Europe/Amsterdam",
      viewport: { width: 1366, height: 900 },
      deviceScaleFactor: 1,
      extraHTTPHeaders: EXTRA_HEADERS,
      ignoreHTTPSErrors: true,
    });
    await context.addInitScript(STEALTH_INIT);

    const page = await context.newPage();

    // Catch challenge detail response (one shot, fires near page load).
    page.on("response", async (r) => {
      const url = r.url();
      if (url.includes("api/challenge/detail") && r.status() === 200) {
        try {
          const j = await r.json();
          if (isOk(j)) {
            diag.detailResponseSeen = true;
            const info = j?.challengeInfo || {};
            captured.detail = {
              id: info.challenge?.id,
              title: info.challenge?.title,
              desc: info.challenge?.desc,
              videoCount: info.stats?.videoCount,
              viewCount: info.stats?.viewCount,
            };
          }
        } catch {}
      }
      if (url.includes("api/challenge/item_list") && r.status() === 200) {
        diag.itemListResponses += 1;
        try {
          const j = await r.json();
          if (!isOk(j)) {
            diag.itemListNonOk += 1;
            return;
          }
          const items = j?.itemList || [];
          if (items.length === 0) diag.itemListZero += 1;
          captured.videos.push(...items.map(mapVideo));
          console.log(
            `[scrapeTikTokTag] tag=${tag} batch=${items.length} total=${captured.videos.length} hasMore=${j?.hasMore}`
          );
        } catch {}
      }
    });

    const targetUrl = `https://www.tiktok.com/tag/${encodeURIComponent(tag)}`;
    await page
      .goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 60000 })
      .catch((e) => {
        diag.blockedReason = `goto_failed:${e?.message?.slice(0, 80)}`;
      });

    diag.landedUrl = page.url();
    diag.landedTitle = await page.title().catch(() => null);

    // Detect early-exit conditions: redirected to captcha or login, or page
    // shows verify-modal class, etc.
    if (diag.landedUrl.includes("captcha") || diag.landedUrl.includes("verify")) {
      diag.captchaDetected = true;
      diag.blockedReason = "redirected_to_captcha";
    }
    const hasCaptchaModal = await page
      .evaluate(() => !!document.querySelector('[id*="captcha"], [class*="captcha"], [class*="verify-bar"]'))
      .catch(() => false);
    if (hasCaptchaModal) {
      diag.captchaDetected = true;
      diag.blockedReason = diag.blockedReason || "captcha_modal_present";
    }

    // Quick warmup — domcontentloaded already fired; just sleep briefly.
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    await sleep(1500);

    // Wall-clock budget for the whole scroll loop. Anything longer than this
    // and the parent orchestrator times out anyway.
    const SCROLL_BUDGET_MS = 50_000;
    const scrollStart = Date.now();
    let stagnantRounds = 0;
    for (let attempt = 0; attempt < 20 && captured.videos.length < limit; attempt++) {
      if (Date.now() - scrollStart > SCROLL_BUDGET_MS) break;
      const before = captured.videos.length;
      await page
        .evaluate(() => window.scrollBy(0, window.innerHeight * 2))
        .catch(() => {});
      await page.waitForLoadState("networkidle", { timeout: 4000 }).catch(() => {});
      await sleep(500);
      if (captured.videos.length === before) {
        stagnantRounds += 1;
        if (stagnantRounds >= 3) break;
      } else {
        stagnantRounds = 0;
      }
    }

    // Dedupe by id.
    const byId = new Map();
    for (const v of captured.videos) if (v.id && !byId.has(v.id)) byId.set(v.id, v);
    captured.videos = Array.from(byId.values());

    if (captured.videos.length === 0 && !diag.blockedReason) {
      diag.blockedReason = diag.itemListResponses === 0
        ? "no_item_list_responses"
        : "item_list_empty";
    }
  } finally {
    await browser.close().catch(() => {});
  }

  diag.elapsedMs = Date.now() - t0;
  return { captured, diag };
}

exports.scrapeTikTokTag = onRequest(
  {
    timeoutSeconds: 540,
    memory: "4GiB",
    region: "us-central1",
    cors: false,
    invoker: "public",
    // Each Cloud Run container handles ONE Chromium launch at a time.
    // Without this, parallel Pub/Sub fan-out causes EFAULT on concurrent spawns.
    concurrency: 1,
    // Allow Cloud Functions to scale out instead of queuing on one instance.
    maxInstances: 20,
  },
  async (req, res) => {
    if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

    const { hashtag, limit = 200, minViews = 0, maxRetries = 1 } = req.body || {};
    if (!hashtag) return res.status(400).json({ error: "hashtag required" });

    const tag = String(hashtag).replace(/^#/, "").trim().toLowerCase();
    // NB: Apify's proxy password is NOT the API token — it's the separate
    // password shown at console.apify.com/proxy. Using the API token here
    // gets a 407 from proxy.apify.com and every page.goto times out.
    const apifyToken = process.env.APIFY_PROXY_PASSWORD || "";
    console.log(
      `[scrapeTikTokTag] START tag=${tag} limit=${limit} proxy=${apifyToken ? `apify/${PROXY_COUNTRY}` : "DIRECT"}`
    );

    let result;
    let attempts = 0;
    while (attempts <= maxRetries) {
      attempts += 1;
      try {
        result = await scrapeOnce(tag, limit, apifyToken);
        if (result.captured.videos.length > 0) break;
        if (result.diag.captchaDetected) break; // retry won't help
        if (attempts <= maxRetries) {
          console.log(
            `[scrapeTikTokTag] tag=${tag} attempt=${attempts} got 0 videos, reason=${result.diag.blockedReason}, retrying after delay`
          );
          await sleep(4000);
        }
      } catch (e) {
        console.error(`[scrapeTikTokTag] attempt=${attempts} threw: ${e?.message}`);
        result = { captured: { videos: [], detail: null }, diag: { blockedReason: `exception:${e?.message?.slice(0, 100)}`, elapsedMs: 0 } };
        if (attempts <= maxRetries) await sleep(4000);
      }
    }

    let videos = result.captured.videos;
    if (minViews > 0) videos = videos.filter((v) => (v.playCount ?? 0) >= minViews);

    console.log(
      `[scrapeTikTokTag] DONE tag=${tag} videos=${videos.length} attempts=${attempts} ` +
      `landed=${result.diag.landedUrl} blocked=${result.diag.blockedReason || "none"} ` +
      `itemList=${result.diag.itemListResponses} captcha=${result.diag.captchaDetected}`
    );

    return res.json({
      hashtag: tag,
      detail: result.captured.detail || null,
      videos,
      diag: {
        attempts,
        ...result.diag,
      },
    });
  }
);
