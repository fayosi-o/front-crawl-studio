@AGENTS.md

## macOS notes (override the Windows-specific parts of AGENTS.md)

- Create and activate the venv with `python3.12 -m venv .venv` and
  `source .venv/bin/activate` (not `.venv/Scripts/activate`). Ignore the
  Git Bash / WSL / PowerShell advice.
- Start the server detached and log to a file, e.g.
  `nohup .venv/bin/python main.py > server.log 2>&1 &` (`*.log` is ignored).
- Find the server's PID with `lsof -ti tcp:8080 -sTCP:LISTEN`, then stop it by
  that PID. Never kill by name.
- For browser checks, use Claude's built-in browser pane at
  http://127.0.0.1:8080/ rather than `playwright-cli` or the VS Code browser.
- `node --check long_catch/static/engine.js` works here (Node is installed for
  checks only; the app itself still must not use Node).
