import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const BASE_URL = process.env.UI_SMOKE_URL || "http://localhost:5173/";
const OUT_DIR = process.env.UI_SMOKE_OUT_DIR || path.resolve("ui-audit");

function asText(v) {
  return (v ?? "").toString().trim();
}

function looksLikeTile(url) {
  return /(tiles|tilejson|\.pbf|mvt)/i.test(url);
}

async function run() {
  const require = createRequire(import.meta.url);
  const { chromium } = require("playwright");

  fs.rmSync(OUT_DIR, { recursive: true, force: true });
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const results = {
    url: BASE_URL,
    checks: {},
    tabs: {},
    console: [],
    pageErrors: [],
    requestFailed: [],
    responses: [],
    mapbox: { responses: [], tileResponses: [] },
    backend: { responses: [] },
  };

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  page.on("console", (m) => {
    const t = m.type();
    if (t === "error" || t === "warning") {
      results.console.push({ type: t, text: m.text() });
    }
  });

  page.on("pageerror", (e) => results.pageErrors.push(String(e)));

  page.on("requestfailed", (r) => {
    results.requestFailed.push({
      url: r.url(),
      failure: r.failure()?.errorText || "",
    });
  });

  page.on("response", (resp) => {
    const u = resp.url();
    const s = resp.status();
    results.responses.push({ status: s, url: u });
    if (u.includes("api.mapbox.com")) {
      results.mapbox.responses.push({ status: s, url: u });
      if (looksLikeTile(u)) results.mapbox.tileResponses.push({ status: s, url: u });
    }
    if (u.includes("localhost:8000") || u.includes("127.0.0.1:8000")) {
      results.backend.responses.push({ status: s, url: u });
    }
  });

  await page.goto(BASE_URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForSelector("header.app-header h1", { timeout: 60_000 });

  results.checks.h1 = asText(await page.textContent("header.app-header h1"));
  results.checks.headerTabs = await page.$$eval("header.app-header nav.app-nav button.tab", (els) =>
    els.map((e) => (e.textContent || "").trim())
  );
  results.checks.sidebarVisible = await page.isVisible("aside.sidebar");
  results.checks.dateRangeVisible = await page.isVisible(".sidebar-date-range");
  results.checks.mapWrapperVisible = await page.isVisible(".map-wrapper");

  await page.waitForTimeout(5_000);
  results.checks.mapCanvasPresent = (await page.locator(".mapboxgl-canvas").count()) > 0;

  await page.screenshot({ path: path.join(OUT_DIR, "01-reliability.png"), fullPage: true });

  async function snap(tabName, filename, expectedDateRange) {
    await page.getByRole("button", { name: tabName }).click();
    await page.waitForTimeout(1_200);

    const h2 = asText(await page.textContent("aside.sidebar h2"));
    const dateVisible = await page.isVisible(".sidebar-date-range");

    results.tabs[tabName] = {
      sidebarH2: h2,
      dateRangeVisible: dateVisible,
      expectedDateRange,
      layout: {
        sidebar: await page.isVisible("aside.sidebar"),
        map: await page.isVisible(".map-container"),
      },
    };

    await page.screenshot({ path: path.join(OUT_DIR, filename), fullPage: true });
  }

  await snap("Crowding Prediction", "02-crowding.png", true);
  await snap("Stop Safety", "03-safety.png", false);
  await snap("Transit Coverage", "04-coverage.png", false);
  await snap("Demand Forecast", "05-demand.png", true);

  await browser.close();

  fs.writeFileSync(path.join(OUT_DIR, "report.json"), JSON.stringify(results, null, 2));

  const mapbox4xx = results.mapbox.responses.filter((r) => r.status >= 400);
  const backend4xx = results.backend.responses.filter((r) => r.status >= 400);

  // eslint-disable-next-line no-console
  console.log(
    JSON.stringify(
      {
        headerTabs: results.checks.headerTabs,
        sidebar: results.checks.sidebarVisible,
        dateRange: results.checks.dateRangeVisible,
        mapWrapper: results.checks.mapWrapperVisible,
        mapCanvas: results.checks.mapCanvasPresent,
        mapboxResponses: results.mapbox.responses.length,
        mapboxTileLikeResponses: results.mapbox.tileResponses.length,
        mapbox4xx: mapbox4xx.slice(0, 10),
        backendResponses: results.backend.responses.length,
        backend4xx: backend4xx.slice(0, 10),
        consoleWarnError: results.console.slice(0, 20),
        pageErrors: results.pageErrors.slice(0, 20),
        requestFailed: results.requestFailed.slice(0, 20),
        tabs: results.tabs,
        outDir: OUT_DIR,
      },
      null,
      2
    )
  );
}

run().catch((e) => {
  // eslint-disable-next-line no-console
  console.error(e);
  process.exitCode = 1;
});

