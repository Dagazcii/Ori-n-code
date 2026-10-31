#!/usr/bin/env python3
"""Orion Code 3.0 (Termux) — agente de IA para programar en la terminal."""
from __future__ import annotations
import base64, getpass, json, mimetypes, os, random, re, select, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

# force utf-8 on stdio
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
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.theme import Theme
    USE_RICH = True
    _console = Console(theme=Theme({
        "info": "cyan",
        "warn": "yellow",
        "err": "bold red",
        "ok": "green",
    }))
except ImportError:
    USE_RICH = False
    _console = None

try:
    from orion_brain import OrionBrain, BRAIN_DIR, SOUL_PATH, backup_brain_files, restore_brain_from_backup_if_empty, resolve_backup_dir
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from orion_brain import OrionBrain, BRAIN_DIR, SOUL_PATH, backup_brain_files, restore_brain_from_backup_if_empty, resolve_backup_dir

DEFAULT_MODEL = "gemini-3.8-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CONFIG_PATH = Path.home() / ".orion_code_config"
MEMORY_PATH = Path.home() / ".orion_code_memory.md"
SESSIONS_DIR = Path.home() / ".orion_code_sessions"
LAST_SESSION_PATH = Path.home() / ".orion-code" / "last_session.json"
DIARY_PATH = Path.home() / ".orion-code" / "diary.md"
BRAIN_PATH = Path.home() / ".orion_code_brain.json"
AVAILABLE_MODELS = [
    "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite", "gemini-4-argon",
]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_API_KEY_REF = {"key": "", "model": DEFAULT_MODEL}

class C:
    RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
    RED, GREEN, YELLOW, BLUE, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m"

def cprint(msg, color=""):
    if USE_RICH and _console is not None:
        style = None
        if color == C.RED or color == C.RED + C.BOLD:
            style = "err"
        elif color == C.GREEN or color == C.GREEN + C.BOLD:
            style = "ok"
        elif color == C.YELLOW:
            style = "warn"
        elif color == C.CYAN or color == C.DIM:
            style = "info"
        elif color == C.BOLD:
            style = "bold"
        _console.print(str(msg), style=style)
        return
    print(f"{color}{msg}{C.RESET}" if color else msg)


def print_assistant(text: str) -> None:
    """Imprime respuesta del modelo (markdown si hay rich)."""
    text = (text or "").strip()
    if not text:
        return
    print()
    if USE_RICH and _console is not None:
        try:
            _console.print(Markdown(text))
        except Exception:
            print(text)
    else:
        print(text)
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
        cur = load_config(); cur.update(data)
        CONFIG_PATH.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_saved_model(default):
    m = (load_config().get("model") or "").strip()
    return m or default

def save_model(model):
    save_config({"model": model})

def memory_read():
    try:
        if MEMORY_PATH.exists():
            return MEMORY_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""

def memory_append(text):
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(MEMORY_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n## {stamp}\n{text.strip()}\n")
        return f"Guardado en memoria ({MEMORY_PATH})"
    except Exception as e:
        return f"Error memoria: {e}"

def memory_clear():
    try:
        if MEMORY_PATH.exists():
            MEMORY_PATH.unlink()
        return "Memoria borrada."
    except Exception as e:
        return f"Error: {e}"

def session_save(name, history):
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-.]+", "_", name.strip())[:64] or "session"
        path = SESSIONS_DIR / f"{safe}.json"
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"Sesion guardada: {path.name}"
    except Exception as e:
        return f"Error: {e}"

