#!/usr/bin/env python3
"""Orion Code — Termux agent for the Gemini API."""
from __future__ import annotations

import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

import base64
import getpass
import json
import mimetypes
import random
import re
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import requests as _requests
    USE_REQUESTS = True
except ImportError:
    _requests = None
    USE_REQUESTS = False

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    USE_TENACITY = True
except ImportError:
    USE_TENACITY = False

try:
    from rich.console import Console
    USE_RICH = True
    _console = Console(force_terminal=True)
except ImportError:
    USE_RICH = False
    _console = None

try:
    from orion_brain import (
        OrionBrain,
        SOUL_PATH,
        backup_brain_files,
        restore_brain_from_backup_if_empty,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from orion_brain import (
        OrionBrain,
        SOUL_PATH,
        backup_brain_files,
        restore_brain_from_backup_if_empty,
    )

DEFAULT_MODEL = "gemini-2.5-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CONFIG_PATH = Path.home() / ".orion_code_config"
MEMORY_PATH = Path.home() / ".orion_code_memory.md"
SESSIONS_DIR = Path.home() / ".orion_code_sessions"
LAST_SESSION_PATH = Path.home() / ".orion-code" / "last_session.json"
DIARY_PATH = Path.home() / ".orion-code" / "diary.md"
AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash",
]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_API_KEY_REF = {"key": "", "model": DEFAULT_MODEL}
_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".idea", ".gradle", "target", ".next",
}


class C:
    RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
    RED, GREEN, YELLOW, BLUE, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m"


def cprint(msg, color=""):
    print(f"{color}{msg}{C.RESET}" if color else msg)


def agent_label() -> str:
    return str(get_pref("agent_name") or "Orion")


def print_assistant(text: str) -> None:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = (text or "").strip()
    if not text:
        return
    print()
    cprint(f"{agent_label()}:", C.GREEN + C.BOLD)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    print()


def which(cmd):
    from shutil import which as w
    return w(cmd) is not None


def load_config():
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data):
    try:
        cur = load_config()
        cur.update(data)
        CONFIG_PATH.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_saved_model(default):
    return (load_config().get("model") or "").strip() or default


def save_model(model):
    save_config({"model": model})



def get_pref(key, default=None):
    return load_config().get(key, default)


def set_pref(key, value):
    save_config({key: value})


def clear_api_key_file():
    """Remove GEMINI_API_KEY lines from cwd .env if present."""
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return False
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = [ln for ln in lines if not ln.strip().startswith("GEMINI_API_KEY=")]
        env_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        return True
    except Exception:
        return False


def save_api_key_to_env(key: str) -> str:
    env_path = Path.cwd() / ".env"
    try:
        existing = ""
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8")
            lines = [ln for ln in existing.splitlines() if not ln.strip().startswith("GEMINI_API_KEY=")]
            existing = "\n".join(lines).rstrip() + "\n"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(existing)
            f.write(f"GEMINI_API_KEY={key}\n")
        return str(env_path)
    except Exception as e:
        return f"error: {e}"



def show_config():
    cfg = load_config()
    user_name = cfg.get("user_name") or "(not set)"
    agent_name = cfg.get("agent_name") or "Orion"
    model = cfg.get("model") or DEFAULT_MODEL
    auto = "on" if cfg.get("auto_mode", True) else "off"
    key_set = bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or (Path.cwd() / ".env").exists()
    )
    print(
        "\n"
        "  Current settings\n"
        "  ---------------\n"
        f"  1) Your name     {user_name}\n"
        f"  2) Agent name    {agent_name}\n"
        f"  3) Model         {model}\n"
        f"  4) Auto mode     {auto}\n"
        f"  5) API key       {'set' if key_set else 'not set'}\n"
        "  0) Back\n"
    )


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def interactive_config(model_ref: dict) -> None:
    """Numbered menu to edit settings."""
    while True:
        show_config()
        choice = _ask("  Choose [0-5]: ")
        if choice in ("0", "q", "quit", "back", ""):
            cprint("  Done.", C.DIM)
            break

        if choice == "1":
            cur = get_pref("user_name") or ""
            val = _ask(f"  Your name [{cur}]: ")
            if val:
                set_pref("user_name", val)
                cprint(f"  user_name = {val}", C.GREEN)
            else:
                cprint("  Unchanged.", C.DIM)

        elif choice == "2":
            cur = get_pref("agent_name") or "Orion"
            val = _ask(f"  Agent name [{cur}]: ")
            if val:
                set_pref("agent_name", val)
                cprint(f"  agent_name = {val}", C.GREEN)
            else:
                cprint("  Unchanged.", C.DIM)

        elif choice == "3":
            cur = get_pref("model") or DEFAULT_MODEL
            print("  Examples:", ", ".join(AVAILABLE_MODELS[:4]))
            val = _ask(f"  Model [{cur}]: ")
            if val:
                set_pref("model", val)
                model_ref["model"] = val
                cprint(f"  model = {val}", C.GREEN)
            else:
                cprint("  Unchanged.", C.DIM)

        elif choice == "4":
            cur = "on" if get_pref("auto_mode", True) else "off"
            val = _ask(f"  Auto mode on/off [{cur}]: ").lower()
            if val in ("on", "1", "true", "si", "sí"):
                set_pref("auto_mode", True)
                cprint("  auto_mode = on", C.GREEN)
            elif val in ("off", "0", "false", "no"):
                set_pref("auto_mode", False)
                cprint("  auto_mode = off", C.GREEN)
            else:
                cprint("  Unchanged.", C.DIM)

        elif choice == "5":
            print("  a) Set new API key")
            print("  b) Clear API key from .env")
            print("  c) Cancel")
            sub = _ask("  Key option [a/b/c]: ").lower()
            if sub == "a":
                key = getpass.getpass("  New API Key: ").strip()
                if not key:
                    cprint("  Cancelled.", C.DIM)
                else:
                    os.environ["GEMINI_API_KEY"] = key
                    path = save_api_key_to_env(key)
                    model_ref["key"] = key
                    cprint(f"  API key saved ({path})", C.GREEN)
            elif sub == "b":
                if "GEMINI_API_KEY" in os.environ:
                    del os.environ["GEMINI_API_KEY"]
                clear_api_key_file()
                cprint("  API key cleared from .env", C.GREEN)
            else:
                cprint("  Cancelled.", C.DIM)

        else:
            cprint("  Invalid option.", C.YELLOW)


def apply_config_command(args: str, model_ref: dict) -> str | None:
    """/config with no args opens interactive menu; with args keeps quick syntax."""
    args = (args or "").strip()
    if not args or args in ("show", "list", "menu"):
        interactive_config(model_ref)
        return None
    parts = args.split(maxsplit=1)
    sub = parts[0].lower()
    val = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("user_name", "user", "name", "me"):
        if not val:
            return "Usage: /config user_name YourName"
        set_pref("user_name", val)
        return f"user_name = {val}"
    if sub in ("agent_name", "agent", "bot"):
        if not val:
            return "Usage: /config agent_name Name"
        set_pref("agent_name", val)
        return f"agent_name = {val}"
    if sub in ("model", "modelo"):
        if not val:
            return "Usage: /config model <name>"
        set_pref("model", val)
        model_ref["model"] = val
        return f"model = {val}"
    if sub in ("auto", "auto_mode"):
        if val.lower() in ("on", "1", "true", "si", "sí"):
            set_pref("auto_mode", True)
            return "auto_mode = on"
        if val.lower() in ("off", "0", "false", "no"):
            set_pref("auto_mode", False)
            return "auto_mode = off"
        return "Usage: /config auto on|off"
    if sub in ("key", "api", "apikey", "api_key"):
        if val.lower() in ("clear", "delete", "remove", "unset"):
            if "GEMINI_API_KEY" in os.environ:
                del os.environ["GEMINI_API_KEY"]
            clear_api_key_file()
            return "API key cleared"
        key = val if val and val.lower() not in ("set", "change") else ""
        if not key:
            key = getpass.getpass("New API Key: ").strip()
        if not key:
            return "Empty key, cancelled"
        os.environ["GEMINI_API_KEY"] = key
        path = save_api_key_to_env(key)
        model_ref["key"] = key
        return f"API key saved ({path})"
    return f"Unknown option: {sub}. Type /config for the menu"


