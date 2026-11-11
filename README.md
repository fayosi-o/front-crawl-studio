# Long Catch

Long Catch is a rapid local prototype for visualising front-crawl stroke shape.

> **Status:** planning complete; the prototype is not built yet. Run
> `/build-prototype` in Copilot Chat. See [BUILD_SPEC.md](BUILD_SPEC.md) and
> [AGENTS.md](AGENTS.md).

It demonstrates:

- catch quality;
- body roll;
- hand slip;
- arm-driven versus hip-connected timing;
- simple estimated back, triceps, and hip/core contribution;
- rough distance-per-stroke and pace estimates.

The swimmer is an intentionally simple procedural human, not a realistic
anatomical model.

All metrics and muscle colours are coaching estimates. They are not measured
EMG, force, medical, or diagnostic data.

The application is completely silent and does not use microphone or audio APIs.

## Repository layout

```text
.
├── .github/
│   ├── copilot-instructions.md               # Always-on Copilot rules
│   └── prompts/
│       ├── build-prototype.prompt.md         # Current build: /build-prototype
│       └── future-production-refactor.prompt.md  # Deferred; do not run yet
├── AGENTS.md                                 # Current objective and hard rules
├── BUILD_SPEC.md                             # Source-of-truth specification
├── README.md
├── requirements.txt
├── .gitignore
└── main.py                                   # Created by /build-prototype
```

## Requirements

- Python 3.12
- NiceGUI

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py
```

Open:

```text
http://127.0.0.1:8080
```
