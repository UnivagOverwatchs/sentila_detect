"""
atualizar_lock.py - Gera deploy/requirements-painel.lock.txt com versões EXATAS (reprodutível) e confere falhas.

    python deploy/atualizar_lock.py

1. cria um ambiente virtual limpo e temporário;
2. instala deploy/requirements-painel.txt (as versões mais novas que atendem aos mínimos);
3. grava o `pip freeze` no lock;
4. roda o pip-audit no lock (falha se houver vulnerabilidade conhecida).
"""

import os
import subprocess
import sys
import tempfile
import venv

RAIZ = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(RAIZ, "requirements-painel.txt")
LOCK = os.path.join(RAIZ, "requirements-painel.lock.txt")


def main() -> int:
    with tempfile.TemporaryDirectory() as pasta:
        venv.create(pasta, with_pip=True)
        python = os.path.join(pasta, "Scripts" if os.name == "nt" else "bin", "python")
        subprocess.run([python, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([python, "-m", "pip", "install", "-q", "-r", ENTRADA], check=True)
        congelado = subprocess.run([python, "-m", "pip", "freeze", "--exclude", "pip"], check=True,
                                   capture_output=True, text=True).stdout
        with open(LOCK, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write("# Gerado por deploy/atualizar_lock.py - não editar à mão.\n" + congelado)
        subprocess.run([python, "-m", "pip", "install", "-q", "pip-audit"], check=True)
        return subprocess.run([python, "-m", "pip_audit", "-r", LOCK, "--progress-spinner", "off"]).returncode


if __name__ == "__main__":
    sys.exit(main())