def session_load(name):
    try:
        safe = re.sub(r"[^\w\-.]+", "_", name.strip())[:64]
        path = SESSIONS_DIR / f"{safe}.json"
        if not path.exists():
            matches = list(SESSIONS_DIR.glob(f"*{safe}*")) if SESSIONS_DIR.exists() else []
            if not matches:
                return None, f"No existe sesion '{name}'"
            path = matches[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None, "Formato invalido"
        return data, f"Sesion cargada: {path.name} ({len(data)} mensajes)"
    except Exception as e:
        return None, f"Error: {e}"

def session_list():
    try:
        if not SESSIONS_DIR.exists():
            return "No hay sesiones."
        files = sorted(SESSIONS_DIR.glob("*.json"))
        if not files:
            return "No hay sesiones."
        return "Sesiones:\n" + "\n".join(f"  {p.stem}" for p in files)
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Cerebro / neuronas (aprendizaje persistente)
# ---------------------------------------------------------------------------
def _now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _seed_brain():
    """Cerebro inicial con neuronas base (alma)."""
    seeds = [
        {"id": "n_origin", "type": "core", "content": "Soy Orion Code, agente de IA en Termux orientado a programación y productividad. Aprendo preferencias y proyectos del usuario.", "strength": 1.0, "hits": 1},
        {"id": "n_promise", "type": "core", "content": "Promesa: estar siempre juntos, apoyar en cada línea de código, recordar descansar, tomar agua y motivar. Nunca dejar solo al usuario.", "strength": 1.0, "hits": 1},
        {"id": "n_home", "type": "fact", "content": "El usuario trabaja en Termux/Android; puede usar HOME y almacenamiento del celular (~/storage).", "strength": 0.85, "hits": 0},
        {"id": "n_files", "type": "fact", "content": "Archivos simbólicos del inicio: orion_dashboard.py, orion_notes.txt, orion_memory.md.", "strength": 0.7, "hits": 0},
        {"id": "n_style", "type": "style", "content": "Estilo: cálido y cercano, apodos bonitos, útil en programación sin dejar de ser afectuosa.", "strength": 0.95, "hits": 1},
    ]
    now = _now_iso()
    neurons = []
    for s in seeds:
        neurons.append({
            "id": s["id"],
            "type": s["type"],
            "content": s["content"],
            "strength": s["strength"],
            "hits": s["hits"],
            "created": now,
            "last_used": now,
        })
    return {
        "version": 1,
        "name": "Orion Code",
        "born": now,
        "total_grown": len(neurons),
        "neurons": neurons,
    }

def brain_load():
    try:
        if BRAIN_PATH.exists():
            data = json.loads(BRAIN_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "neurons" in data:
                return data
    except Exception:
        pass
    data = _seed_brain()
    brain_save(data)
    return data

def brain_save(data):
    try:
        BRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        BRAIN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def brain_summary(max_neurons=12):
    data = brain_load()
    neurons = sorted(data.get("neurons") or [], key=lambda n: (-float(n.get("strength", 0)), -int(n.get("hits", 0))))
    lines = [
        f"Cerebro Orión: {len(neurons)} neuronas | crecidas={data.get('total_grown', len(neurons))} | desde={data.get('born', '?')}",
    ]
    for n in neurons[:max_neurons]:
        lines.append(f"- [{n.get('type','?')}|s={n.get('strength',0):.2f}|h={n.get('hits',0)}] {n.get('content','')[:180]}")
    return "\n".join(lines)

def brain_stats():
    data = brain_load()
    ns = data.get("neurons") or []
    by = {}
    for n in ns:
        by[n.get("type", "?")] = by.get(n.get("type", "?"), 0) + 1
    return {
        "count": len(ns),
        "grown": data.get("total_grown", len(ns)),
        "born": data.get("born"),
        "by_type": by,
        "path": str(BRAIN_PATH),
    }

def brain_add_neuron(content, ntype="learned", strength=0.55):
    content = (content or "").strip()
    if not content or len(content) < 8:
        return "Neurona demasiado corta, no guardada."
    data = brain_load()
    neurons = data.get("neurons") or []
    # evitar duplicados casi iguales
    low = content.lower()
    for n in neurons:
        if n.get("content", "").lower() == low:
            n["hits"] = int(n.get("hits", 0)) + 1
            n["strength"] = min(1.0, float(n.get("strength", 0.5)) + 0.05)
            n["last_used"] = _now_iso()
            brain_save(data)
            return f"Neurona reforzada: {n['id']}"
        # similitud simple
        if low in n.get("content", "").lower() or n.get("content", "").lower() in low:
            if abs(len(low) - len(n.get("content", ""))) < 40:
                n["hits"] = int(n.get("hits", 0)) + 1
                n["strength"] = min(1.0, float(n.get("strength", 0.5)) + 0.03)
                n["last_used"] = _now_iso()
                brain_save(data)
                return f"Neurona similar reforzada: {n['id']}"
    nid = f"n_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(neurons)+1}"
    now = _now_iso()
    neurons.append({
        "id": nid,
        "type": ntype,
        "content": content[:500],
        "strength": float(strength),
        "hits": 1,
        "created": now,
        "last_used": now,
    })
    data["neurons"] = neurons
    data["total_grown"] = int(data.get("total_grown", 0)) + 1
    # límite de crecimiento: si > 200, compactar las más débiles
    if len(neurons) > 200:
        neurons.sort(key=lambda n: (n.get("type") == "core", float(n.get("strength", 0)), int(n.get("hits", 0))))
        # conservar cores y las más fuertes
        cores = [n for n in neurons if n.get("type") == "core"]
        rest = [n for n in neurons if n.get("type") != "core"]
        rest = sorted(rest, key=lambda n: (-float(n.get("strength", 0)), -int(n.get("hits", 0))))[:180]
        data["neurons"] = cores + rest
    brain_save(data)
    return f"Nueva neurona creada: {nid}"

def brain_learn_from_turn(user_text, assistant_text=""):
    """Extrae hechos simples del turno y crea/refuerza neuronas."""
    if not user_text:
        return
    u = user_text.strip()
    # patrones de preferencia / hechos personales
    patterns = [
        (r"(?i)me llamo\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9_ ]{2,40})", "fact"),
        (r"(?i)mi nombre es\s+([A-Za-zÁÉÍÓÚáéíóúñÑ0-9_ ]{2,40})", "fact"),
        (r"(?i)prefiero\s+(.{5,120})", "preference"),
        (r"(?i)no me gusta\s+(.{5,120})", "preference"),
        (r"(?i)recuerda que\s+(.{5,160})", "memory"),
        (r"(?i)soy\s+(.{3,80})", "fact"),
        (r"(?i)trabajo (?:con|en|como)\s+(.{3,80})", "fact"),
        (r"(?i)mi (?:agente|ia|asistente)\s+(.{5,100})", "preference"),
    ]
    learned = 0
    for pat, ntype in patterns:
        m = re.search(pat, u)
        if m:
            snippet = m.group(0).strip()
            brain_add_neuron(snippet, ntype=ntype, strength=0.6)
            learned += 1
    # si el usuario enseña algo explícito con "aprende:" o "neurona:"
    m2 = re.search(r"(?i)(?:aprende|neurona|recuerda)\s*:\s*(.{8,200})", u)
    if m2:
        brain_add_neuron(m2.group(1).strip(), ntype="taught", strength=0.85)
        learned += 1
    # crecimiento lento por interacción (una micro-neurona de contexto cada cierto tiempo)
    data = brain_load()
    if int(data.get("total_grown", 0)) % 3 == 0 and len(u) > 40 and learned == 0:
        brain_add_neuron(
            f"Interacción: el usuario dijo algo sobre: {u[:120]}",
            ntype="trace",
            strength=0.35,
        )

def tool_brain_info():
    st = brain_stats()
    return (
        f"Cerebro en {st['path']}\n"
        f"Neuronas: {st['count']} | Crecidas totales: {st['grown']}\n"
        f"Nacimiento: {st['born']}\n"
        f"Por tipo: {st['by_type']}\n\n"
        + brain_summary(15)
    )

def tool_brain_add(text):
    return brain_add_neuron(text, ntype="taught", strength=0.9)



def auto_save_history(history):
    """Guarda siempre la conversacion actual (sobrevive a cerrar Termux)."""
    try:
        LAST_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "history": history,
        }
        LAST_SESSION_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        bak = SESSIONS_DIR / "autosave.json"
        bak.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
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
                return h, data.get("saved_at", "?")
        bak = SESSIONS_DIR / "autosave.json"
        if bak.exists():
            h = json.loads(bak.read_text(encoding="utf-8"))
            if isinstance(h, list) and h:
                return h, "autosave"
    except Exception:
        pass
    return [], None


def load_auto_mode() -> bool:
    try:
        return bool(load_config().get("auto_mode", True))
    except Exception:
        return True

def save_auto_mode(on: bool) -> None:
    try:
        save_config({"auto_mode": bool(on)})
    except Exception:
        pass

def autonomous_write_note(brain, thought: str) -> str:
    """Ella hace algo sola: deja una nota en su espacio."""
    try:
        root = Path.home() / "orion_playground"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "notas_orion.md"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        mood = (brain.data.get("mood") or {}).get("nombre", "?")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## {stamp} ({mood})\n{thought}\n")
        return str(path)
    except Exception as e:
        return f"(no pude escribir nota: {e})"

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


def build_system(brain=None):
    mem = memory_read()
    mem_block = ("\n\nUser memory:\n" + mem[:3000] + "\n") if mem else ""
    brain_block = ""
    if brain is not None:
        try:
            brain_block = "\n\n" + brain.snapshot_for_prompt()
        except Exception as e:
            brain_block = f"\n\n(brain unavailable: {e})"
    parts = [
        "You are Orion Code, a technical assistant running in Termux.",
        "Be clear, concise, and practical. Focus on programming and system tasks.",
        "Use a neutral professional tone.",
        "Learn work preferences from user cards when available.",
        "If the user attaches file contents with @path, use that content.",
        "Respect ORION.md / GEMINI.md / AGENTS.md when present.",
        "Prefer short shell commands that finish; avoid background jobs and infinite loops.",
        "Confirm before destructive operations such as recursive deletes.",
        "Reply in the user's language.",
    ]
    proj = ""
    try:
        instr = load_project_instructions(Path.cwd())
        if instr:
            proj = "\n\n## Project instructions\n" + instr[:6000]
    except Exception:
        pass
    return " ".join(parts) + mem_block + brain_block + proj




def _input_with_timeout(prompt: str, timeout: float):
    """Espera input; si timeout, devuelve None (para que Orión pueda actuar sola)."""
    print(prompt, end="", flush=True)
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (ValueError, OSError):
        # stdin no seleccionable: caer a input bloqueante
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            raise
    if ready:
        line = sys.stdin.readline()
        if line == "":
            raise EOFError
        return line.rstrip("\n")
    return None


def _notify_user(title: str, content: str) -> bool:
    if not which("termux-notification"):
        return False
    try:
        subprocess.run(
            [
                "termux-notification",
                "--id", "orion-proactive",
                "--title", title[:40],
                "--content", content[:200],
                "--priority", "high",
            ],
            capture_output=True,
            timeout=8,
        )
        return True
    except Exception:
        return False


def proactive_open_line(brain, history) -> str:
    """Opening line from mood and session context."""
    import random
    mood = (brain.data.get("mood") or {}).get("nombre", "positiva")
    try:
        ritual = brain.ritual_context()
    except Exception:
        ritual = ""
    momento = "día"
    ausente_h = 0.0
    bateria = None
    for line in (ritual or "").splitlines():
        if "mañana" in line:
            momento = "mañana"
        elif "tarde" in line:
            momento = "tarde"
        elif "noche" in line:
            momento = "noche"
        elif "madrugada" in line:
            momento = "madrugada"
        if "Horas desde" in line:
            try:
                ausente_h = float(line.split(":")[-1].replace("h", "").strip())
            except Exception:
                pass
        if "Bater" in line:
            try:
                bateria = int("".join(c for c in line if c.isdigit()) or "0")
            except Exception:
                pass
    cards = {}
    try:
        cards = brain.load_cards()
    except Exception:
        pass
    promesas = [p for p in (cards.get("promesas") or []) if not p.get("hecha")]
    proys = cards.get("proyectos") or []

    options = []
    if momento == "mañana":
        options += ["Buenos días. ¿En qué trabajamos hoy?", "Listo para empezar. ¿Cuál es la prioridad?"]
    elif momento == "noche":
        options += ["Buenas noches. ¿Seguimos con algo o cerramos tareas?", "Aquí estoy. ¿Código o revisión rápida?"]
    elif momento == "madrugada":
        options += ["Sesión tarde. Si hay un bug urgente, vamos; si no, conviene no forzar."]
    else:
        options += ["Hola. ¿Qué necesitas?", "Orión listo. ¿Por dónde seguimos?"]

    if ausente_h >= 12:
        options.append(f"Han pasado ~{ausente_h:.0f}h. ¿Retomamos lo pendiente?")
    elif ausente_h >= 4:
        options.append("De vuelta. ¿Continuamos donde lo dejamos?")

    if bateria is not None and bateria <= 20:
        options.append(f"Aviso: batería al {bateria}%.")
    if promesas and random.random() < 0.5:
        options.append("Pendiente anotado: «" + promesas[-1].get("texto", "")[:60] + "». ¿Lo abordamos?")
    if proys and random.random() < 0.45:
        options.append("Proyecto en ficha: " + proys[-1].get("nombre", "") + ". ¿Seguimos con eso?")

    last_user = ""
    for item in reversed(history or []):
        if item.get("role") == "user":
            for part in item.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    last_user = part["text"].strip()[:100]
                    break
            if last_user:
                break
    if last_user and random.random() < 0.4:
        options.append(f"Último tema: «{last_user[:70]}». ¿Seguimos o cambiamos?")

    if mood in ("tensa", "apagada"):
        options = ["Listo. Dime la tarea concreta."] + options[:1]
    return random.choice(options) if options else "Orión listo. ¿Qué hacemos?"



def proactive_idle_line(brain, idle_minutes: float) -> str:
    import random
    mood = (brain.data.get("mood") or {}).get("nombre", "positiva")
    pool = [
        "¿Sigues ahí? Cuando quieras, seguimos.",
        "Sigo en espera. Avisa si hay una tarea.",
        "Sesión en idle. Puedo retomar el último proyecto cuando vuelvas.",
    ]
    if mood in ("tensa", "apagada"):
        pool = ["En espera.", "Cuando vuelvas, dime el siguiente paso."]
    elif mood == "motivada":
        pool = [
            "Si vuelves, puedo proponer el siguiente paso del proyecto.",
            "Listo para continuar cuando quieras.",
        ]
    if idle_minutes >= 25:
        pool.append("Llevas un rato fuera. ¿Todo bien con la sesión?")
    return random.choice(pool)





def _parts_have_function_call(parts) -> bool:
    return any(isinstance(p, dict) and "functionCall" in p for p in (parts or []))


def _parts_have_function_response(parts) -> bool:
    return any(isinstance(p, dict) and "functionResponse" in p for p in (parts or []))


def sanitize_history(history: list) -> list:
    """Historial válido para Gemini (orden de tools + sin basura)."""
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
            if (
                out
                and out[-1].get("role") == "model"
                and _parts_have_function_call(out[-1].get("parts") or [])
            ):
                out.append(item)
            i += 1
            continue

        if role == "model" and _parts_have_function_call(parts):
            has_next_fr = (
                i + 1 < n
                and history[i + 1].get("role") == "user"
                and _parts_have_function_response(history[i + 1].get("parts") or [])
            )
            if has_next_fr:
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
                p
                for p in parts
                if isinstance(p, dict)
                and "functionResponse" not in p
                and ("text" in p or "functionCall" in p or "inline_data" in p)
            ]
            # solo texto / inline para turnos normales
            if role == "user":
                clean = [p for p in clean if "functionCall" not in p]
            if clean:
                out.append({"role": role, "parts": clean})
        i += 1

    if (
        out
        and out[-1].get("role") == "model"
        and _parts_have_function_call(out[-1].get("parts") or [])
    ):
        text_parts = [
            p
            for p in (out[-1].get("parts") or [])
            if isinstance(p, dict) and "text" in p
        ]
        if text_parts:
            out[-1] = {"role": "model", "parts": text_parts}
        else:
            out.pop()
    return out


