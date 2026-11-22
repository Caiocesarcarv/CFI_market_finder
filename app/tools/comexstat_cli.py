"""Carga de dados do Comex Stat pela linha de comando.

Uso (na raiz do projeto, com o venv):

  venv\\Scripts\\python -m app.tools.comexstat_cli sync
      Baixa/atualiza as tabelas oficiais NCM e de países.

  venv\\Scripts\\python -m app.tools.comexstat_cli import data\\comexstat\\EXP_2024.csv [outros.csv] [--ncm 09]
      Importa arquivos oficiais EXP_AAAA.csv (base "Exportação" por NCM do
      Comex Stat). Sem arquivos, importa todos os data\\comexstat\\EXP_*.csv.
      --ncm restringe a um prefixo de NCM para economizar espaço.

Os arquivos EXP_AAAA.csv são publicados em
https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app.config import BASE_DIR, load_settings
from app.database import connect, init_db
from app.services import comexstat, reference
from app.services.http import ExternalServiceError

CSV_DIR = BASE_DIR / "data" / "comexstat"


def cmd_sync(conn) -> int:
    print("Baixando tabela NCM...")
    print(f"  {reference.sync_ncm(conn)} códigos NCM.")
    print("Baixando países (pode levar ~2 minutos na primeira vez)...")
    print(f"  {reference.sync_countries(conn)} países com código ISO.")
    return 0


def cmd_import(conn, files: list[str], ncm_prefix: str | None) -> int:
    paths = [Path(f) for f in files] or sorted(CSV_DIR.glob("EXP_*.csv"))
    if not paths:
        print(f"Nenhum arquivo informado e nenhum EXP_*.csv em {CSV_DIR}")
        return 1
    if not conn.execute("SELECT EXISTS(SELECT 1 FROM countries WHERE iso3 IS NOT NULL)").fetchone()[0]:
        print("[AVISO] Tabela de países vazia: rode 'sync' antes para ligar os destinos ao código ISO.")
    status = 0
    for path in paths:
        t = time.time()
        print(f"Importando {path} ...")
        try:
            r = comexstat.import_csv(conn, path, ncm_prefix=ncm_prefix)
        except (FileNotFoundError, ValueError) as exc:
            print(f"  [ERRO] {exc}")
            status = 1
            continue
        print(f"  {r['read_rows']:,} linhas lidas → {r['stored_rows']:,} registros (anos {r['years']}) "
              f"em {time.time() - t:.0f}s")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.tools.comexstat_cli", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="baixar tabelas NCM e países")
    imp = sub.add_parser("import", help="importar arquivos EXP_AAAA.csv")
    imp.add_argument("files", nargs="*")
    imp.add_argument("--ncm", dest="ncm_prefix", help="importar apenas NCMs com este prefixo")
    args = parser.parse_args(argv)

    settings = load_settings()
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    try:
        if args.command == "sync":
            return cmd_sync(conn)
        return cmd_import(conn, args.files, args.ncm_prefix)
    except ExternalServiceError as exc:
        print(f"[ERRO] {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
