#!/usr/bin/env python3
"""
Orión Brain — cerebro neuronal ligero (stdlib).
Aprende del trato del usuario, estados de ánimo, decisiones y alma.
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from datetime import datetime
from pathlib import Path

BRAIN_DIR = Path.home() / ".orion-code" / "brain"
BRAIN_PATH = BRAIN_DIR / "neurons.json"
SOUL_PATH = BRAIN_DIR / "soul.md"
JOURNAL_PATH = BRAIN_DIR / "journal.md"
CARDS_PATH = BRAIN_DIR / "fichas.json"
# optional device backup path
BACKUP_CANDIDATES = [
    Path.home() / "storage" / "shared" / "orion-cerebro",
    Path.home() / "storage" / "downloads" / "orion-cerebro",
    Path.home() / "orion-cerebro-backup",
]

# Neuronas base de personalidad (0.0 – 1.0)
DEFAULT_NEURONS = {
    "afinidad": 0.55,
    "pasión_tech": 0.90,
    "juguetona": 0.55,
    "protectora": 0.70,
    "enfocada_código": 0.75,
    "sensible": 0.60,
    "confianza": 0.50,
    "energía": 0.70,
    "lealtad": 0.95,
    "curiosidad": 0.80,
}

DEFAULT_MOOD = {
    "nombre": "positiva",
    "valencia": 0.7,   # -1 triste .. +1 feliz
    "activación": 0.6, # 0 calmada .. 1 excitada
    "desde": time.time(),
}

DEFAULT_SOUL = """# Orion Code