def agent_label() -> str:
    return str(get_pref("agent_name") or "Orion")


def print_assistant(text: str) -> None:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = (text or "").strip()
    if not text:
        return
    print()
    cprint(f"{agent_label()}:", C.GREEN + C.BOLD)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    print()


def which(cmd):
    from shutil import which as w
    return w(cmd) is not None


def load_config():
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data):
    try:
        cur = load_config()
        cur.update(data)
        CONFIG_PATH.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_saved_model(default):
    return (load_config().get("model") or "").strip() or default


def save_model(model):
    save_config({"model": model})



def get_pref(key, default=None):
    return load_config().get(key, default)


def set_pref(key, value):
    save_config({key: value})


def clear_api_key_file():
    """Remove GEMINI_API_KEY lines from cwd .env if present."""
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return False
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = [ln for ln in lines if not ln.strip().startswith("GEMINI_API_KEY=")]
        env_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        return True
    except Exception:
        return False


def save_api_key_to_env(key: str) -> str:
    env_path = Path.cwd() / ".env"
    try:
        existing = ""
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8")
            lines = [ln for ln in existing.splitlines() if not ln.strip().startswith("GEMINI_API_KEY=")]
            existing = "\n".join(lines).rstrip() + "\n"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(existing)
            f.write(f"GEMINI_API_KEY={key}\n")
        return str(env_path)
    except Exception as e:
        return f"error: {e}"


def show_config():
    cfg = load_config()
    user_name = cfg.get("user_name") or "(not set)"
    agent_name = cfg.get("agent_name") or "Orion"
    model = cfg.get("model") or DEFAULT_MODEL
    auto = "on" if cfg.get("auto_mode", True) else "off"
    key_set = bool(
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or (Path.cwd() / ".env").exists()
    )
    print(
        "\n"
        "  Configuration\n"
        "  ------------\n"
        f"  user_name   {user_name}\n"
        f"  agent_name  {agent_name}\n"
        f"  model       {model}\n"
        f"  auto_mode   {auto}\n"
        f"  api_key     {'set' if key_set else 'not set'}\n"
        "\n"
        "  Usage:\n"
        "  /config user_name <name>\n"
        "  /config agent_name <name>\n"
        "  /config model <model>\n"
        "  /config auto on|off\n"
        "  /config key          (set API key)\n"
        "  /config key clear    (remove from .env)\n"
        "  /config show\n"
    )


def apply_config_command(args: str, model_ref: dict) -> str | None:
    """Handle /config subcommands. Returns message or None if show only."""
    args = (args or "").strip()
    if not args or args in ("show", "list"):
        show_config()
        return None
    parts = args.split(maxsplit=1)
    sub = parts[0].lower()
    val = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("user_name", "user", "name", "me"):
        if not val:
            return "Usage: /config user_name YourName"
        set_pref("user_name", val)
        return f"user_name = {val}"

    if sub in ("agent_name", "agent", "bot"):
        if not val:
            return "Usage: /config agent_name Name"
        set_pref("agent_name", val)
        return f"agent_name = {val}"

    if sub in ("model", "modelo"):
        if not val:
            return "Usage: /config model <name>"
        set_pref("model", val)
        model_ref["model"] = val
        return f"model = {val}"

    if sub in ("auto", "auto_mode"):
        if val.lower() in ("on", "1", "true", "si", "sí"):
            set_pref("auto_mode", True)
            return "auto_mode = on"
        if val.lower() in ("off", "0", "false", "no"):
            set_pref("auto_mode", False)
            return "auto_mode = off"
        return "Usage: /config auto on|off"

    if sub in ("key", "api", "apikey", "api_key"):
        if val.lower() in ("clear", "delete", "remove", "unset"):
            if "GEMINI_API_KEY" in os.environ:
                del os.environ["GEMINI_API_KEY"]
            clear_api_key_file()
            return "API key cleared from env/.env (restart if needed)"
        # interactive or inline
        key = val if val and val.lower() not in ("set", "change") else ""
        if not key:
            key = getpass.getpass("New API Key: ").strip()
        if not key:
            return "Empty key, cancelled"
        os.environ["GEMINI_API_KEY"] = key
        path = save_api_key_to_env(key)
        model_ref["key"] = key
        return f"API key saved ({path})"

    return f"Unknown option: {sub}. Type /config show"


def memory_read():
    try:
        if MEMORY_PATH.exists():
            return MEMORY_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""
    return ""


def memory_append(text):
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n- {datetime.now().isoformat(timespec='seconds')}: {text}\n")
        return f"Saved ({MEMORY_PATH})"
    except Exception as e:
        return f"Error: {e}"


def memory_clear():
    try:
        if MEMORY_PATH.exists():
            MEMORY_PATH.unlink()
        return "Memory cleared"
    except Exception as e:
        return f"Error: {e}"


def session_save(name, history):
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]+", "_", name)[:60]
        path = SESSIONS_DIR / f"{safe}.json"
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"Saved: {path.name}"
    except Exception as e:
        return f"Error: {e}"


def session_load(name):
    try:
        safe = re.sub(r"[^\w\-]+", "_", name)[:60]
        path = SESSIONS_DIR / f"{safe}.json"
        if not path.exists():
            matches = list(SESSIONS_DIR.glob(f"*{safe}*")) if SESSIONS_DIR.exists() else []
            if not matches:
                return None, "Session not found"
            path = matches[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, f"Loaded: {path.name}"
    except Exception as e:
        return None, f"Error: {e}"


def session_list():
    if not SESSIONS_DIR.exists():
        return "(no sessions)"
    files = sorted(SESSIONS_DIR.glob("*.json"))
    if not files:
        return "(no sessions)"
    return "\n".join(f"  {f.stem}" for f in files)


def auto_save_history(history):
    try:
        LAST_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "history": history,
        }
        LAST_SESSION_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        (SESSIONS_DIR / "autosave.json").write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    try:
        backup_brain_files()
    except Exception:
        pass


def auto_load_history():
    try:
        if LAST_SESSION_PATH.exists():
            data = json.loads(LAST_SESSION_PATH.read_text(encoding="utf-8"))
            h = data.get("history") if isinstance(data, dict) else data
            if isinstance(h, list) and h:
                return h, data.get("saved_at", "?") if isinstance(data, dict) else "?"
        bak = SESSIONS_DIR / "autosave.json"
        if bak.exists():
            h = json.loads(bak.read_text(encoding="utf-8"))
            if isinstance(h, list) and h:
                return h, "autosave"
    except Exception:
        pass
    return [], None


def load_auto_mode():
    try:
        return bool(load_config().get("auto_mode", True))
    except Exception:
        return True


def save_auto_mode(on: bool):
    try:
        save_config({"auto_mode": bool(on)})
    except Exception:
        pass


def diary_append(role, text):
    try:
        if not text or not str(text).strip():
            return
        DIARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(DIARY_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n### {stamp} — {role}\n{str(text).strip()[:2000]}\n")
    except Exception:
        pass


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data and data.strip():
            self._chunks.append(data.strip())

    def text(self):
        return " ".join(self._chunks)


def html_to_text(html):
    p = _TextExtractor()
    try:
        p.feed(html)
        return p.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)



