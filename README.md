# Orion Code

Terminal agent for Termux using the Gemini API.

## Features

- File, shell, git, and project tools
- `@path` file mentions
- `ORION.md` / `GEMINI.md` project instructions
- Session restore, history compaction
- Optional: `requests`, `tenacity`, `rich`

## Install (Termux)

```bash
pkg install python git
pip install requests tenacity rich
bash install.sh
orion
```

Set `GEMINI_API_KEY` or enter it on first launch.

## Usage

```text
orion
explica @main.py
/proyecto
/
```

## License

MIT
