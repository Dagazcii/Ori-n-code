#!/usr/bin/env python3
"""Orión Dashboard v1.1 — panel que LEE el cerebro, no lo duplica."""
import os
import sys
import platform
import subprocess
import datetime
import shutil
import json
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from orion_brain import OrionBrain, BRAIN_PATH, SOUL_PATH, CARDS_PATH
except ImportError:
    OrionBrain = None


def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')


def get_battery():
    try:
        res = subprocess.run(['termux-battery-status'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            return f"{data.get('percentage', 'N/A')}% ({data.get('status', 'N/A')})"
    except Exception:
        pass
    return "No disponible (¿termux-api instalado?)"


def get_storage():
    try:
        total, used, free = shutil.disk_usage("/")
        return {
            "total": f"{total // (2**30)} GB",
            "used": f"{used // (2**30)} GB",
            "free": f"{free // (2**30)} GB",
        }
    except Exception:
        return {"total": "?", "used": "?", "free": "?"}


def show_banner():
    print("\033[1;36m" + "=" * 50)
    print("      🚀 ORION CODE - DASHBOARD v1.1")
    print("=" * 50 + "\033[0m")


def show_brain(brain):
    if brain is None:
        print("\n(cerebro no disponible: falta orion_brain.py)")
        return
    try:
        print("\n\033[1;35m[ Estado del cerebro ]\033[0m")
        print(brain.status_text())
        print("\n\033[1;35m[ Fichas ]\033[0m")
        print(brain.cards_text())
    except Exception as e:
        print(f"(error leyendo cerebro: {e})")


def main_menu():
    brain = OrionBrain() if OrionBrain else None
    while True:
        clear_screen()
        show_banner()

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"📅 Fecha/Hora: \033[1;33m{now}\033[0m")
        print(f"💻 Sistema: \033[1;32m{platform.system()} {platform.machine()} ({platform.release()})\033[0m")
        print(f"🔋 Batería: \033[1;33m{get_battery()}\033[0m")

        storage = get_storage()
        print(f"💾 Almacenamiento raíz: Usado {storage['used']} / Libre {storage['free']} (Total {storage['total']})")

        print("\n\033[1;35m[ Menú Principal ]\033[0m")
        print("1. Ver información detallada del sistema")
        print("2. Listar archivos del directorio actual")
        print("3. Comprobar conexión a Internet (Ping)")
        print("4. Ver estado del cerebro y fichas de Orión")
        print("5. Ver diario compartido (~/.orion-code/diary.md)")
        print("6. Abrir Orión Code (agente)")
        print("7. Salir")

        choice = input("\n\033[1;34mElige una opción (1-7): \033[0m").strip()

        if choice == '1':
            print("\n--- DETALLES DEL SISTEMA ---")
            os.system("uname -a && uptime")
            input("\nPresiona Enter para continuar...")
        elif choice == '2':
            print("\n--- ARCHIVOS EN DIRECTORIO ACTUAL ---")
            for f in os.listdir('.'):
                print(f" - {f}")
            input("\nPresiona Enter para continuar...")
        elif choice == '3':
            print("\n--- COMPROBANDO CONEXIÓN ---")
            res = os.system("ping -c 3 8.8.8.8")
            if res != 0:
                print("\n⚠️ Sin conexión o ping bloqueado.")
            input("\nPresiona Enter para continuar...")
        elif choice == '4':
            show_brain(brain)
            input("\nPresiona Enter para continuar...")
        elif choice == '5':
            diary = Path.home() / ".orion-code" / "diary.md"
            print(f"\n--- DIARIO ({diary}) ---")
            if diary.exists():
                data = diary.read_text(encoding="utf-8", errors="replace")
                print("...\n" + data[-4000:] if len(data) > 4000 else data)
            else:
                print("Aún no hay diario.")
            input("\nPresiona Enter para continuar...")
        elif choice == '6':
            script = Path(__file__).resolve().parent / "orion_code.py"
            if script.exists():
                subprocess.run([sys.executable, str(script)])
            else:
                print("No encuentro orion_code.py junto al dashboard.")
            input("\nPresiona Enter para continuar...")
        elif choice == '7':
            print("\n¡Hasta luego! 🌌 Saliendo de Orión Dashboard.")
            break
        else:
            print("\n❌ Opción inválida.")
            input("\nPresiona Enter para continuar...")


if __name__ == "__main__":
    main_menu()