def _search_roots() -> list:
    """Directories where @path may resolve."""
    roots = []
    seen = set()
    candidates = [
        Path.cwd(),
        Path.home(),
        Path.home() / "storage" / "shared",
        Path.home() / "storage" / "downloads",
        Path.home() / "storage" / "documents",
        Path("/storage/emulated/0"),
        Path("/storage/emulated/0/Download"),
        Path("/storage/emulated/0/Documents"),
        Path("/sdcard"),
        Path("/sdcard/Download"),
    ]
    for c in candidates:
        try:
            r = c.expanduser().resolve()
            if r.is_dir() and str(r) not in seen:
                seen.add(str(r))
                roots.append(r)
        except Exception:
            continue
    return roots


def _looks_like_path(name: str) -> bool:
    return bool(re.search(r"[/\\.]|~", name)) or name.startswith(".")


def _find_by_name(name: str, roots: list, max_hits: int = 8) -> list:
    """Find files/dirs named name under roots (depth-limited)."""
    name_l = name.lower().rstrip("/")
    hits = []
    skip = _IGNORE_DIRS | {"Android", "DCIM", "Alarms", "Notifications", "Ringtones"}
    for root in roots:
        try:
            # direct child
            direct = root / name
            if direct.exists():
                hits.append(direct.resolve())
            # case-insensitive children
            try:
                for child in root.iterdir():
                    if child.name.lower() == name_l:
                        hits.append(child.resolve())
            except Exception:
                pass
        except Exception:
            pass
    # shallow walk (depth 1-3) if still few hits
    if len(hits) < 2:
        for root in roots[:6]:
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    depth = Path(dirpath).relative_to(root).parts
                    if len(depth) > 3:
                        dirnames[:] = []
                        continue
                    dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
                    base = Path(dirpath)
                    for d in list(dirnames):
                        if d.lower() == name_l or name_l in d.lower():
                            hits.append((base / d).resolve())
                    for f in filenames:
                        if f.lower() == name_l or (
                            len(name_l) > 2 and name_l in f.lower()
                        ):
                            hits.append((base / f).resolve())
                    if len(hits) >= max_hits:
                        break
            except Exception:
                continue
            if len(hits) >= max_hits:
                break
    # unique preserve order
    out = []
    seen = set()
    for h in hits:
        s = str(h)
        if s not in seen:
            seen.add(s)
            out.append(h)
    return out[:max_hits]


def _format_dir_listing(path: Path, max_entries: int = 40) -> str:
    lines = [f"[directory] {path}"]
    try:
        entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for e in entries[:max_entries]:
            lines.append(("  [DIR] " if e.is_dir() else "  ") + e.name)
        if len(entries) > max_entries:
            lines.append(f"  ... ({len(entries) - max_entries} more)")
    except Exception as ex:
        lines.append(f"  (cannot list: {ex})")
    # include short README if present
    for n in ("README.md", "ORION.md", "package.json"):
        fp = path / n
        if fp.is_file() and fp.stat().st_size < 40_000:
            try:
                lines.append(
                    f"\n--- {n} ---\n"
                    + fp.read_text(encoding="utf-8", errors="replace")[:1500]
                )
            except Exception:
                pass
    return "\n".join(lines)


def _format_file(path: Path, max_file_chars: int) -> str:
    try:
        if path.stat().st_size > 400_000:
            return f"[file too large] {path} ({path.stat().st_size} bytes)"
        body = path.read_text(encoding="utf-8", errors="replace")
    except Exception as ex:
        return f"[read error] {path}: {ex}"
    if len(body) > max_file_chars:
        body = body[:max_file_chars] + "\n...[truncated]"
    return f"--- file: {path} ---\n{body}\n--- end ---"


def expand_at_mentions(text: str, max_file_chars: int = 12000) -> str:
    """
    Expand @path, @folder, @name mentions.
    Searches cwd, home, and phone storage — not only Termux $HOME.
    """
    if not text or "@" not in text:
        return text
    # @foo, @foo/bar, @~/x, @./x, @"path with spaces" (simple)
    pattern = re.compile(r"@(\"[^\"]+\"|'[^']+'|[~/.\w\-]+(?:/[~\w.\-]+)*)")
    roots = _search_roots()
    seen = set()
    chunks = []

    def resolve_one(raw: str) -> str:
        raw = raw.strip().strip("\"'")
        if not raw or raw in seen:
            return ""
        seen.add(raw)

        # absolute / home / relative to cwd
        candidates = []
        p = Path(raw).expanduser()
        try:
            if p.is_absolute() and p.exists():
                candidates.append(p.resolve())
        except Exception:
            pass
        try:
            rel = (Path.cwd() / raw).resolve()
            if rel.exists():
                candidates.append(rel)
        except Exception:
            pass
        # search by basename across roots
        base = Path(raw).name
        found = _find_by_name(base, roots)
        for f in found:
            if f not in candidates:
                candidates.append(f)
        # also try full relative under each root
        for root in roots:
            try:
                q = (root / raw).resolve()
                if q.exists() and q not in candidates:
                    candidates.append(q)
            except Exception:
                pass

        if not candidates:
            return f"[not found: @{raw} — searched cwd, home, storage]"

        # if multiple, list them and attach the best (prefer cwd, then file match exact)
        if len(candidates) > 1:
            exact = [c for c in candidates if c.name.lower() == base.lower()]
            pick = exact[0] if exact else candidates[0]
            alt = "\n".join(f"  - {c}" for c in candidates[:6])
            header = f"[resolved @{raw} -> {pick}]\n[other matches:\n{alt}\n]"
        else:
            pick = candidates[0]
            header = f"[resolved @{raw} -> {pick}]"

        if pick.is_dir():
            return header + "\n" + _format_dir_listing(pick)
        if pick.is_file():
            return header + "\n" + _format_file(pick, max_file_chars)
        return f"[not a file/dir: {pick}]"

    def repl(m):
        raw = m.group(1)
        block = resolve_one(raw)
        if block:
            chunks.append(block)
        return m.group(0)

    new_text = pattern.sub(repl, text)
    if chunks:
        new_text = new_text + "\n\n" + "\n\n".join(chunks)
    return new_text


def load_project_instructions(root: Path | None = None) -> str:
    root = Path(root or Path.cwd()).expanduser().resolve()
    lines = []
    for name in ("ORION.md", "GEMINI.md", "AGENTS.md", ".orion.md"):
        fp = root / name
        if fp.is_file() and fp.stat().st_size < 100_000:
            try:
                lines.append(f"### {name}\n{fp.read_text(encoding='utf-8', errors='replace')[:8000]}")
            except Exception:
                pass
    return "\n\n".join(lines)


def snapshot_project_brief(root: Path | None = None, max_entries: int = 35) -> str:
    root = Path(root or Path.cwd()).expanduser().resolve()
    lines = [f"CWD: {root}"]
    try:
        entries = sorted(
            [e for e in root.iterdir() if e.name not in _IGNORE_DIRS],
            key=lambda x: (not x.is_dir(), x.name.lower()),
        )[:max_entries]
        lines.append("Contents:")
        for e in entries:
            lines.append(("  [DIR] " if e.is_dir() else "  ") + e.name)
    except Exception as ex:
        lines.append(f"(list error: {ex})")
    instr = load_project_instructions(root)
    if instr:
        lines.append("\nProject instructions:\n" + instr)
    for name in ("README.md", "README.txt", "package.json", "pyproject.toml"):
        fp = root / name
        if fp.is_file() and fp.stat().st_size < 60_000:
            try:
                lines.append(
                    f"\n--- {name} ---\n"
                    + fp.read_text(encoding="utf-8", errors="replace")[:2000]
                )
            except Exception:
                pass
    return "\n".join(lines)


