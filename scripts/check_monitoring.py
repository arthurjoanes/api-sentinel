"""Valida configuração e séries sintéticas sem iniciar a stack de demonstração."""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MONITORING = PROJECT / "monitoring"
CONTAINER_MONITORING = "/etc/sentinel/monitoring"


def docker_command(image: str, tool: str, *arguments: str, workdir: str | None = None) -> list[str]:
    # --volume usa ':'; --mount interpreta vírgulas no caminho como separadores CSV.
    # Cada argumento segue separado ao subprocess, inclusive caminhos Windows com espaços.
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--volume",
        f"{MONITORING.resolve()}:{CONTAINER_MONITORING}:ro",
    ]
    if workdir is not None:
        command.extend(["--workdir", workdir])
    command.extend(["--entrypoint", f"/bin/{tool}", image, *arguments])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-image", default="prom/prometheus:v3.5.0")
    parser.add_argument("--alertmanager-image", default="prom/alertmanager:v0.28.1")
    options = parser.parse_args()
    if not MONITORING.is_dir():
        print(f"Diretório de monitoramento não encontrado: {MONITORING}", file=sys.stderr)
        return 2

    checks = [
        (
            "Configurações Prometheus: demo e referência",
            docker_command(
                options.prometheus_image,
                "promtool",
                "check",
                "config",
                f"{CONTAINER_MONITORING}/prometheus/demo.yml",
                f"{CONTAINER_MONITORING}/prometheus/reference.yml",
            ),
        ),
        (
            "Regras Prometheus: demo e referência",
            docker_command(
                options.prometheus_image,
                "promtool",
                "check",
                "rules",
                f"{CONTAINER_MONITORING}/rules/demo.yml",
                f"{CONTAINER_MONITORING}/rules/reference.yml",
            ),
        ),
        (
            "Séries sintéticas: demo e referência",
            docker_command(
                options.prometheus_image,
                "promtool",
                "test",
                "rules",
                "demo.yml",
                "reference.yml",
                "delivery-health.yml",
                "probe-freshness.yml",
                workdir=f"{CONTAINER_MONITORING}/rules-tests",
            ),
        ),
        (
            "Configurações Alertmanager: demo e referência",
            docker_command(
                options.alertmanager_image,
                "amtool",
                "check-config",
                f"{CONTAINER_MONITORING}/alertmanager/demo.yml",
                f"{CONTAINER_MONITORING}/alertmanager/reference.yml",
            ),
        ),
    ]
    for description, command in checks:
        print(description, flush=True)
        try:
            result = subprocess.run(command, cwd=PROJECT, check=False)
        except FileNotFoundError:
            print("Docker CLI não encontrado no PATH.", file=sys.stderr)
            return 127
        if result.returncode:
            print(
                f"Validação interrompida: Docker retornou {result.returncode}.",
                file=sys.stderr,
            )
            return result.returncode if result.returncode > 0 else 128 - result.returncode
    print("Configurações e testes de regras: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
