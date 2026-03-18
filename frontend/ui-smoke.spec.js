const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("@playwright/test");

const BASE_URL = process.env.UI_SMOKE_URL || "http://localhost:5173/";
const OUT_DIR = process.env.UI_SMOKE_OUT_DIR || path.resolve(process.cwd(), "..", "ui-audit");

function asText(v) {
  return (v ?? "").toString().trim();
}

function looksLikeTile(url) {
  return /(tiles|tilejson|\\.pbf|mvt)/i.test(url);
}

test("UI smoke: tabs/sidebar/date range/map/network", async ({ page }) => {
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

  page.on("console", (m) => {
    const t = m.type();
    if (t === "error" || t === "warning") results.console.push({ type: t, text: m.text() });
  });
  page.on("pageerror", (e) => results.pageErrors.push(String(e)));
  page.on("requestfailed", (r) =>
    results.requestFailed.push({ url: r.url(), failure: r.failure()?.errorText || "" })
  );
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

  await expect(page.locator("header.app-header")).toBeVisible();
  await expect(page.locator("header.app-header h1")).toHaveText(/Bay Area Transit Intelligence/);

  results.checks.headerTabs = await page
    .locator("header.app-header nav.app-nav button.tab")
    .allTextContents()
    .then((xs) => xs.map((x) => x.trim()).filter(Boolean));

  expect(results.checks.headerTabs).toEqual([
    "Transit Reliability",
    "Crowding Prediction",
    "Stop Safety",
    "Transit Coverage",
    "Demand Forecast",
    "Route Explorer",
    "Bunching",
    "Live Vehicles",
    "Route Compare",
  ]);

  await expect(page.locator("aside.sidebar")).toBeVisible();
  results.checks.sidebarVisible = await page.isVisible("aside.sidebar");

  // Reliability: date range should show.
  await expect(page.locator(".sidebar-date-range")).toBeVisible();
  results.checks.dateRangeVisible = await page.isVisible(".sidebar-date-range");

  // Map container should exist and a WebGL canvas should appear.
  await expect(page.locator(".map-container")).toBeVisible();
  await expect(page.locator(".map-wrapper")).toBeVisible();
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
    expect(dateVisible).toBe(expectedDateRange);
  }

  await snap("Crowding Prediction", "02-crowding.png", true);
  await snap("Stop Safety", "03-safety.png", true);
  await snap("Transit Coverage", "04-coverage.png", true);
  await snap("Demand Forecast", "05-demand.png", true);
  await snap("Route Explorer", "06-routes.png", true);
  await snap("Bunching", "07-bunching.png", true);
  await snap("Live Vehicles", "08-vehicles.png", true);
  await snap("Route Compare", "09-comparison.png", true);

  fs.writeFileSync(path.join(OUT_DIR, "report.json"), JSON.stringify(results, null, 2));

  // Attach a short summary to test output.
  const mapbox4xx = results.mapbox.responses.filter((r) => r.status >= 400);
  const backend4xx = results.backend.responses.filter((r) => r.status >= 400);
  // eslint-disable-next-line no-console
  console.log(
    JSON.stringify(
      {
        headerTabs: results.checks.headerTabs,
        mapCanvasPresent: results.checks.mapCanvasPresent,
        mapboxResponses: results.mapbox.responses.length,
        mapboxTileLikeResponses: results.mapbox.tileResponses.length,
        mapbox4xx: mapbox4xx.slice(0, 10),
        backendResponses: results.backend.responses.length,
        backend4xx: backend4xx.slice(0, 10),
        consoleWarnErrorCount: results.console.length,
        pageErrorsCount: results.pageErrors.length,
        requestFailedCount: results.requestFailed.length,
      },
      null,
      2
    )
  );
});

