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
  `playwright-cli`, as in "Checks".
- Node is installed here for the checks only.
- The first `import nicegui` after a while can take several minutes of slow
  disk reads (CPU time stays under a second), so the first `pytest` run or
  server start may look hung. Run them in the background; later runs take
  seconds.
