"""Diagnóstico do ambiente:  python -m app.tools.doctor   (ou diagnostico.bat)

Confere Python, pacotes, arquivo .env, banco de dados, porta e a conexão com
cada serviço externo. Nunca mostra o valor das chaves. Faz no máximo uma
consulta pequena à UN Comtrade (1 requisição da cota diária) e nenhuma
geração de texto no Groq (apenas lista os modelos, sem gastar tokens).
"""

from __future__ import annotations

import importlib
import socket
import sys
from pathlib import Path

OK, WARN, FAIL = "[ OK ]", "[AVISO]", "[FALHA]"
results: list[str] = []


def line(status: str, text: str, hint: str | None = None) -> None:
    results.append(status)
    print(f"{status} {text}")
    if hint:
        print(f"        -> {hint}")


def check_python() -> None:
    v = sys.version_info
    text = f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if v >= (3, 12):
        line(OK, text)
    else:
        line(FAIL, text, "Instale o Python 3.12 ou mais novo, apague a pasta venv e rode o run.bat de novo.")


def check_packages() -> bool:
    ok = True
    for mod, name in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("pandas", "pandas"),
                      ("requests", "requests"), ("dotenv", "python-dotenv"), ("pydantic", "pydantic")]:
        try:
            m = importlib.import_module(mod)
            line(OK, f"Pacote {name} {getattr(m, '__version__', '')}".strip())
        except ImportError:
            ok = False
            line(FAIL, f"Pacote {name} não instalado", "Rode o run.bat (ele instala as dependências).")
    return ok


def check_env(settings) -> None:
    from app.config import BASE_DIR

    if (BASE_DIR / ".env").exists():
        line(OK, "Arquivo .env encontrado")
    else:
        line(WARN, "Arquivo .env não encontrado", "Copie .env.example para .env e preencha as chaves.")
    if settings.comtrade_configured:
        line(OK, "Chave da UN Comtrade configurada")
    else:
        line(FAIL, "Chave da UN Comtrade ausente", "Preencha COMTRADE_API_KEY no .env (veja o README).")
    if settings.groq_configured:
        line(OK, f"Chave do Groq configurada (modelo {settings.groq_model})")
    else:
        line(WARN, "Chave do Groq ausente", "Sem ela, as funções de IA ficam indisponíveis. Preencha GROQ_API_KEY no .env.")


def check_database(settings) -> None:
    from app.database import connect, init_db
    from app.services.reference import reference_status

    try:
        version = init_db(settings.database_path)
        conn = connect(settings.database_path)
        status = reference_status(conn)
        searches = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        conn.close()
    except Exception as exc:  # noqa: BLE001 - diagnóstico deve relatar qualquer falha
        line(FAIL, f"Banco de dados: {exc}", f"Verifique permissão de escrita em {settings.database_path.parent}")
        return
    line(OK, f"Banco de dados pronto (esquema v{version}, {searches} pesquisa(s) salva(s))")
    if status["ncm"]["rows"] and status["countries"]["rows"]:
        line(OK, f"Tabelas oficiais: {status['ncm']['rows']} NCMs, {status['countries']['rows']} países")
    else:
        line(WARN, "Tabelas oficiais ainda não baixadas",
             "Elas são baixadas automaticamente ao iniciar o run.bat (cerca de 2 minutos na primeira vez).")


def check_port(settings) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((settings.app_host, settings.app_port))
            line(OK, f"Porta {settings.app_port} livre")
        except OSError:
            line(WARN, f"Porta {settings.app_port} em uso",
                 "O sistema pode já estar aberto. Se não estiver, altere APP_PORT no .env.")


def check_services(settings) -> None:
    from app.services import comtrade
    from app.services.http import ExternalServiceError, request_json
    from app.services.reference import COMEXSTAT_API

    try:
        body = request_json("GET", f"{COMEXSTAT_API}/general/dates/updated", source="Comex Stat", timeout=20, retries=0)
        d = body.get("data") or {}
        line(OK, f"Comex Stat acessível (dados até {d.get('monthNumber')}/{d.get('year')})")
    except ExternalServiceError as exc:
        line(FAIL, f"Comex Stat: {exc.message}", "Verifique a conexão com a internet ou proxy da rede.")

    if settings.comtrade_configured:
        try:
            records = comtrade._fetch(settings, {"cmdCode": "0901", "reporterCode": "842", "partnerCode": "0",
                                                 "period": str(comtrade.default_years()[-2])})
            line(OK, f"UN Comtrade acessível e chave válida ({len(records)} registro(s) de teste)")
        except ExternalServiceError as exc:
            line(FAIL, f"UN Comtrade: {exc.message}", "Confira a chave em comtradedeveloper.un.org e a conexão.")

    if settings.groq_configured:
        try:
            body = request_json("GET", "https://api.groq.com/openai/v1/models", source="Groq", timeout=20, retries=0,
                                headers={"Authorization": f"Bearer {settings.groq_api_key}"})
            models = {m.get("id") for m in body.get("data", [])}
            if settings.groq_model in models:
                line(OK, f"Groq acessível; modelo {settings.groq_model} disponível")
            else:
                line(FAIL, f"Groq acessível, mas o modelo {settings.groq_model} não está disponível",
                     "Altere GROQ_MODEL no .env (ex.: openai/gpt-oss-120b).")
        except ExternalServiceError as exc:
            line(FAIL, f"Groq: {exc.message}", "Confira a chave em console.groq.com/keys e a conexão.")


def main() -> int:
    print("Diagnóstico do CFI Market Finder\n")
    check_python()
    if not check_packages():
        print("\nCorrija os pacotes antes de continuar.")
        return 1
    from app.config import load_settings

    settings = load_settings()
    check_env(settings)
    check_database(settings)
    check_port(settings)
    print("\nTestando conexão com os serviços externos...")
    check_services(settings)

    fails, warns = results.count(FAIL), results.count(WARN)
    print(f"\nResumo: {len(results) - fails - warns} ok, {warns} aviso(s), {fails} falha(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    # garante acentos corretos no console do Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.exit(main())
