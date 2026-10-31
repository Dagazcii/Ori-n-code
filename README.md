# Orion Code

Terminal agent for Termux (Android) using the Gemini API.

## Features

- File and shell tools with live output
- Git helpers and project context
- `@path` file mentions
- Project instructions via `ORION.md` / `GEMINI.md` / `AGENTS.md`
- Persistent local state (preferences, sessions, backup)
- Optional: `requests`, `tenacity`, `rich`

## Install (Termux)

```bash
pkg install python git
pip install requests tenacity rich
termux-setup-storage
cd /path/to/orion-code
bash install.sh
orion
```

Set `GEMINI_API_KEY` or enter it on first run.

## Usage

```text
orion
orion -p "summarize this error"
explica @main.py
/proyecto
/
```

## License

MIT