def load_image_part(path):
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return f"Not a file: {path}"
        if p.suffix.lower() not in IMAGE_EXTS:
            return f"Unsupported image type: {p.suffix}"
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        return {"inline_data": {"mime_type": mime, "data": data}}
    except Exception as e:
        return f"Error: {e}"


# --- tools ---

_DANGEROUS = [
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){",
    "shutdown", "reboot", "halt", "rm -rf /*",
]


def tool_list_directory(path="."):
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            return f"Not a directory: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"Contents of {p}:"]
        for e in entries[:80]:
            lines.append(("  [DIR] " if e.is_dir() else "  ") + e.name)
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def tool_read_file(path):
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return f"Not a file: {path}"
        if p.stat().st_size > 500_000:
            return "File too large"
        return p.read_text(encoding="utf-8", errors="replace")[:50000]
    except Exception as e:
        return f"Error: {e}"


def tool_write_file(path, content):
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written: {p} ({len(content)} chars)"
    except Exception as e:
        return f"Error: {e}"


def _git_safety_check(command: str) -> str | None:
    """Block risky git usage (HOME repo, secrets)."""
    low = command.lower().strip()
    if not low.startswith("git ") and " git " not in f" {low} ":
        # still catch pure git ...
        if not re.match(r"^git\b", low):
            return None
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    # git init/add/commit/push from HOME is almost always wrong
    if cwd == home or cwd == home / "storage" or str(cwd).endswith("/storage/shared"):
        if re.search(r"\bgit\s+(init|add|commit|push|remote)\b", low):
            return (
                "Blocked: git write operations from HOME/shared root. "
                "cd into the project folder first (e.g. cd ~/storage/shared/orion-code)."
            )
    # never add secrets
    if re.search(r"\bgit\s+add\b", low):
        banned = (
            ".env", ".ssh", ".gitconfig", ".bash_history", "id_rsa", "id_ed25519",
            "credentials", "token", ".orion_code_config", "neurons.json",
        )
        for b in banned:
            if b in low:
                return f"Blocked: refusing to git add sensitive path matching '{b}'."
        if re.search(r"\bgit\s+add\s+(-A|--all|\.)\s*$", low) and cwd == home:
            return "Blocked: git add -A in HOME would stage private Termux files."
    return None


def tool_run_shell(command, confirm=False):
    low = command.lower().strip()
    for b in _DANGEROUS:
        if b in low:
            return f"Blocked: {command}"
    git_block = _git_safety_check(command)
    if git_block:
        return git_block
    if re.search(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)", low) and not confirm:
        return "Destructive rm -rf requires confirm=true after user approval."
    if command.rstrip().endswith("&") or " & " in command:
        return "Background jobs (&) are not supported here. Run in foreground."
    is_long = any(
        k in low
        for k in (
            "pkg install", "pkg upgrade", "apt install", "pip install",
            "npm install", "curl ", "wget ", "git clone",
        )
    )
    timeout = 600 if is_long else 120
    print(f"{C.DIM}$ {command}{C.RESET}", flush=True)
    collected = []
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.getcwd(),
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                proc.kill()
                collected.append(f"\n[timeout {timeout}s]")
                break
            line = proc.stdout.readline()
            if line:
                print(line, end="", flush=True)
                collected.append(line)
            elif proc.poll() is not None:
                rest = proc.stdout.read()
                if rest:
                    print(rest, end="", flush=True)
                    collected.append(rest)
                break
            else:
                time.sleep(0.05)
        code = proc.returncode if proc.returncode is not None else -1
        out = "".join(collected).strip() or "(no output)"
        return out[:20000] + f"\n[exit: {code}]"
    except Exception as e:
        return f"Error: {e}"


def tool_get_cwd():
    return f"CWD: {os.getcwd()}"


def tool_change_directory(path):
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            return f"Invalid directory: {path}"
        os.chdir(p)
        return f"CWD: {os.getcwd()}"
    except Exception as e:
        return f"Error: {e}"


def tool_fetch_url(url, max_chars=8000):
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        headers = {"User-Agent": "OrionCode/3.0"}
        if USE_REQUESTS:
            r = _requests.get(url, headers=headers, timeout=25)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            raw = r.content[:500_000]
            text_body = r.content.decode("utf-8", errors="replace")
        else:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=25) as resp:
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read(500_000)
            text_body = raw.decode("utf-8", errors="replace")
        if "html" in ctype.lower() or b"<html" in raw[:200].lower():
            text = html_to_text(raw.decode("utf-8", errors="replace"))
        else:
            text = text_body
        text = text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        return f"URL: {url}\n\n{text}" if text else f"URL: {url}\n(empty)"
    except Exception as e:
        return f"URL error: {e}"


def tool_clipboard_get():
    if not which("termux-clipboard-get"):
        return "termux-api required"
    try:
        r = subprocess.run(
            ["termux-clipboard-get"], capture_output=True, text=True, timeout=10
        )
        return r.stdout or "(empty)"
    except Exception as e:
        return f"Error: {e}"


def tool_clipboard_set(text):
    if not which("termux-clipboard-set"):
        return "termux-api required"
    try:
        subprocess.run(
            ["termux-clipboard-set"], input=text, capture_output=True, text=True, timeout=10
        )
        return "Clipboard updated"
    except Exception as e:
        return f"Error: {e}"


def tool_system_info():
    lines = [
        f"Python: {sys.version.split()[0]}",
        f"CWD: {os.getcwd()}",
        f"Home: {Path.home()}",
        f"HTTP: {'requests' if USE_REQUESTS else 'urllib'}",
    ]
    if which("termux-battery-status"):
        try:
            r = subprocess.run(
                ["termux-battery-status"], capture_output=True, text=True, timeout=8
            )
            if r.stdout:
                b = json.loads(r.stdout)
                lines.append(f"Battery: {b.get('percentage', '?')}%")
        except Exception:
            pass
    return "\n".join(lines)


def tool_notify(title, content):
    if not which("termux-notification"):
        return "termux-api required"
    try:
        subprocess.run(
            [
                "termux-notification",
                "--title", str(title)[:40],
                "--content", str(content)[:200],
            ],
            capture_output=True,
            timeout=8,
        )
        return "Notification sent"
    except Exception as e:
        return f"Error: {e}"


def tool_project_context(path="."):
    try:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            return f"Error: {path}"
        brief = snapshot_project_brief(root)
        if which("git"):
            st = subprocess.run(
                ["git", "status", "-sb"],
                capture_output=True, text=True, cwd=str(root), timeout=10,
            )
            if st.stdout:
                brief += "\nGit:\n" + st.stdout.strip()
        return brief
    except Exception as e:
        return f"Error: {e}"


def _git(args, timeout=30):
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True, timeout=timeout, cwd=os.getcwd()
        )
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return (out.strip() or "(no output)") + f"\n[exit: {r.returncode}]"
    except Exception as e:
        return f"Error: {e}"


def tool_git_status():
    return _git(["status", "-sb"])


def tool_git_diff(staged=False):
    return _git(["diff", "--staged"] if staged else ["diff"])


def tool_git_log(n=10):
    return _git(["log", f"-{max(1, min(int(n), 30))}", "--oneline", "--decorate"])


def tool_git_commit(message, confirm=False):
    if not confirm:
        return "Commit requires confirm=true after user approval."
    return _git(["commit", "-m", message])


def tool_memory_read():
    return memory_read() or "(empty)"


def tool_memory_write(text):
    return memory_append(text)