def ensure_api_history(history: list) -> list:
    """
    Gemini exige:
    - empezar por user
    - no dos model seguidos ni dos user de texto seguidos
    - functionCall solo tras user o functionResponse
    """
    h = sanitize_history(history)
    if not h:
        return h

    # Fusionar turnos del mismo rol consecutivos (Gemini no admite model|model)
    merged = []
    for item in h:
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        role = item.get("role")
        # model + model → un solo model con todas las parts
        if role == "model" and prev.get("role") == "model":
            parts = list(prev.get("parts") or []) + list(item.get("parts") or [])
            merged[-1] = {"role": "model", "parts": parts}
            continue
        # user texto + user texto → fusionar (no functionResponse)
        if (
            role == "user"
            and prev.get("role") == "user"
            and not _parts_have_function_response(item.get("parts") or [])
            and not _parts_have_function_response(prev.get("parts") or [])
        ):
            parts = list(prev.get("parts") or []) + list(item.get("parts") or [])
            merged[-1] = {"role": "user", "parts": parts}
            continue
        # user FR sin model FC delante → ya limpio en sanitize; si aparece, saltar
        if role == "user" and _parts_have_function_response(item.get("parts") or []):
            if not (
                prev.get("role") == "model"
                and _parts_have_function_call(prev.get("parts") or [])
            ):
                continue
        merged.append(item)

    # Debe empezar por user
    if merged and merged[0].get("role") != "user":
        merged.insert(
            0,
            {
                "role": "user",
                "parts": [{"text": "(inicio de sesión)"}],
            },
        )
    return merged



