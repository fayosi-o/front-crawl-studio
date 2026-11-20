@AGENTS.md

## macOS notes (override the Windows-specific parts of AGENTS.md)

- Create and activate the venv with `python3.12 -m venv .venv` and
  `source .venv/bin/activate` (not `.venv/Scripts/activate`). Ignore the
  Git Bash / WSL / PowerShell advice.
- Start the server detached and log to a file, e.g.
  `nohup .venv/bin/python main.py > server.log 2>&1 &` (`*.log` is ignored).
- Find the server's PID with `lsof -ti tcp:8080 -sTCP:LISTEN`, then stop it by
  that PID. Never kill by name.
- To look at the app, use Claude's built-in browser pane or the Playwright MCP
  tools at http://127.0.0.1:8080/, not the VS Code browser.
- The scripted browser checks are `tests/browser_estimates.js` and
  `tests/browser_motion.js` (there is no `tools/browser_checks.js` here). Run
  both before pushing, with the server restarted on the current code:
  `cd tests && playwright-cli open about:blank`, then
  `playwright-cli run-code --filename=browser_estimates.js` and the same for
  `browser_motion.js`, then `playwright-cli close`. Each prints
  `"checks":"passed"` or the failed assertion.
- Both scripts open `127.0.0.1:8080`. Restart that server first (it inlines
  `engine.js` at startup); don't make copies of the scripts on another port.
- `node --check long_catch/static/engine.js` works here (Node is installed for
  checks only; the app itself still must not use Node).
- The first `import nicegui` after a while can take several minutes of slow
  disk reads (CPU time stays under a second), so the first `pytest` run or
  server start may look hung. Run them in the background; later runs take
  seconds.
