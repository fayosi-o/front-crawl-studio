// Find Playwright and a Chromium it can drive, wherever they are installed, so the browser checks
// run as they are: no NODE_PATH, no copies with a hard-coded browser path.
// Dev tools only; the app itself never uses Node.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

// WebGL needs SwiftShader when Chromium runs headless without a GPU.
const GL = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'];

function loadPlaywright() {
  const tried = [];
  const attempt = target => {
    try { return require(target); } catch (error) { tried.push(target); return null; }
  };
  const direct = attempt('playwright');
  if (direct) return direct;
  // Global installs: plain playwright, the playwright CLI (which bundles it), or @playwright/test.
  let roots = [];
  try { roots.push(execSync('npm root -g', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()); } catch { /* no npm */ }
  roots = roots.concat(['/usr/local/lib/node_modules', '/opt/homebrew/lib/node_modules']);
  for (const root of [...new Set(roots)]) {
    for (const sub of ['playwright', '@playwright/cli/node_modules/playwright', '@playwright/test/node_modules/playwright']) {
      const found = attempt(path.join(root, sub));
      if (found) return found;
    }
  }
  throw new Error(`Playwright not found (tried ${tried.join(', ')}). Install it as a dev tool: npm i -g playwright`);
}

// Newest installed browser build, for when Playwright's own pinned build is missing.
function installedChromium() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH
    || path.join(os.homedir(), process.platform === 'darwin' ? 'Library/Caches/ms-playwright' : '.cache/ms-playwright');
  if (!fs.existsSync(cache)) return null;
  const builds = fs.readdirSync(cache)
    .filter(name => /^chromium(_headless_shell)?-\d+$/.test(name))
    .sort((a, b) => (+b.split('-').pop()) - (+a.split('-').pop()) || (b.includes('headless') ? 1 : -1));
  const binaries = [
    'chrome-headless-shell-mac-arm64/chrome-headless-shell', 'chrome-headless-shell-mac-x64/chrome-headless-shell',
    'chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-headless-shell-win64/chrome-headless-shell.exe',
    'chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    'chrome-linux/chrome', 'chrome-win/chrome.exe',
  ];
  for (const build of builds) {
    for (const binary of binaries) {
      const file = path.join(cache, build, binary);
      if (fs.existsSync(file)) return file;
    }
  }
  return null;
}

async function launchChromium(options = {}) {
  const { chromium } = loadPlaywright();
  try {
    return await chromium.launch({ args: GL, ...options });
  } catch (error) {
    if (!/Executable doesn't exist|executable doesn't exist/i.test(error.message)) throw error;
    const executablePath = installedChromium();
    if (!executablePath) throw new Error('No Chromium build found. Run: npx playwright install chromium');
    return chromium.launch({ args: GL, executablePath, ...options });
  }
}

module.exports = { launchChromium, loadPlaywright, installedChromium, GL };
