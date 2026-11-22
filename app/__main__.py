"""Inicializa o servidor:  python -m app  [--no-browser] [--reload]

Lê host/porta do .env, verifica se a porta está livre, abre o navegador
e sobe o Uvicorn. Usado pelo run.bat.
"""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser

import uvicorn

from app.config import load_settings


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main() -> int:
    settings = load_settings()
    host, port = settings.app_host, settings.app_port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"

    if not port_is_free(host, port):
        print(f"[ERRO] A porta {port} já está em uso. O CFI Market Finder pode já estar aberto em {url}")
        print("       Feche a outra instância ou altere APP_PORT no arquivo .env.")
        return 1

    print(f"CFI Market Finder em {url}  (Ctrl+C para encerrar)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()

    uvicorn.run("app.main:app", host=host, port=port, reload="--reload" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
