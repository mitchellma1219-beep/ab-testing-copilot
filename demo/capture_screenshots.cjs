// Optional helper: capture the dashboard screenshots in demo/screenshots/.
// Not part of the test suite. Needs Node.js, Playwright (`npm install playwright`) and a
// Chromium or Chrome binary; the dashboard must already be running:
//
//   streamlit run app/streamlit_app.py --server.headless true --server.port 8501
//   node demo/capture_screenshots.cjs http://127.0.0.1:8501
//
// Set CHROME_PATH to use an installed Chrome instead of Playwright's own browser.
const path = require('path');
const { chromium } = require('playwright');

const url = process.argv[2] || 'http://127.0.0.1:8501';
const out = path.join(__dirname, 'screenshots');

async function scenario(page, title) {
  await page.getByRole('combobox', { name: /Scenario/ }).click();
  await page.getByRole('option', { name: title, exact: true }).click();
  await page.waitForTimeout(2500);
}

async function tab(page, name) {
  await page.getByRole('tab', { name }).click();
  await page.waitForTimeout(1500);
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || undefined,
    args: ['--no-sandbox', '--no-proxy-server'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const shot = (name) => page.screenshot({ path: path.join(out, name + '.png') });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.getByRole('tab', { name: 'Experiment setup' }).waitFor({ timeout: 60000 });
  await page.waitForTimeout(2500);
  await shot('01_experiment_setup');
  await tab(page, 'Power calculator');
  await shot('02_power_calculator');
  await tab(page, 'Simulation');
  await page.getByText('Repeated looks at growing data').click();
  await page.waitForTimeout(800);
  await page.getByRole('button', { name: 'Run simulation' }).click();
  await page.waitForTimeout(9000);
  await shot('03_simulation');
  await scenario(page, 'Segment heterogeneity');
  await tab(page, 'Statistical results');
  await shot('04_statistical_results');
  await scenario(page, 'Novelty decay');
  await tab(page, 'Diagnostic warnings');
  await shot('05_diagnostic_warnings');
  await scenario(page, 'Sample ratio mismatch');
  await tab(page, 'Decision report');
  await shot('06_decision_report');
  await scenario(page, 'Clean win');
  await tab(page, 'Export');
  await shot('07_export');
  await browser.close();
})().catch((error) => { console.error(error); process.exit(1); });
