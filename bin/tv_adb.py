#!/usr/bin/env python3
"""Google TV / Chromecast ADB Management Utility.

Automates package management, debloat, SmartTube updates, and performance tuning.
"""

import argparse
import subprocess
import sys

DEFAULT_TV_IP = "192.168.8.206"


def run_adb(cmd: list[str], target: str = "") -> subprocess.CompletedProcess:
    base = ["adb"]
    if target:
        base.extend(["-s", target])
    base.extend(cmd)
    return subprocess.run(base, capture_output=True, text=True)


def list_apps(target: str):
    print(f"📱 Listando aplicativos instalados na TV ({target or 'default'})...\n")
    res = run_adb(["shell", "pm", "list", "packages", "-3"], target)
    if res.returncode != 0:
        print(f"❌ Erro ao listar apps: {res.stderr}")
        return
    for line in res.stdout.strip().split("\n"):
        pkg = line.replace("package:", "").strip()
        if pkg:
            print(f"  • {pkg}")


def get_storage(target: str):
    res = run_adb(["shell", "df", "-h", "/data"], target)
    print("\n💾 Armazenamento da TV:")
    print(res.stdout)


def optimize_animations(target: str):
    print(f"⚡ Otimizando escalas de animação para 0.5x na TV ({target or 'default'})...")
    run_adb(["shell", "settings", "put", "global", "window_animation_scale", "0.5"], target)
    run_adb(["shell", "settings", "put", "global", "transition_animation_scale", "0.5"], target)
    run_adb(["shell", "settings", "put", "global", "animator_duration_scale", "0.5"], target)
    print("✓ Interface acelerada com sucesso (0.5x)!")


def main():
    parser = argparse.ArgumentParser(description="Google TV ADB Management Utility")
    parser.add_argument("--target", type=str, default="", help="Dispositivo ADB específico (ex: 192.168.8.206:32875)")
    parser.add_argument("--list-apps", action="store_true", help="Listar aplicativos de terceiros")
    parser.add_argument("--storage", action="store_true", help="Exibir uso de armazenamento")
    parser.add_argument("--optimize", action="store_true", help="Acelerar animações para 0.5x")

    args = parser.parse_args()

    if args.list_apps:
        list_apps(args.target)
    elif args.storage:
        get_storage(args.target)
    elif args.optimize:
        optimize_animations(args.target)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