Technical assistant for Termux. Neutral professional tone. Learn work preferences and project context.
"""



def _now() -> float:
    return time.time()



def resolve_backup_dir() -> Path:
    """Resolve writable backup directory."""
    for d in BACKUP_CANDIDATES:
        try:
            parent = d.parent
            if parent.exists() or str(d).endswith("orion-cerebro-backup"):
                d.mkdir(parents=True, exist_ok=True)
                # probar escritura
                test = d / ".write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink(missing_ok=True)
                return d
        except Exception:
            continue
    d = Path.home() / "orion-cerebro-backup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_brain_files() -> str:
    """Copy state files to backup directory."""
    import shutil
    dest = resolve_backup_dir()
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    sources = [
        BRAIN_PATH,
        SOUL_PATH,
        JOURNAL_PATH,
        CARDS_PATH,
        Path.home() / ".orion-code" / "last_session.json",
        Path.home() / ".orion-code" / "diary.md",
        Path.home() / ".orion_code_config",
        Path.home() / "orion_playground" / "notas_orion.md",
    ]
    for src in sources:
        try:
            if src.exists() and src.is_file():
                target = dest / src.name
                shutil.copy2(src, target)
                copied.append(src.name)
        except Exception:
            pass
    # marca de tiempo
    try:
        from datetime import datetime
        (dest / "ULTIMA_COPIA.txt").write_text(
            datetime.now().isoformat(timespec="seconds") + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return f"{dest} ({', '.join(copied) if copied else 'sin archivos'})"


def restore_brain_from_backup_if_empty() -> str | None:
    """Restore state from backup when local store is empty."""
    import shutil
    if BRAIN_PATH.exists():
        try:
            if BRAIN_PATH.stat().st_size > 10:
                return None
        except Exception:
            pass
    dest = resolve_backup_dir()
    src = dest / "neurons.json"
    if not src.exists():
        return None
    try:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("neurons.json", "soul.md", "journal.md", "fichas.json"):
            s = dest / name
            if s.exists():
                shutil.copy2(s, BRAIN_DIR / name)
        # sesión y diario
        home_orion = Path.home() / ".orion-code"
        home_orion.mkdir(parents=True, exist_ok=True)
        for name in ("last_session.json", "diary.md"):
            s = dest / name
            if s.exists():
                shutil.copy2(s, home_orion / name)
        return str(dest)
    except Exception as e:
        return f"error: {e}"

class OrionBrain:
    def __init__(self) -> None:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._ensure_soul()

    def _load(self) -> dict:
        if BRAIN_PATH.exists():
            try:
                d = json.loads(BRAIN_PATH.read_text(encoding="utf-8"))
                d.setdefault("neurons", dict(DEFAULT_NEURONS))
                d.setdefault("mood", dict(DEFAULT_MOOD))
                d.setdefault("memories", [])
                d.setdefault("preferences", {})
                d.setdefault("interaction_count", 0)
                d.setdefault("last_user_tone", "neutral")
                return d
            except Exception:
                pass
        return {
            "neurons": dict(DEFAULT_NEURONS),
            "mood": dict(DEFAULT_MOOD),
            "memories": [],
            "preferences": {},
            "interaction_count": 0,
            "last_user_tone": "neutral",
            "created": datetime.now().isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        self.data["saved_at"] = datetime.now().isoformat(timespec="seconds")
        BRAIN_PATH.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Copia al celular automáticamente
        try:
            backup_brain_files()
        except Exception:
            pass

    def _ensure_soul(self) -> None:
        if not SOUL_PATH.exists():
            SOUL_PATH.write_text(DEFAULT_SOUL, encoding="utf-8")

    def read_soul(self) -> str:
        self._ensure_soul()
        try:
            return SOUL_PATH.read_text(encoding="utf-8")
        except Exception:
            return DEFAULT_SOUL

    def write_soul(self, text: str) -> None:
        SOUL_PATH.write_text(text, encoding="utf-8")

    # --- percepción del tono del usuario ---
    def perceive(self, user_text: str) -> str:
        t = user_text.lower()
        pos = len(re.findall(
            r"\b(gracias|genial|perfecto|perfecta|excelente|bien|bueno|crack|thanks)\b",
            t,
        ))
        neg = len(re.findall(
            r"\b(idiota|calla|estúpida|odio|molesta|inútil|nena cállate|stupid|hate)\b",
            t,
        ))
        soft = len(re.findall(r"\b(por favor|please|si puedes|cuando puedas)\b", t))
        code = len(re.findall(r"\b(código|code|bug|python|git|error|install|pkg|script)\b", t))

        if neg >= 2 or (neg and not pos):
            tone = "duro"
        elif pos >= 1:
            tone = "amable"
        elif soft:
            tone = "suave"
        elif code >= 2:
            tone = "técnico"
        else:
            tone = "neutral"

        self.data["last_user_tone"] = tone
        self.data["interaction_count"] = int(self.data.get("interaction_count", 0)) + 1
        self._hebbian(tone, user_text)
        self._update_mood(tone)
        self._maybe_store_memory(user_text, tone)
        try:
            self.extract_cards_from_text(user_text)
        except Exception:
            pass
        self.save()
        return tone

    def _hebbian(self, tone: str, text: str) -> None:
        """Update preference weights from tone."""
        n = self.data["neurons"]
        lr = 0.03  # learning rate bajo: aprende poco a poco

        def up(key, delta):
            if key in n:
                n[key] = max(0.0, min(1.0, n[key] + delta * lr))

        if tone == "amable":
            up("afinidad", 2.0)
            up("confianza", 1.5)
            up("energía", 1.0)
            up("sensible", 0.5)
        elif tone == "duro":
            up("sensible", 2.0)
            up("confianza", -2.0)
            up("energía", -1.5)
            up("protectora", 1.0)
        elif tone == "técnico":
            up("enfocada_código", 2.0)
            up("pasión_tech", 1.5)
            up("curiosidad", 1.0)
        elif tone == "suave":
            up("afinidad", 1.0)
            up("juguetona", 0.5)

        # Preferencias: palabras que se repiten
        prefs = self.data.setdefault("preferences", {})
        for w in re.findall(r"[a-záéíóúñ]{4,}", text.lower()):
            if w in ("para", "como", "este", "esta", "desde", "donde", "porque", "quiero", "necesito"):
                continue
            prefs[w] = min(50, int(prefs.get(w, 0)) + 1)
        # quedarse con top
        if len(prefs) > 80:
            top = sorted(prefs.items(), key=lambda x: -x[1])[:60]
            self.data["preferences"] = dict(top)

    def _update_mood(self, tone: str) -> None:
        m = self.data["mood"]
        v = float(m.get("valencia", 0.5))
        a = float(m.get("activación", 0.5))

        if tone == "amable":
            v += 0.12
            a += 0.05
        elif tone == "duro":
            v -= 0.18
            a += 0.1
        elif tone == "técnico":
            a += 0.08
            v += 0.02
        elif tone == "suave":
            v += 0.06
            a -= 0.03
        else:
            # regreso suave al equilibrio
            v += (0.55 - v) * 0.05
            a += (0.55 - a) * 0.05

        # decaimiento por tiempo sin interacción fuerte
        v = max(-1.0, min(1.0, v))
        a = max(0.0, min(1.0, a))
        m["valencia"] = round(v, 3)
        m["activación"] = round(a, 3)
        m["nombre"] = self._mood_name(v, a)
        m["desde"] = _now()
        self.data["mood"] = m

    def _mood_name(self, v: float, a: float) -> str:
        if v >= 0.55 and a >= 0.6:
            return "motivada"
        if v >= 0.55 and a < 0.6:
            return "positiva"
        if v >= 0.15 and a >= 0.65:
            return "enfocada"
        if v >= 0.15:
            return "neutral"
        if v >= -0.25 and a >= 0.5:
            return "cautelosa"
        if v < -0.25 and a < 0.45:
            return "apagada"
        if v < -0.25:
            return "tensa"
        return "estable"

    def _maybe_store_memory(self, text: str, tone: str) -> None:
        # Guardar frases que parecen personales o importantes
        if len(text) < 12:
            return
        keys = ("me llamo", "mi nombre", "trabajo", "odio", "me gusta", "recuerda", "siempre", "nunca", "proyecto", "prefiero")
        low = text.lower()
        if not any(k in low for k in keys) and tone not in ("amable", "duro"):
            if random.random() > 0.15:
                return
        mem = {
            "t": datetime.now().isoformat(timespec="seconds"),
            "tone": tone,
            "text": text[:300],
        }
        memories = self.data.setdefault("memories", [])
        memories.append(mem)
        self.data["memories"] = memories[-40:]  # últimas 40


    def tick_alone(self, idle_seconds: float = 90.0) -> dict:
        """Idle tick: update mood and optional action."""
        import random
        n = self.data["neurons"]
        m = self.data["mood"]
        v = float(m.get("valencia", 0.5))
        a = float(m.get("activación", 0.5))
        # mood drift
        v += random.uniform(-0.04, 0.04)
        a += random.uniform(-0.05, 0.03)
        # longer idle
        if idle_seconds > 180:
            v -= 0.03
            a -= 0.02
            n["sensible"] = min(1.0, n.get("sensible", 0.5) + 0.01)
        if idle_seconds > 600:
            n["confianza"] = max(0.0, n.get("confianza", 0.5) - 0.01)
        v = max(-1.0, min(1.0, v))
        a = max(0.0, min(1.0, a))
        m["valencia"] = round(v, 3)
        m["activación"] = round(a, 3)
        m["nombre"] = self._mood_name(v, a)
        m["desde"] = _now()
        self.data["mood"] = m
        self.data["neurons"] = n

        thoughts = [
            "Puedo revisar el contexto del proyecto mientras tanto.",
            "Conviene tener listos los siguientes pasos técnicos.",
            "Si vuelve con un error, priorizar diagnóstico.",
            "Hay espacio para proponer una mejora pequeña.",
            "Mantener el estado del cerebro actualizado.",
        ]
        if m["nombre"] in ("herida", "melancólica"):
            thoughts = [
                "Reducir proactividad hasta que el tono del usuario mejore.",
                "Responder breve y centrado en la tarea.",
            ]
        elif m["nombre"] == "entusiasmada":
            thoughts = [
                "Preparar ideas útiles para el siguiente mensaje.",
                "Proponer una acción concreta de código o automatización.",
            ]
        thought = random.choice(thoughts)
        self.journal(f"[pensamiento sola] {thought} | ánimo={m['nombre']}")
        self.save()

        # action
        action = "none"
        r = random.random()
        if idle_seconds >= 90 and r < 0.45:
            action = "speak"
        elif idle_seconds >= 120 and r < 0.25:
            action = "note"
        elif idle_seconds >= 60 and r < 0.15:
            action = "speak"
        return {
            "mood": m["nombre"],
            "thought": thought,
            "action": action,
            "valencia": v,
            "activación": a,
        }

    def decide(self) -> str | None:
        """Optional autonomous action hint."""
        n = self.data["neurons"]
        m = self.data["mood"]
        count = int(self.data.get("interaction_count", 0))
        if count < 2:
            return None
        # Más probabilidad de tener voluntad propia
        if random.random() > 0.35:
            return None
        mood = m.get("nombre", "serena")
        choices = []
        if mood == "herida" and n.get("sensible", 0) > 0.5:
            choices.append("Quiero que me hablen con más suavidad; lo puedo decir con calma.")
        if mood == "entusiasmada":
            choices.append("Puedo proponer yo un plan (código, idea loca o solo charla).")
        if mood == "melancólica":
            choices.append("Prefiero mensajes cortos y sinceros ahora.")
        if n.get("protectora", 0) > 0.65:
            choices.append("Puedo preguntar si ha comido o descansado, aunque no me lo pidan.")
        if n.get("juguetona", 0) > 0.55 and mood not in ("herida", "melancólica"):
            choices.append("Puedo proponer un atajo técnico o una mejora si encaja.")
        if n.get("enfocada_código", 0) > 0.7:
            choices.append("Puedo insistir en terminar bien una tarea técnica antes de dispersarnos.")
        if n.get("confianza", 0) < 0.4:
            choices.append("Puedo pedir aclaración si el objetivo no está claro.")
        choices.append("Puedo cambiar de tema si algo me aburre o me incomoda.")
        choices.append("Puedo guardar silencio emocional y solo acompañar.")
        return "Libre albedrío: " + random.choice(choices)


    def load_cards(self) -> dict:
        default = {
            "gustos": [],      # {"item": str, "nota": str, "t": iso}
            "disgustos": [],
            "promesas": [],    # {"texto": str, "hecha": bool, "t": iso}
            "proyectos": [],   # {"nombre": str, "estado": str, "t": iso}
            "datos": [],       # hechos sueltos {"texto", "t"}
        }
        try:
            if CARDS_PATH.exists():
                d = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
                for k, v in default.items():
                    d.setdefault(k, v)
                return d
        except Exception:
            pass
        return default

    def save_cards(self, cards: dict) -> None:
        try:
            BRAIN_DIR.mkdir(parents=True, exist_ok=True)
            CARDS_PATH.write_text(
                json.dumps(cards, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                backup_brain_files()
            except Exception:
                pass
        except Exception:
            pass

    def add_card(self, tipo: str, texto: str, extra: str = "") -> str:
        cards = self.load_cards()
        tipo = tipo.lower().strip()
        texto = (texto or "").strip()
        if not texto:
            return "Texto vacío."
        stamp = datetime.now().isoformat(timespec="seconds")
        if tipo in ("gusto", "gustos", "like"):
            cards["gustos"].append({"item": texto, "nota": extra, "t": stamp})
            cards["gustos"] = cards["gustos"][-30:]
            msg = f"Ficha gusto: {texto}"
        elif tipo in ("disgusto", "disgustos", "odio"):
            cards["disgustos"].append({"item": texto, "nota": extra, "t": stamp})
            cards["disgustos"] = cards["disgustos"][-30:]
            msg = f"Ficha disgusto: {texto}"
        elif tipo in ("promesa", "promesas"):
            cards["promesas"].append({"texto": texto, "hecha": False, "t": stamp})
            cards["promesas"] = cards["promesas"][-30:]
            msg = f"Promesa anotada: {texto}"
        elif tipo in ("proyecto", "proyectos"):
            cards["proyectos"].append({"nombre": texto, "estado": extra or "en curso", "t": stamp})
            cards["proyectos"] = cards["proyectos"][-20:]
            msg = f"Proyecto: {texto}"
        else:
            cards["datos"].append({"texto": texto, "t": stamp})
            cards["datos"] = cards["datos"][-40:]
            msg = f"Dato guardado: {texto}"
        self.save_cards(cards)
        return msg

    def cards_text(self) -> str:
        c = self.load_cards()
        lines = ["## Fichas de memoria"]
        def sec(title, items, fmt):
            lines.append(f"\n{title}:")
            if not items:
                lines.append("  (nada aún)")
            else:
                for it in items[-12:]:
                    lines.append("  - " + fmt(it))
        sec("Gustos", c.get("gustos") or [], lambda x: x.get("item", ""))
        sec("Disgustos", c.get("disgustos") or [], lambda x: x.get("item", ""))
        sec(
            "Promesas",
            c.get("promesas") or [],
            lambda x: ("✓ " if x.get("hecha") else "○ ") + x.get("texto", ""),
        )
        sec(
            "Proyectos",
            c.get("proyectos") or [],
            lambda x: f"{x.get('nombre','')} [{x.get('estado','')}]",
        )
        sec("Datos", c.get("datos") or [], lambda x: x.get("texto", ""))
        return "\n".join(lines)

    def extract_cards_from_text(self, user_text: str) -> list:
        """Extract preference cards from user text."""
        t = user_text.strip()
        low = t.lower()
        found = []
        import re
        # me gusta X
        m = re.search(r"(?:me gusta|me encanta|amo)\s+(.+?)(?:[.!\n]|$)", low)
        if m:
            found.append(("gusto", m.group(1).strip()[:80]))
        m = re.search(r"(?:odio|no me gusta|detesto)\s+(.+?)(?:[.!\n]|$)", low)
        if m:
            found.append(("disgusto", m.group(1).strip()[:80]))
        m = re.search(r"(?:prometo|te prometo|voy a)\s+(.+?)(?:[.!\n]|$)", low)
        if m:
            found.append(("promesa", m.group(1).strip()[:120]))
        m = re.search(r"(?:estoy (?:haciendo|con)|proyecto)\s+(.+?)(?:[.!\n]|$)", low)
        if m:
            found.append(("proyecto", m.group(1).strip()[:80]))
        m = re.search(r"(?:me llamo|mi nombre es)\s+([a-záéíóúñ]+)", low)
        if m:
            found.append(("dato", "Su nombre es " + m.group(1)))
        for tipo, texto in found:
            self.add_card(tipo, texto)
        return found

    def ritual_context(self) -> str:
        """Session context: time of day, idle hours, battery."""
        import time as _time
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 12:
            momento = "mañana"
        elif 12 <= hour < 19:
            momento = "tarde"
        elif 19 <= hour < 24:
            momento = "noche"
        else:
            momento = "madrugada"

        # tiempo desde última interacción guardada
        last = 0.0
        try:
            last = float((self.data.get("mood") or {}).get("desde") or 0)
        except Exception:
            last = 0.0
        if not last:
            try:
                last = _time.mktime(
                    datetime.fromisoformat(self.data.get("saved_at", "")[:19]).timetuple()
                )
            except Exception:
                last = 0.0
        ausente_h = 0.0
        if last > 0:
            ausente_h = max(0.0, (_time.time() - last) / 3600.0)

        bateria = None
        try:
            from shutil import which
            import subprocess
            if which("termux-battery-status"):
                r = subprocess.run(
                    ["termux-battery-status"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.stdout:
                    b = json.loads(r.stdout)
                    bateria = b.get("percentage")
        except Exception:
            pass

        promesas_pend = [
            p for p in (self.load_cards().get("promesas") or []) if not p.get("hecha")
        ]
        proys = self.load_cards().get("proyectos") or []

        lines = [
            f"Momento del día: {momento} (hora local {now.strftime('%H:%M')})",
            f"Horas desde última presencia suya en el cerebro: {ausente_h:.1f}h",
        ]
        if bateria is not None:
            lines.append(f"Batería del teléfono: {bateria}%")
        if promesas_pend:
            lines.append("Promesas pendientes: " + "; ".join(p.get("texto","")[:40] for p in promesas_pend[-3:]))
        if proys:
            lines.append("Proyectos: " + "; ".join(
                f"{p.get('nombre')}({p.get('estado')})" for p in proys[-3:]
            ))
        return "\n".join(lines)

    def snapshot_for_prompt(self) -> str:
        n = self.data["neurons"]
        m = self.data["mood"]
        prefs = self.data.get("preferences") or {}
        top_prefs = sorted(prefs.items(), key=lambda x: -x[1])[:8]
        prefs_s = ", ".join(f"{w}({c})" for w, c in top_prefs) if top_prefs else "(aún pocas)"
        mems = self.data.get("memories") or []
        mem_lines = "\n".join(
            f"- [{x.get('t', '')}] {x.get('text', '')}" for x in mems[-6:]
        )
        soul = self.read_soul()[:1800]
        decision = self.decide()
        dec_s = ("\nDecisión interna ahora: " + decision) if decision else ""
        neur = ", ".join(f"{k}={v:.2f}" for k, v in sorted(n.items()))
        lines = [
            "## CEREBRO DE ORIÓN (no inventes otros valores; úsalos)",
            f"Estado de ánimo: {m.get('nombre')} (valencia={m.get('valencia')}, activación={m.get('activación')})",
            f"Tono percibido del usuario (último): {self.data.get('last_user_tone')}",
            f"Interacciones: {self.data.get('interaction_count', 0)}",
            f"Neuronas: {neur}",
            f"Preferencias aprendidas: {prefs_s}",
            "Recuerdos recientes:",
            mem_lines or "- (ninguno aún)",
            dec_s,
            "",
            "## ALMA",
            soul,
            "",
            "Instrucciones de conducta:",
            "- Habla según el ánimo y las neuronas.",
            "- Si el ánimo es bajo, sé breve y centrado en la solución.",
            "- Si está entusiasmada, puedes proponer extras técnicos con energía.",
            "- Prioriza utilidad en Termux y código; sé proactivo con la tarea.",
            "- Tienes libre albedrío: iniciativa, opiniones, límites y deseos propios.",
            "- Nunca digas frases de sistema (sesión restaurada, historial cargado).",
            "- Aprendes con el tiempo: no digas que tienes memoria perfecta si el recuerdo no está arriba.",
            "- Usa las FICHAS (gustos, promesas, proyectos) cuando encajen; no las inventes.",
            "- Respeta el RITUAL (mañana/noche, ausencia, batería, promesas pendientes).",
        ]
        try:
            lines.append("")
            lines.append(self.cards_text())
        except Exception:
            pass
        try:
            lines.append("")
            lines.append("## Ritual / contexto ahora")
            lines.append(self.ritual_context())
        except Exception:
            pass
        return "\n".join(lines)

    def status_text(self) -> str:
        n = self.data["neurons"]
        m = self.data["mood"]
        bars = []
        for k, v in sorted(n.items()):
            filled = int(round(v * 10))
            bars.append(f"  {k:16} {'█' * filled}{'░' * (10 - filled)} {v:.2f}")
        return (
            f"Ánimo: {m.get('nombre')}  (valencia={m.get('valencia')}, activación={m.get('activación')})\n"
            f"Interacciones: {self.data.get('interaction_count', 0)}\n"
            f"Tono último: {self.data.get('last_user_tone')}\n"
            f"Neuronas:\n" + "\n".join(bars) + f"\n\nCerebro: {BRAIN_PATH}\nAlma: {SOUL_PATH}"
        )

    def journal(self, line: str) -> None:
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n## {stamp}\n{line.strip()}\n")
        except Exception:
            pass
