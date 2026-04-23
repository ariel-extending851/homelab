#!/usr/bin/env python3
"""Destructive AWS lab cleanup: runs aws-nuke 5 times under explicit confirmation.

Port of infra/aws/scripts/clean-lab.sh — preserves identical behavior:
exit codes, message strings, 5 attempts with 10s sleep between, required
uppercase 'SIM' confirmation.
"""

import json
import subprocess
import sys
import time

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"

TOTAL_ATTEMPTS = 5
NUKE_DELAY_SECONDS = 10
COUNTDOWN_SECONDS = 5
CONFIRMATION_TOKEN = "SIM"


def get_caller_identity():
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    identity = json.loads(result.stdout)
    return identity["Account"], identity["Arn"]


def countdown(seconds):
    for i in range(seconds, 0, -1):
        print(f"{i}... ", end="", flush=True)
        time.sleep(1)
    print("GO! 🚀")


def run_nuke_loop(attempts=TOTAL_ATTEMPTS):
    for i in range(1, attempts + 1):
        print()
        print(f"{YELLOW}--------------------------------------------------{NC}")
        print(f"{YELLOW}   Tentativa de Nuke {i} de {attempts} {NC}")
        print(f"{YELLOW}--------------------------------------------------{NC}")

        subprocess.run(
            [
                "aws-nuke",
                "run",
                "--config",
                "config.yml",
                "--profile",
                "default",
                "--no-dry-run",
                "--force",
            ],
            check=True,
        )

        if i < attempts:
            print()
            print(
                f"{GREEN}⏳ Aguardando {NUKE_DELAY_SECONDS} segundos para "
                f"estabilização da AWS...{NC}"
            )
            time.sleep(NUKE_DELAY_SECONDS)


def main():
    print(f"{YELLOW}=================================================={NC}")
    print(f"{RED}   💣 PROTOCOLO DE DESTRUIÇÃO - AWS NUKE (LOOP)   {NC}")
    print(f"{YELLOW}=================================================={NC}")
    print("Verificando credenciais atuais...")

    # Match original shell (no `set -e`): if AWS STS fails the script still
    # shows the banner with empty-ish identity and falls through to the
    # confirmation gate. This avoids a Python traceback for unauthenticated runs.
    try:
        account_id, arn = get_caller_identity()
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        account_id, arn = "unknown", "unknown"

    print("Você está prestes a limpar a conta:")
    print(f"🆔 Account ID: {GREEN}{account_id}{NC}")
    print(f"👤 User ARN:   {GREEN}{arn}{NC}")
    print()
    print(
        f"{RED}⚠️  CUIDADO: Isso vai rodar o aws-nuke {TOTAL_ATTEMPTS} "
        f"VEZES com --force.{NC}"
    )
    print(f"{RED}    Todos os recursos não filtrados serão DESTRUÍDOS.{NC}")
    print()

    confirm = input(
        f"Tem certeza absoluta que deseja continuar? "
        f"Digite '{CONFIRMATION_TOKEN}' para confirmar: "
    )
    if confirm != CONFIRMATION_TOKEN:
        print("Operação cancelada pelo usuário.")
        return 1

    print()
    print(
        f"{YELLOW}Iniciando em {COUNTDOWN_SECONDS} segundos... "
        f"(Pressione Ctrl+C para cancelar){NC}"
    )
    countdown(COUNTDOWN_SECONDS)

    run_nuke_loop()

    print()
    print(f"{GREEN}✅ Processo de loop finalizado.{NC}")
    print("Recomendação: Verifique o console AWS para garantir que tudo sumiu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
