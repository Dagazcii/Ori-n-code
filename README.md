# Orion Code

Terminal agent for Termux using the Gemini API.

## UI modes

- **TUI (default if Textual is installed):** full-screen client
  ```bash
  orion
  orion --tui
  ```
- **Classic line mode:**
  ```bash
  orion --cli
  ```

## Install (Termux)

```bash
pkg install python git
pip install -r requirements.txt
bash install.sh
orion
```

## Commands

`/config` `/git` `/proyecto` `@file` `/` help · in TUI: `F1` help, `Ctrl+C` quit

## License

MIT