def tool_memory_clear():
    return memory_clear()


def tool_analyze_image(path, question="Describe this image."):
    part = load_image_part(path)
    if isinstance(part, str):
        return part
    key = _API_KEY_REF.get("key") or ""
    model = _API_KEY_REF.get("model") or DEFAULT_MODEL
    if not key:
        return "No API key"
    body = {
        "contents": [{"role": "user", "parts": [part, {"text": question}]}],
        "generationConfig": {"temperature": 0.4},
    }
    try:
        return parts_text(extract_parts(gemini_generate(key, model, body["contents"])))
    except Exception as e:
        return f"Error: {e}"


def _params(props, required=None):
    d = {"type": "object", "properties": props}
    if required:
        d["required"] = required
    return d


TOOL_IMPL = {
    "list_directory": lambda a: tool_list_directory(a.get("path", ".")),
    "read_file": lambda a: tool_read_file(a["path"]),
    "write_file": lambda a: tool_write_file(a["path"], a.get("content", "")),
    "run_shell": lambda a: tool_run_shell(a["command"], bool(a.get("confirm", False))),
    "get_cwd": lambda a: tool_get_cwd(),
    "change_directory": lambda a: tool_change_directory(a["path"]),
    "fetch_url": lambda a: tool_fetch_url(a["url"], int(a.get("max_chars", 8000) or 8000)),
    "clipboard_get": lambda a: tool_clipboard_get(),
    "clipboard_set": lambda a: tool_clipboard_set(a.get("text", "")),
    "system_info": lambda a: tool_system_info(),
    "notify": lambda a: tool_notify(a.get("title", "Orion"), a.get("content", "")),
    "project_context": lambda a: tool_project_context(a.get("path", ".")),
    "git_status": lambda a: tool_git_status(),
    "git_diff": lambda a: tool_git_diff(bool(a.get("staged", False))),
    "git_log": lambda a: tool_git_log(a.get("n", 10)),
    "git_commit": lambda a: tool_git_commit(a.get("message", ""), bool(a.get("confirm", False))),
    "memory_read": lambda a: tool_memory_read(),
    "memory_write": lambda a: tool_memory_write(a.get("text", "")),
    "memory_clear": lambda a: tool_memory_clear(),
    "analyze_image": lambda a: tool_analyze_image(a["path"], a.get("question", "Describe this image.")),
}

