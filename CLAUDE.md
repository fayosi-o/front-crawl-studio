@AGENTS.md

## macOS notes

- Create the venv with `python3.12 -m venv .venv` and activate it with
  `source .venv/bin/activate`.
- Start the server detached and log to a file:
  `nohup .venv/bin/python main.py > server.log 2>&1 &` (`*.log` is ignored).
- Find the server's PID with `lsof -ti tcp:8080 -sTCP:LISTEN`, then stop it by
  that PID. Never kill by name.
- To look at the app, use the built-in browser pane or the Playwright MCP
  tools at http://127.0.0.1:8080/. Run the scripted browser checks with
  `node tools/browser_checks.js` (no `NODE_PATH` needed), or with
  `playwright-cli` as in "Checks".
- Node is installed here for the checks only.
- The first `import nicegui` after a while can take several minutes of slow
  disk reads (CPU time stays under a second), so the first `pytest` run or
  server start may look hung. Run them in the background; later runs take
  seconds.

## When the Fayosi AI Panel is running (local)

The panel (`../fayosi-ai-panel`, http://127.0.0.1:7411) may already be running this app as `long-catch`; `../CLAUDE.md`
has the general rules. Check before starting a server:

```bash
curl -s localhost:7411/api/projects | python3 -c "import json,sys; print(*[p['url'] for p in json.load(sys.stdin) if p['id']=='long-catch' and p['url']])"
```

If that prints a URL, use the panel's server and skip the start/stop steps above and in AGENTS.md:

- Don't start a second copy (the panel kills same-command copies from this folder as strays) and don't stop the
  panel's copy by PID.
- It restarts the server when code changes, on the same port. To force it: `curl -X POST localhost:7411/api/projects/long-catch/restart`.
- Server output is at `curl -s 'localhost:7411/api/projects/long-catch/logs?tail=200'` (no `server.log` in this case).
- Browser checks: pass the URL, `node tools/browser_checks.js <url>`, instead of restarting on a fixed port.

If nothing answers on 7411, the panel isn't running: follow the steps above as before.
