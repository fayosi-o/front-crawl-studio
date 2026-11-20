// Run the scripted browser checks in tests/browser_*.js against a running Long Catch server.
//
// Usage: node tools/browser_checks.js [URL] [check ...]   (default http://127.0.0.1:8080/, every check)
// Needs Node with Playwright and a Chromium build (dev tools only; the app itself does not use Node).
// tools/playwright_env.js finds both wherever they are installed, so this runs as it is.
// Each check is an `async page => {...}` file, the format `playwright-cli run-code` also accepts.
const fs = require('fs');
const path = require('path');
const { launchChromium } = require('./playwright_env');

const args = process.argv.slice(2);
const url = args[0] && /^https?:/.test(args[0]) ? args.shift() : 'http://127.0.0.1:8080/';
const dir = path.join(__dirname, '..', 'tests');
const names = args.length ? args : fs.readdirSync(dir).filter(f => /^browser_.*\.js$/.test(f)).sort();

(async () => {
  const browser = await launchChromium();
  let failed = 0;
  try {
    for (const name of names) {
      const file = path.join(dir, name.endsWith('.js') ? name : `${name}.js`);
      const check = eval(fs.readFileSync(file, 'utf8'));  // a trusted file from this repository
      const context = await browser.newContext();
      context.__studioUrl = url;
      const page = await context.newPage();
      const started = Date.now();
      try {
        const result = await check(page);
        console.log(`PASS ${path.basename(file)} (${((Date.now() - started) / 1000).toFixed(1)} s)`);
        console.log(JSON.stringify(result, null, 2));
      } catch (error) {
        failed++;
        console.log(`FAIL ${path.basename(file)}: ${error.message}`);
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  process.exit(failed ? 1 : 0);
})();