TOOL_DECLARATIONS = [
    {"name": "list_directory", "description": "List directory.", "parameters": _params({"path": {"type": "string"}})},
    {"name": "read_file", "description": "Read text file.", "parameters": _params({"path": {"type": "string"}}, ["path"])},
    {"name": "write_file", "description": "Write text file.", "parameters": _params({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"])},
    {"name": "run_shell", "description": "Run shell command with live output. Destructive needs confirm=true. For git: only inside a project folder, never $HOME. Never add .env or secrets.", "parameters": _params({"command": {"type": "string"}, "confirm": {"type": "boolean"}}, ["command"])},
    {"name": "get_cwd", "description": "Current directory.", "parameters": _params({})},
    {"name": "change_directory", "description": "Change directory.", "parameters": _params({"path": {"type": "string"}}, ["path"])},
    {"name": "fetch_url", "description": "Fetch URL text.", "parameters": _params({"url": {"type": "string"}, "max_chars": {"type": "integer"}}, ["url"])},
    {"name": "clipboard_get", "description": "Get clipboard.", "parameters": _params({})},
    {"name": "clipboard_set", "description": "Set clipboard.", "parameters": _params({"text": {"type": "string"}}, ["text"])},
    {"name": "system_info", "description": "System info.", "parameters": _params({})},
    {"name": "notify", "description": "Android notification.", "parameters": _params({"title": {"type": "string"}, "content": {"type": "string"}}, ["content"])},
    {"name": "project_context", "description": "Project summary.", "parameters": _params({"path": {"type": "string"}})},
    {"name": "git_status", "description": "git status.", "parameters": _params({})},
    {"name": "git_diff", "description": "git diff.", "parameters": _params({"staged": {"type": "boolean"}})},
    {"name": "git_log", "description": "git log.", "parameters": _params({"n": {"type": "integer"}})},
    {"name": "git_commit", "description": "git commit (confirm=true).", "parameters": _params({"message": {"type": "string"}, "confirm": {"type": "boolean"}}, ["message"])},
    {"name": "memory_read", "description": "Read notes memory.", "parameters": _params({})},
    {"name": "memory_write", "description": "Append notes memory.", "parameters": _params({"text": {"type": "string"}}, ["text"])},
    {"name": "memory_clear", "description": "Clear notes memory.", "parameters": _params({})},
    {"name": "analyze_image", "description": "Analyze image file.", "parameters": _params({"path": {"type": "string"}, "question": {"type": "string"}}, ["path"])},
]


def extract_parts(response):
    cands = response.get("candidates") or []
    if not cands:
        return []
    return (cands[0].get("content") or {}).get("parts") or []


def parts_text(parts):
    return "\n".join(p["text"] for p in parts if "text" in p and p["text"]).strip()


def parts_function_calls(parts):
    return [p["functionCall"] for p in parts if "functionCall" in p]


def load_api_key():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if key:
        return key.strip()
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    while True:
        key = getpass.getpass("API Key: ").strip()
        if not key:
            cprint("Empty key.", C.RED)
            continue
        if input("Save to .env? [y/N]: ").strip().lower() in ("y", "yes", "s", "si"):
            try:
                with open(Path.cwd() / ".env", "a", encoding="utf-8") as f:
                    f.write(f"\nGEMINI_API_KEY={key}\n")
                cprint("Saved.", C.GREEN)
            except Exception as ex:
                cprint(str(ex), C.YELLOW)
        return key


def classify_network_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = str(exc)
        try:
            msg = json.loads(raw).get("error", {}).get("message", raw)
        except Exception:
            msg = raw
        if code == 401:
            return "Invalid API key (401)."
        if code == 429:
            return "Rate limit (429). Wait and retry."
        if code >= 500:
            return f"Server error ({code}). Retry later."
        return f"HTTP {code}: {msg}"
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", exc)).lower()
        if "timed out" in reason or "timeout" in reason:
            return "Network timeout."
        if "name or service" in reason or "nodename" in reason:
            return "No DNS / no internet."
        return f"Network error: {exc.reason}"
    return f"Error: {exc}"


def _gemini_post_once(url, body, headers):
    if USE_REQUESTS:
        r = _requests.post(url, json=body, headers=headers, timeout=120)
        if r.status_code >= 400:
            try:
                msg = r.json().get("error", {}).get("message", r.text)
            except Exception:
                msg = r.text
            raise RuntimeError(f"HTTP {r.status_code}: {msg}")
        return r.json()
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(classify_network_error(e)) from e
    except urllib.error.URLError as e:
        raise RuntimeError(classify_network_error(e)) from e


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(x in msg for x in ("429", "rate limit", "500", "502", "503", "504", "timeout"))


def _gemini_post(url, body, headers):
    if USE_TENACITY:
        @retry(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type(RuntimeError),
        )
        def _do():
            try:
                return _gemini_post_once(url, body, headers)
            except RuntimeError as e:
                if _is_retryable(e):
                    cprint(f"  (retry: {e})", C.DIM)
                    raise
                raise
        return _do()
    try:
        return _gemini_post_once(url, body, headers)
    except RuntimeError as e:
        if _is_retryable(e):
            cprint("  (retry in 2s)", C.DIM)
            time.sleep(2)
            return _gemini_post_once(url, body, headers)
        raise


def gemini_generate(api_key, model, contents, system_instruction=None):
    url = f"{API_BASE}/models/{model}:generateContent"
    body = {
        "contents": contents,
        "tools": [{"function_declarations": TOOL_DECLARATIONS}],
        "generationConfig": {"temperature": 0.7},
    }
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    try:
        return _gemini_post(url, body, headers)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Network error: {e}") from e


def gemini_stream_text(api_key, model, contents, system_instruction=None):
    """Stream text-only response; force UTF-8 decoding."""
    url = f"{API_BASE}/models/{model}:streamGenerateContent?alt=sse"
    body = {"contents": contents, "generationConfig": {"temperature": 0.7}}
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    full = []

    def emit(tx):
        if not tx:
            return
        if isinstance(tx, bytes):
            tx = tx.decode("utf-8", errors="replace")
        print(tx, end="", flush=True)
        full.append(tx)

    if USE_REQUESTS:
        with _requests.post(url, json=body, headers=headers, timeout=120, stream=True) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")
            for raw in resp.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                for part in extract_parts(obj):
                    emit(part.get("text") or "")
    else:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            buf = b""
            while True:
                chunk = resp.read(512)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_b, buf = buf.split(b"\n", 1)
                    line = line_b.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    for part in extract_parts(obj):
                        emit(part.get("text") or "")
    if full:
        print()
    return "".join(full)


def should_try_text_stream(user_text: str) -> bool:
    if not user_text or len(user_text) > 400 or "@" in user_text:
        return False
    low = user_text.lower()
    triggers = (
        "install", "instala", "ejecuta", "run ", "lee ", "read ", "write ",
        "git ", "pkg ", "pip ", "shell", "archivo", "file ", "commit",
    )
    return not any(x in low for x in triggers)


def network_reachable(timeout: float = 3.0) -> bool:
    try:
        if USE_REQUESTS:
            r = _requests.head("https://www.google.com/", timeout=timeout, allow_redirects=True)
            return r.status_code < 500
        req = urllib.request.Request("https://www.google.com/", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True
    except Exception:
        return False


def build_system(brain=None):
    mem = memory_read()
    mem_block = ("\n\nUser memory:\n" + mem[:3000] + "\n") if mem else ""
    brain_block = ""
    if brain is not None:
        try:
            brain_block = "\n\n" + brain.snapshot_for_prompt()
        except Exception as e:
            brain_block = f"\n\n(brain unavailable: {e})"
    user_name = get_pref("user_name") or ""
    agent_name = get_pref("agent_name") or "Orion"
    parts = [
        f"You are {agent_name}, a technical assistant running in Termux (Orion Code).",
        "Be clear, concise, and practical. Focus on programming and system tasks.",
        "Use a neutral professional tone.",
        "If the user attaches file contents with @path, use that content.",
        "Respect ORION.md / GEMINI.md / AGENTS.md when present.",
        "Prefer short shell commands that finish; avoid background jobs and infinite loops.",
        "Confirm before destructive operations such as recursive deletes.",
        "Reply in the user's language with correct UTF-8 text.",
        "Never store API tokens, passwords, or secrets in memory, brain, diary, or files.",
        "Before any git write (init/add/commit/push), run pwd and git status. If cwd is $HOME, cd to the project first.",
        "Never git init or git add in $HOME or storage shared root.",
        "Never git add .env, .ssh, tokens, credentials, or whole Termux config.",
        "Prefer few precise shell commands over many exploratory ones.",
        "If git asks for credentials, stop and tell the user to run git push themselves with a PAT.",
        "Do not loop on the same failing command more than twice; explain the fix instead.",
    ]
    if user_name:
        parts.append(f"The user's name is {user_name}. Address them as {user_name} when natural.")
    proj = ""
    try:
        instr = load_project_instructions(Path.cwd())
        if instr:
            proj = "\n\n## Project instructions\n" + instr[:6000]
    except Exception:
        pass
    return " ".join(parts) + mem_block + brain_block + proj


def _parts_have_function_call(parts) -> bool:
    return any(isinstance(p, dict) and "functionCall" in p for p in (parts or []))


def _parts_have_function_response(parts) -> bool:
    return any(isinstance(p, dict) and "functionResponse" in p for p in (parts or []))


def sanitize_history(history: list) -> list:
    if not history:
        return []
    out = []
    i = 0
    n = len(history)
    while i < n:
        item = history[i]
        if not isinstance(item, dict):
            i += 1
            continue
        role = item.get("role")
        parts = item.get("parts") or []
        if role == "user" and _parts_have_function_response(parts):
            if out and out[-1].get("role") == "model" and _parts_have_function_call(out[-1].get("parts") or []):
                out.append(item)
            i += 1
            continue
        if role == "model" and _parts_have_function_call(parts):
            has_fr = (
                i + 1 < n
                and history[i + 1].get("role") == "user"
                and _parts_have_function_response(history[i + 1].get("parts") or [])
            )
            if has_fr:
                out.append(item)
                out.append(history[i + 1])
                i += 2
                continue
            text_parts = [p for p in parts if isinstance(p, dict) and "text" in p]
            if text_parts:
                out.append({"role": "model", "parts": text_parts})
            i += 1
            continue
        if role in ("user", "model"):
            clean = [
                p for p in parts
                if isinstance(p, dict)
                and "functionResponse" not in p
                and ("text" in p or "functionCall" in p or "inline_data" in p)
            ]
            if role == "user":
                clean = [p for p in clean if "functionCall" not in p]
            if clean:
                out.append({"role": role, "parts": clean})
        i += 1
    if out and out[-1].get("role") == "model" and _parts_have_function_call(out[-1].get("parts") or []):
        text_parts = [p for p in (out[-1].get("parts") or []) if isinstance(p, dict) and "text" in p]
        if text_parts:
            out[-1] = {"role": "model", "parts": text_parts}
        else:
            out.pop()
    return out


def ensure_api_history(history: list) -> list:
    h = sanitize_history(history)
    if not h:
        return h
    merged = []
    for item in h:
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        role = item.get("role")
        if role == "model" and prev.get("role") == "model":
            merged[-1] = {
                "role": "model",
                "parts": list(prev.get("parts") or []) + list(item.get("parts") or []),
            }
            continue
        if (
            role == "user" and prev.get("role") == "user"
            and not _parts_have_function_response(item.get("parts") or [])
            and not _parts_have_function_response(prev.get("parts") or [])
        ):
            merged[-1] = {
                "role": "user",
                "parts": list(prev.get("parts") or []) + list(item.get("parts") or []),
            }
            continue
        if role == "user" and _parts_have_function_response(item.get("parts") or []):
            if not (prev.get("role") == "model" and _parts_have_function_call(prev.get("parts") or [])):
                continue
        merged.append(item)
    if merged and merged[0].get("role") != "user":
        merged.insert(0, {"role": "user", "parts": [{"text": "(session start)"}]})
    return merged


def _turn_brief(item: dict, limit: int = 200) -> str:
    role = item.get("role", "?")
    bits = []
    for p in item.get("parts") or []:
        if not isinstance(p, dict):
            continue
        if p.get("text"):
            bits.append(p["text"].strip().replace("\n", " "))
        elif "functionCall" in p:
            bits.append(f"[tool:{p['functionCall'].get('name', '?')}]")
        elif "functionResponse" in p:
            bits.append(f"[result:{p['functionResponse'].get('name', '?')}]")
    text = " ".join(bits).strip()
    if len(text) > limit:
        text = text[:limit] + "..."
    return f"{role}: {text}" if text else ""


def compact_history(history: list, keep_last: int = 12) -> list:
    h = sanitize_history(history)
    if len(h) <= keep_last + 2:
        return h
    old, recent = h[:-keep_last], h[-keep_last:]
    briefs = [b for b in (_turn_brief(x) for x in old) if b]
    summary = " | ".join(briefs)
    if len(summary) > 1500:
        summary = "..." + summary[-1500:]
    compact_turn = {
        "role": "user",
        "parts": [{"text": "(Earlier conversation summary)\n" + summary}],
    }
    return ensure_api_history([compact_turn] + recent)


def _input_with_timeout(prompt: str, timeout: float):
    # Always start the prompt on a fresh line (avoids "you> you>")
    print(prompt, end="", flush=True)
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (ValueError, OSError):
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            raise
    if ready:
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")
    # Timeout: move to next line so the next prompt is not glued
    print(flush=True)
    return None


def proactive_open_line(brain, history) -> str:
    mood = (brain.data.get("mood") or {}).get("nombre", "neutral")
    hour = datetime.now().hour
    if 5 <= hour < 12:
        base = "Good morning. What should we work on?"
    elif 12 <= hour < 19:
        base = "Hello. What do you need?"
    elif 19 <= hour < 24:
        base = "Good evening. Continue a task or start something new?"
    else:
        base = "Late session. Urgent bug or wrap up?"
    if history:
        return f"{base} (previous session restored)."
    if mood in ("tensa", "apagada"):
        return "Ready. State the task."
    return base





def print_banner(model: str) -> None:
    """Startup banner with colored ASCII."""
    # ANSI colors for logo lines
    colors = [
        "\033[96m",  # bright cyan
        "\033[36m",  # cyan
        "\033[94m",  # bright blue
        "\033[34m",  # blue
        "\033[95m",  # bright magenta
        "\033[92m",  # bright green
        "\033[32m",  # green
        "\033[93m",  # bright yellow
        "\033[33m",  # yellow
        "\033[91m",  # bright red
    ]
    reset = "\033[0m"
    bold = "\033[1m"
    lines = [
        r"   ___  ____  ___  ___  _   _",
        r"  / _ \|  _ \|_ _|/ _ \| \ | |",
        r" | | | | |_) || || | | |  \| |",
        r" | |_| |  _ < | || |_| | |\  |",
        r"  \___/|_| \_\___|\___/|_| \_|",
        r"   ____ ___  ____  _____",
        r"  / ___/ _ \|  _ \| ____|",
        r" | |  | | | | | | |  _|",
        r" | |__| |_| | |_| | |___",
        r"  \____\___/|____/|_____|",
    ]
    print()
    for i, line in enumerate(lines):
        # ORION (first 5 lines) cooler palette; CODE (last 5) warmer
        color = colors[i % len(colors)]
        print(f"{bold}{color}{line}{reset}")
    print(f"\033[2m  Orion Code  ·  Termux agent for Gemini{reset}")
    print(f"\033[2m  Dagazcii Dev{reset}")
    print(f"\033[2m  {'-' * 40}{reset}")
    cprint(f"  Model  {model}", C.CYAN)
    cprint(f"  Dir    {os.getcwd()}", C.DIM)
    http = "requests" if USE_REQUESTS else "urllib"
    extras = []
    if USE_TENACITY:
        extras.append("retry")
    if USE_RICH:
        extras.append("rich")
    cprint(f"  HTTP   {http}" + (f" +{'+'.join(extras)}" if extras else ""), C.DIM)
    cprint("  Type / for commands", C.DIM)
    print(f"\033[2m  {'-' * 40}{reset}")
    print()

def run_agent(api_key, model, seed_prompt=None, use_stream=True):
    _API_KEY_REF["key"] = api_key
    _API_KEY_REF["model"] = model
    try:
        restore_brain_from_backup_if_empty()
    except Exception:
        pass
    brain = OrionBrain()
    try:
        pkg_soul = Path(__file__).resolve().parent / "soul_default.md"
        if pkg_soul.exists() and (not SOUL_PATH.exists() or len(brain.read_soul()) < 40):
            brain.write_soul(pkg_soul.read_text(encoding="utf-8"))
    except Exception:
        pass

    print_banner(model)

    history, saved_at = auto_load_history()
    history = sanitize_history(history)
    system = build_system(brain)
    try:
        if load_project_instructions(Path.cwd()):
            cprint("  Project instructions loaded.", C.DIM)
    except Exception:
        pass
    if history:
        cprint(f"  Session restored ({saved_at}), messages: {len(history)}", C.CYAN)

    open_line = proactive_open_line(brain, history)
    print()
    cprint(f"{agent_label()}:", C.GREEN + C.BOLD)
    print(open_line)
    print()
    if not history:
        history.append({"role": "user", "parts": [{"text": "(session start)"}]})
    history.append({"role": "model", "parts": [{"text": open_line}]})
    history[:] = ensure_api_history(history)
    auto_save_history(history)
    try:
        brain.save()
    except Exception:
        pass

    def handle_turn(user_parts):
        nonlocal history, model, system
        new_parts = []
        for part in user_parts:
            if isinstance(part, dict) and part.get("text"):
                expanded = expand_at_mentions(part["text"])
                if expanded != part["text"]:
                    cprint("  (@ path resolved)", C.DIM)
                new_parts.append({**part, "text": expanded})
            else:
                new_parts.append(part)
        user_parts = new_parts

        try:
            utext = " ".join(
                p.get("text", "") for p in user_parts if isinstance(p, dict) and "text" in p
            ).strip()
            if utext:
                brain.perceive(utext)
                system = build_system(brain)
        except Exception:
            pass

        history[:] = sanitize_history(history)
        history.append({"role": "user", "parts": user_parts})
        handle_turn._recent_tools = []

        try:
            if use_stream:
                ut = " ".join(
                    p.get("text", "") for p in user_parts if isinstance(p, dict) and p.get("text")
                )
                if should_try_text_stream(ut):
                    try:
                        cprint("... thinking", C.DIM)
                        print()
                        cprint(f"{agent_label()}:", C.GREEN + C.BOLD)
                        streamed = gemini_stream_text(
                            api_key, model, ensure_api_history(history), system
                        )
                        if streamed and streamed.strip():
                            history.append({"role": "model", "parts": [{"text": streamed}]})
                            history[:] = sanitize_history(history)
                            auto_save_history(history)
                            try:
                                brain.save()
                            except Exception:
                                pass
                            return
                        print()
                    except Exception as ex:
                        cprint(f"  (stream fallback: {ex})", C.DIM)

            for _ in range(40):
                cprint("... thinking", C.DIM)
                if len(history) > 16:
                    history[:] = compact_history(history, keep_last=12)
                api_hist = ensure_api_history(history)
                try:
                    resp = gemini_generate(api_key, model, api_hist, system)
                except RuntimeError as net_err:
                    msg = str(net_err).lower()
                    if any(x in msg for x in ("network", "internet", "dns", "timeout", "unreachable")):
                        cprint("No cloud connection. Local commands still work.", C.YELLOW)
                        cprint(str(net_err), C.DIM)
                        return
                    raise
                parts = extract_parts(resp)
                if not parts:
                    cprint("(empty response)", C.YELLOW)
                    break
                fcalls = parts_function_calls(parts)
                text = parts_text(parts)
                if not fcalls:
                    history.append({"role": "model", "parts": parts})
                    if text:
                        print_assistant(text)
                    break
                history.append({"role": "model", "parts": parts})
                fn_responses = []
                for fc in fcalls:
                    name = fc.get("name", "")
                    args = fc.get("args") or {}
                    sig = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                    if not hasattr(handle_turn, "_recent_tools"):
                        handle_turn._recent_tools = []
                    recent = handle_turn._recent_tools
                    if recent.count(sig) >= 2:
                        result = (
                            "Stopped: same tool/args repeated 3 times. "
                            "Change approach or ask the user to run the command manually."
                        )
                        cprint(f"  -> {name} (blocked repeat)", C.YELLOW)
                        fn_responses.append(
                            {"functionResponse": {"name": name, "response": {"result": result}}}
                        )
                        continue
                    recent.append(sig)
                    if len(recent) > 30:
                        handle_turn._recent_tools = recent[-20:]
                    cprint(f"  -> {name}({args})", C.DIM)
                    impl = TOOL_IMPL.get(name)
                    try:
                        result = impl(args) if impl else f"Unknown tool: {name}"
                    except Exception as tool_ex:
                        result = f"Tool error: {tool_ex}"
                    if not isinstance(result, (str, dict, list, int, float, bool)):
                        result = str(result)
                    if isinstance(result, str) and len(result) > 12000:
                        result = result[:12000] + "\n...[truncated]"
                    fn_responses.append(
                        {"functionResponse": {"name": name, "response": {"result": result}}}
                    )
                history.append({"role": "user", "parts": fn_responses})
            else:
                cprint("(tool step limit — try a smaller task or run git yourself)", C.YELLOW)
            history[:] = sanitize_history(history)
            auto_save_history(history)
            try:
                brain.save()
            except Exception:
                pass
        except Exception as e:
            cprint(str(e), C.YELLOW if "HTTP" in str(e) or "Network" in str(e) else C.RED)
            history[:] = sanitize_history(history)
            auto_save_history(history)

    if seed_prompt:
        handle_turn([{"text": seed_prompt}])
        return

    idle_rounds = 0
    IDLE_TIMEOUT = 90.0
    while True:
        try:
            user_input = _input_with_timeout(f"\n{C.BLUE}{C.BOLD}you>{C.RESET} ", IDLE_TIMEOUT)
        except (KeyboardInterrupt, EOFError):
            auto_save_history(history)
            try:
                brain.save()
            except Exception:
                pass
            print("\nSession saved.")
            break

        if user_input is None:
            idle_rounds += 1
            if load_auto_mode() and idle_rounds in (2, 5):
                try:
                    brain.tick_alone(idle_rounds * IDLE_TIMEOUT)
                except Exception:
                    pass
            continue

        user_input = user_input.strip()
        if not user_input:
            continue
        idle_rounds = 0
        low = user_input.lower().strip()

        def show_menu():
            print(
                "\nCommands:\n"
                "  /                  This menu\n"
                "  /quit /exit        Exit\n"
                "  /clear             Clear chat + screen\n"
                "  /model [name]      Show/set model\n"
                "  /config            Settings (name, key, model)\n"
                "  /image <path> [q]  Analyze image\n"
                "  /proyecto          Project summary\n"
                "  /compact           Compact history\n"
                "  /red               Network check\n"
                "  /fichas /gustos    Preference cards\n"
                "  /diario /backup    Diary / backup\n"
                "  /save /load        Sessions\n"
                "  @file or @folder   Attach file/folder (searches storage)\n"
            )

        if user_input.strip() == "/" or low in ("/help", "/ayuda", "/comandos"):
            show_menu()
            continue
        if low in ("/quit", "/exit", "/salir", "quit", "exit"):
            auto_save_history(history)
            try:
                brain.save()
            except Exception:
                pass
            print("Bye.")
            break
        if low in ("/clear", "/limpiar"):
            history.clear()
            os.system("clear")
            cprint("Chat cleared.", C.GREEN)
            continue
        if low in ("/diario", "/diary"):
            if DIARY_PATH.exists():
                print(DIARY_PATH.read_text(encoding="utf-8", errors="replace")[-8000:])
            else:
                print("(empty)")
            continue
        if low in ("/backup", "/respaldo"):
            try:
                brain.save()
            except Exception:
                pass
            cprint(str(backup_brain_files()), C.GREEN)
            continue
        if low in ("/compact", "/compactar"):
            before = len(history)
            history[:] = compact_history(history, keep_last=12)
            auto_save_history(history)
            cprint(f"Compacted {before} -> {len(history)}", C.GREEN)
            continue
        if low in ("/red", "/net"):
            cprint(f"HTTP client: {'requests' if USE_REQUESTS else 'urllib'}", C.DIM)
            cprint("Online." if network_reachable() else "Offline.", C.GREEN if network_reachable() else C.YELLOW)
            continue
        if low in ("/proyecto", "/project", "/ctx"):
            print(snapshot_project_brief(Path.cwd()))
            continue
        if low in ("/fichas", "/cards"):
            try:
                print(brain.cards_text())
            except Exception as e:
                print(e)
            continue
        if low in ("/gustos", "/promesas", "/proyectos"):
            try:
                print(brain.cards_text())
            except Exception as e:
                print(e)
            continue
        if low in ("/mood", "/animo", "/brain", "/cerebro"):
            try:
                print(brain.status_text())
            except Exception as e:
                print(e)
            continue
        if low in ("/soul", "/alma"):
            try:
                print(brain.read_soul())
            except Exception as e:
                print(e)
            continue
        if low == "/config" or low.startswith("/config "):
            rest = user_input[7:].strip() if len(user_input) > 7 else ""
            model_ref = _API_KEY_REF
            msg = apply_config_command(rest, model_ref)
            if msg:
                cprint(msg, C.GREEN)
            # refresh model local var if changed
            if model_ref.get("model"):
                model = model_ref["model"]
            if model_ref.get("key"):
                api_key = model_ref["key"]
            system = build_system(brain)
            continue
        if low.startswith("/model") or low.startswith("/modelo"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                model = parts[1].strip()
                save_model(model)
                _API_KEY_REF["model"] = model
                cprint(f"Model: {model}", C.GREEN)
            else:
                print(f"Current: {model}")
                print("Examples:", ", ".join(AVAILABLE_MODELS))
            continue
        if low.startswith("/image") or low.startswith("/imagen"):
            tokens = user_input.split(maxsplit=2)
            if len(tokens) < 2:
                cprint("Usage: /image path.jpg [question]", C.YELLOW)
                continue
            part = load_image_part(tokens[1])
            if isinstance(part, str):
                cprint(part, C.RED)
                continue
            q = tokens[2] if len(tokens) > 2 else "Describe this image."
            handle_turn([part, {"text": q}])
            continue
        if low.startswith("/save") or low.startswith("/guardar"):
            parts = user_input.split(maxsplit=1)
            name = parts[1].strip() if len(parts) == 2 else datetime.now().strftime("chat_%Y%m%d_%H%M")
            cprint(session_save(name, history), C.GREEN)
            continue
        if low.startswith("/load") or low.startswith("/cargar"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                cprint("Usage: /load name", C.YELLOW)
                continue
            data, msg = session_load(parts[1])
            cprint(msg, C.GREEN if data is not None else C.RED)
            if data is not None:
                history = data
            continue
        if low in ("/sessions", "/sesiones"):
            print(session_list())
            continue
        if low.startswith("/") and len(low) > 1:
            cprint(f"Unknown command. Type / for help.", C.YELLOW)
            continue

        handle_turn([{"text": user_input}])


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Orion Code 3.5.0 (Termux)")
    parser.add_argument("-m", "--model", default=None)
    parser.add_argument("-p", "--prompt", default=None)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--version", action="version", version="3.5.0")
    args = parser.parse_args()
    cprint("Orion Code 3.5.0", C.BOLD)
    api_key = load_api_key()
    model = args.model or load_saved_model(DEFAULT_MODEL)
    if args.model:
        save_model(model)
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        try:
            prompt = sys.stdin.read().strip() or None
        except Exception:
            prompt = None
    run_agent(api_key, model, seed_prompt=prompt, use_stream=not args.no_stream)


if __name__ == "__main__":
    main()