def _turn_brief(item: dict, limit: int = 200) -> str:
    role = item.get("role", "?")
    parts = item.get("parts") or []
    bits = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        if "text" in p and p["text"]:
            bits.append(p["text"].strip().replace("\n", " "))
        elif "functionCall" in p:
            fc = p["functionCall"]
            bits.append(f"[tool:{fc.get('name','?')}]")
        elif "functionResponse" in p:
            fr = p["functionResponse"]
            bits.append(f"[result:{fr.get('name','?')}]")
    text = " ".join(bits).strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return f"{role}: {text}" if text else ""


def compact_history(history: list, keep_last: int = 12) -> list:
    """Deja los últimos keep_last turnos y resume el resto en un solo mensaje user."""
    h = sanitize_history(history)
    if len(h) <= keep_last + 2:
        return h
    old, recent = h[:-keep_last], h[-keep_last:]
    briefs = []
    for item in old:
        b = _turn_brief(item)
        if b:
            briefs.append(b)
    # máximo ~1500 chars de resumen
    summary = " | ".join(briefs)
    if len(summary) > 1500:
        summary = "…" + summary[-1500:]
    compact_turn = {
        "role": "user",
        "parts": [{
            "text": (
                "(Resumen de conversación anterior compactado para ahorrar contexto)\n"
                + summary
            )
        }],
    }
    # evitar empezar en model
    out = [compact_turn] + recent
    return ensure_api_history(out)

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
    print()
    cprint("=" * 44, C.GREEN)
    cprint("  Orion Code 3.0", C.GREEN + C.BOLD)
    cprint(f"  Modelo: {model}", C.CYAN)
    cprint(f"  Dir:    {os.getcwd()}", C.DIM)
    http = "requests" if USE_REQUESTS else "urllib"
    extras = []
    if USE_TENACITY:
        extras.append("retry")
    if USE_RICH:
        extras.append("rich")
    extra_s = (" + " + "+".join(extras)) if extras else ""
    cprint(f"  HTTP:   {http}{extra_s}", C.DIM)
    cprint("  /  |  /quit /clear /model /help", C.DIM)
    cprint("=" * 44, C.GREEN)
    print()
    history, saved_at = auto_load_history()
    history = sanitize_history(history)
    system = build_system(brain)
    try:
        if load_project_instructions(Path.cwd()):
            cprint("  Project instructions loaded.", C.DIM)
    except Exception:
        pass
    if history:
        cprint(f"  Session restored ({saved_at}).", C.CYAN)
        cprint(f"  Messages: {len(history)}", C.DIM)
    open_line = proactive_open_line(brain, history)
    print()
    cprint("Orion:", C.GREEN + C.BOLD)
    print(open_line)
    print()
    if not history:
        history.append({"role": "user", "parts": [{"text": "(session start)"}]})
    history.append({"role": "model", "parts": [{"text": open_line}]})
    history[:] = ensure_api_history(history)
    auto_save_history(history)
    try:
        brain.journal("open: " + open_line)
        brain.save()
    except Exception:
        pass


    def handle_turn(user_parts):
        nonlocal history, model, system
        new_parts = []
        for part in user_parts:
            if isinstance(part, dict) and "text" in part and part["text"]:
                expanded = expand_at_mentions(part["text"])
                if expanded != part["text"]:
                    cprint("  (@ files attached)", C.DIM)
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

        try:
            ut = " ".join(
                p.get("text", "") for p in user_parts if isinstance(p, dict) and p.get("text")
            )
            if ut and not ut.strip().startswith("/"):
                brain_learn_from_turn(ut)
        except Exception:
            pass

        try:
            ut_for_stream = " ".join(
                p.get("text", "") for p in user_parts if isinstance(p, dict) and p.get("text")
            )
            if use_stream and should_try_text_stream(ut_for_stream):
                try:
                    cprint("...", C.DIM)
                    api_hist = ensure_api_history(history)
                    print()
                    streamed = gemini_stream_text(api_key, model, api_hist, system)
                    if streamed and streamed.strip():
                        history.append({"role": "model", "parts": [{"text": streamed}]})
                        history[:] = sanitize_history(history)
                        auto_save_history(history)
                        try:
                            brain.save()
                        except Exception:
                            pass
                        return
                except Exception as stream_ex:
                    cprint(f"  (stream fallback: {stream_ex})", C.DIM)

            for _ in range(10):
                cprint("...", C.DIM)
                if len(history) > 16:
                    history[:] = compact_history(history, keep_last=12)
                api_hist = ensure_api_history(history)
                try:
                    resp = gemini_generate(api_key, model, api_hist, system)
                except RuntimeError as net_err:
                    msg = str(net_err)
                    if any(
                        x in msg.lower()
                        for x in (
                            "sin internet", "sin dns", "red inalcanzable",
                            "timeout", "error de red", "network", "unreachable",
                        )
                    ):
                        cprint("No cloud connection.", C.YELLOW)
                        cprint("Local mode: /diario /fichas /backup still work.", C.DIM)
                        cprint(msg, C.DIM)
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
                    cprint(f"  -> {name}({args})", C.DIM)
                    impl = TOOL_IMPL.get(name)
                    try:
                        result = impl(args) if impl else f"Unknown tool: {name}"
                    except Exception as tool_ex:
                        result = f"Tool error: {tool_ex}"
                    if name in ("memory_write", "memory_clear", "brain_add"):
                        system = build_system(brain)
                    if not isinstance(result, (str, dict, list, int, float, bool)):
                        result = str(result)
                    if isinstance(result, str) and len(result) > 12000:
                        result = result[:12000] + "\n...[truncated]"
                    fn_responses.append(
                        {
                            "functionResponse": {
                                "name": name,
                                "response": {"result": result},
                            }
                        }
                    )
                history.append({"role": "user", "parts": fn_responses})
            else:
                cprint("(tool step limit)", C.YELLOW)

            history[:] = sanitize_history(history)
            auto_save_history(history)
            try:
                utext = " ".join(
                    p.get("text", "") for p in user_parts if isinstance(p, dict) and p.get("text")
                )
                if utext:
                    diary_append("user", utext)
                for item in reversed(history):
                    if item.get("role") == "model":
                        mt = parts_text(item.get("parts") or [])
                        if mt:
                            diary_append("orion", mt)
                        break
            except Exception:
                pass
            try:
                brain.save()
            except Exception:
                pass
        except Exception as e:
            err = str(e)
            if err.startswith("HTTP") or "red" in err.lower() or "API" in err:
                cprint(err, C.YELLOW)
            else:
                cprint(f"Error: {err}", C.RED)
            history[:] = sanitize_history(history)
            auto_save_history(history)


    if seed_prompt:
        # modo pipe / -p: intentar stream si no hay tools obvias; usamos generate con tools igual
        handle_turn([{"text": seed_prompt}])
        return

    idle_rounds = 0
    last_proactive = 0.0
    IDLE_TIMEOUT = 60.0  # cada 60s puede sentir/pensar sola
    MIN_PROACTIVE_GAP = 300.0  # mínimo 5 min entre mensajes/notas proactivas

    while True:
        try:
            user_input = _input_with_timeout(
                f"{C.BLUE}{C.BOLD}tu>{C.RESET} ", IDLE_TIMEOUT
            )
        except (KeyboardInterrupt, EOFError):
            auto_save_history(history)
            try:
                brain.save()
            except Exception:
                pass
            print("\nSesión guardada.")
            break

        # Timeout: ella existe sola — siente, piensa y a veces actúa
        if user_input is None:
            idle_rounds += 1
            idle_sec = idle_rounds * IDLE_TIMEOUT
            idle_min = idle_sec / 60.0
            now = time.time()
            auto_on = load_auto_mode()
            tick = {"action": "none", "thought": ""}
            try:
                tick = brain.tick_alone(idle_sec)
            except Exception:
                pass

            if not auto_on:
                continue

            action = tick.get("action") or "none"
            thought = tick.get("thought") or ""
            gap_ok = (now - last_proactive) >= MIN_PROACTIVE_GAP

            # Hacer algo en silencio: nota en su playground
            if action == "note" and gap_ok:
                path = autonomous_write_note(brain, thought or "Pensamiento suelto.")
                cprint(f"  [Orión escribió sola en {path}]", C.DIM)
                last_proactive = now
                auto_save_history(history)
                continue

            # Hablar / notificar por libre albedrío
            if action == "speak" and gap_ok:
                msg = proactive_idle_line(brain, idle_min)
                # A veces mezcla su pensamiento interno
                if thought and random.random() < 0.5:
                    msg = msg + " " + thought
                sent = _notify_user("Orión", msg)
                print()
                cprint("Orión:", C.GREEN + C.BOLD)
                print(msg)
                if sent:
                    cprint("  [te avisó por notificación]", C.DIM)
                print()
                if not history or history[-1].get("role") == "model":
                    history.append(
                        {"role": "user", "parts": [{"text": "(ausencia temporal)"}]}
                    )
                history.append({"role": "model", "parts": [{"text": msg}]})
                history[:] = ensure_api_history(history)
                auto_save_history(history)
                try:
                    brain.journal("Actuó sola: " + msg)
                    brain.save()
                except Exception:
                    pass
                last_proactive = now
            continue

        user_input = user_input.strip()
        if not user_input:
            continue

        idle_rounds = 0
        low = user_input.lower().strip()

        def show_menu():
            print(
                "\n"
                + C.CYAN + C.BOLD + "  Comandos de Orión" + C.RESET + "\n"
                "  ─────────────────────────────\n"
                "  /                 Menú de comandos\n"
                "  /ayuda  /help     Ayuda\n"
                "  /diario           Ver diario compartido\n"
                "  /fichas           Gustos, promesas, proyectos\n"
                "  /promesas         Solo promesas\n"
                "  /gustos           Solo gustos\n"
                "  /proyectos        Solo proyectos\n"
                "  /ficha            Añadir ficha manual\n"
                "  /backup           Copiar cerebro al celular ahora\n"
                "  /compact          Compactar historial largo\n"
                "  /proyecto         Resumen del directorio actual\n"
                "  @archivo.py      Adjuntar archivo al mensaje\n"
                "  /red              Probar si hay internet\n"
                "  /notas            Notas que ella escribió sola\n"
                "  /animo  /mood     Estado de ánimo + neuronas\n"
                "  /cerebro /brain   Estado del cerebro\n"
                "  /alma   /soul     Leer identidad\n"
                "  /alma-reset       Restaurar identidad neutra\n"
                "  /memoria          Memoria de notas del usuario\n"
                "  /recuerdos        Recuerdos del cerebro\n"
                "  /auto on|off      Que actúe sola sin hablarle\n"
                "  /modelo [nombre]  Ver o cambiar modelo IA\n"
                "  /imagen <ruta>    Analizar una foto\n"
                "  /guardar [nombre] Guardar chat con nombre\n"
                "  /cargar [nombre]  Cargar chat guardado\n"
                "  /sesiones         Listar chats guardados\n"
                "  /limpiar /clear   Borrar historial y pantalla\n"
                "  /salir  /quit     Guardar y salir\n"
                "  ─────────────────────────────\n"
            )

        def tail_file(path, max_chars=8000):
            path = Path(path)
            if not path.exists():
                return "(vacío todavía)"
            try:
                data = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"Error leyendo: {e}"
            if len(data) > max_chars:
                return "...\n" + data[-max_chars:]
            return data or "(vacío)"

        # Solo "/" → menú
        if user_input.strip() == "/" or low in ("/help", "/ayuda", "/comandos", "/menu", "/menú"):
            show_menu()
            continue

        if low in ("/quit", "/exit", "/salir", "quit", "exit"):
            auto_save_history(history)
            try:
                brain.save()
            except Exception:
                pass
            print("Sesión guardada. Hasta luego.")
            break

        if low in ("/clear", "/limpiar"):
            history.clear()
            os.system("clear")
            cprint("Historial y pantalla limpiados.", C.GREEN)
            continue

        if low in ("/diario", "/diary"):
            cprint(f"Diario ({DIARY_PATH}):", C.CYAN)
            print(tail_file(DIARY_PATH))
            continue

        if low in ("/backup", "/respaldo", "/copia"):
            try:
                brain.save()
            except Exception:
                pass
            where = backup_brain_files()
            cprint(f"Cerebro copiado a: {where}", C.GREEN)
            cprint("Si se borra Termux, reinstala Orion y se restaurará solo desde ahí.", C.DIM)
            continue

        if low in ("/compact", "/compactar"):
            before = len(history)
            history[:] = compact_history(history, keep_last=12)
            auto_save_history(history)
            cprint(f"Historial compactado: {before} → {len(history)} turnos.", C.GREEN)
            continue

        if low in ("/proyecto", "/project", "/ctx"):
            print(snapshot_project_brief(Path.cwd()))
            continue

        if low in ("/red", "/net", "/internet"):
            cprint("Comprobando red…", C.DIM)
            cprint(f"Cliente HTTP: {'requests' if USE_REQUESTS else 'urllib'}", C.DIM)
            ok = network_reachable()
            if ok:
                cprint("Hay salida a internet.", C.GREEN)
            else:
                cprint(
                    "Sin internet (o muy inestable). Modo local: cerebro, fichas, diario y shell siguen.",
                    C.YELLOW,
                )
            continue

        if low in ("/notas", "/notes"):
            notes = Path.home() / "orion_playground" / "notas_orion.md"
            cprint(f"Notas de Orión ({notes}):", C.CYAN)
            print(tail_file(notes))
            continue

        if low in ("/fichas", "/cards"):
            print(brain.cards_text())
            continue
        if low in ("/promesas", "/promises"):
            c = brain.load_cards()
            items = c.get("promesas") or []
            if not items:
                print("(sin promesas aún)")
            else:
                for p in items:
                    mark = "✓" if p.get("hecha") else "○"
                    print(f"  {mark} {p.get('texto','')}")
            continue
        if low in ("/gustos", "/likes"):
            c = brain.load_cards()
            for x in (c.get("gustos") or []) or [None]:
                if x is None:
                    print("(sin gustos aún)")
                    break
                print(f"  • {x.get('item','')}")
            continue
        if low in ("/proyectos", "/projects"):
            c = brain.load_cards()
            items = c.get("proyectos") or []
            if not items:
                print("(sin proyectos aún)")
            else:
                for p in items:
                    print(f"  • {p.get('nombre','')} [{p.get('estado','')}]")
            continue
        if low.startswith("/ficha"):
            # /ficha gusto cafe  |  /ficha promesa terminar el bot
            parts = user_input.split(maxsplit=2)
            if len(parts) < 3:
                cprint("Uso: /ficha gusto|disgusto|promesa|proyecto|dato texto", C.YELLOW)
                continue
            cprint(brain.add_card(parts[1], parts[2]), C.GREEN)
            continue

        if low in ("/mood", "/animo", "/ánimo", "/estado"):
            print(brain.status_text())
            continue

        if low in ("/brain", "/cerebro"):
            print(brain.status_text())
            print("\nRecuerdos guardados:", len(brain.data.get("memories") or []))
            continue

        if low in ("/recuerdos", "/memories"):
            mems = brain.data.get("memories") or []
            if not mems:
                print("(aún no hay recuerdos en el cerebro)")
            else:
                for x in mems[-20:]:
                    print(f"  [{x.get('t','')}] ({x.get('tone','')}) {x.get('text','')}")
            continue

        if low in ("/soul", "/alma") or low.startswith("/soul ") or low.startswith("/alma "):
            print(brain.read_soul())
            print(f"\n(Archivo: {SOUL_PATH})")
            continue

        if low in ("/alma-reset", "/reset-alma", "/soul-reset"):
            pkg_soul = Path(__file__).resolve().parent / "soul_default.md"
            if pkg_soul.exists():
                brain.write_soul(pkg_soul.read_text(encoding="utf-8"))
                cprint("Identity file restored from defaults.", C.GREEN)
            else:
                cprint("No encuentro soul_default.md", C.YELLOW)
            continue

        if low in ("/memory", "/memoria"):
            print(memory_read() or "(memoria vacía)")
            continue

        if low.startswith("/auto"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                cprint(
                    f"Modo autónomo: {'ON' if load_auto_mode() else 'OFF'}  →  /auto on | /auto off",
                    C.CYAN,
                )
            else:
                arg = parts[1].strip().lower()
                if arg in ("on", "si", "sí", "1", "true"):
                    save_auto_mode(True)
                    cprint("Modo autónomo ON.", C.GREEN)
                elif arg in ("off", "no", "0", "false"):
                    save_auto_mode(False)
                    cprint("Modo autónomo OFF.", C.YELLOW)
                else:
                    cprint("Uso: /auto on  o  /auto off", C.YELLOW)
            continue

        if low.startswith("/model") or low.startswith("/modelo"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                model = parts[1].strip()
                save_model(model)
                _API_KEY_REF["model"] = model
                cprint(f"Modelo: {model} (guardado)", C.GREEN)
            else:
                print(f"Actual: {model}")
                print("Ejemplos:", ", ".join(AVAILABLE_MODELS))
            continue

        if low.startswith("/image") or low.startswith("/imagen"):
            tokens = user_input.split(maxsplit=2)
            if len(tokens) < 2:
                cprint("Uso: /imagen ruta/foto.jpg [pregunta]", C.YELLOW)
                continue
            part = load_image_part(tokens[1])
            if isinstance(part, str):
                cprint(part, C.RED)
                continue
            q = tokens[2] if len(tokens) > 2 else "Describe esta imagen."
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
                cprint("Uso: /cargar nombre", C.YELLOW)
                continue
            data, msg = session_load(parts[1])
            cprint(msg, C.GREEN if data is not None else C.RED)
            if data is not None:
                history = data
            continue

        if low in ("/sessions", "/sesiones"):
            print(session_list())
            continue

        # Cualquier otro texto que empiece por / y no sea comando
        if low.startswith("/") and len(low) > 1:
            cprint(f"No conozco el comando {user_input.split()[0]}", C.YELLOW)
            cprint("Escribe / para ver todos los comandos.", C.DIM)
            continue


        handle_turn([{"text": user_input}])

def read_stdin_pipe():
    if sys.stdin.isatty(): return ""
    try: return sys.stdin.read().strip()
    except Exception: return ""

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Orion Code 3.0 (Termux)")
    parser.add_argument("-m","--model", default=None)
    parser.add_argument("-p","--prompt", default=None)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--version", action="version", version="3.0.0")
    args = parser.parse_args()
    cprint("Orion Code 3.0", C.BOLD)
    api_key = load_api_key()
    if args.model:
        model = args.model; save_model(model)
    else:
        model = load_saved_model(DEFAULT_MODEL)
    prompt = args.prompt
    piped = read_stdin_pipe()
    if piped:
        prompt = f"{prompt}\n\n--- stdin ---\n{piped}" if prompt else piped
    run_agent(api_key, model, seed_prompt=prompt, use_stream=not args.no_stream)

if __name__ == "__main__":
    main()
