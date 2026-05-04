"""ETL: baixa o CSV consolidado da Execução Orçamentária da PMSP e carrega em SQLite.

Fonte oficial:
    https://orcamento.prefeitura.sp.gov.br/orcamento/uploads/<ano>/basedadosexecucaoConsolidadosComRestos_<mmaa>.csv

O arquivo cobre 2003 até o ano corrente (~200 MB) e é regerado mensalmente.
Cada execução substitui o conteúdo da tabela `execucao` em `despesas.db`.

Uso:
    python etl_orcamento.py                 # usa URL default ou ORCAMENTO_CSV_URL
    python etl_orcamento.py --discover      # tenta encontrar o CSV mais recente
    python etl_orcamento.py --url <url>     # usa URL específica
    python etl_orcamento.py --csv data/x.csv  # usa CSV local, sem download
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

DB_PATH = Path(__file__).parent / "despesas.db"
DATA_DIR = Path(__file__).parent / "data"
TABLE = "execucao"

URL_PADRAO = (
    "https://orcamento.prefeitura.sp.gov.br/orcamento/uploads/2026/"
    "basedadosexecucaoConsolidadosComRestos_0426.csv"
)
URL_TEMPLATE = (
    "https://orcamento.prefeitura.sp.gov.br/orcamento/uploads/{ano}/"
    "basedadosexecucaoConsolidadosComRestos_{mmaa}.csv"
)

NUMERIC_COLUMNS = [
    "Vl_Orcado_Ano",
    "Vl_Suplementado",
    "Vl_Reduzido",
    "Vl_SuplementadoLiquido",
    "Vl_SuplementadoEmTramitacao",
    "Vl_ReduzidoEmTramitacao",
    "Vl_Orcado_Atualizado",
    "Vl_Congelado",
    "Vl_Descongelado",
    "Vl_CongeladoLiquido",
    "Disponivel",
    "Vl_ReservadoLiquido",
    "Vl_Empenhado",
    "Empenhado_Anulado",
    "Vl_EmpenhadoLiquido",
    "Vl_Liquidado",
    "Vl_Pago",
    "Saldo_Dotacao",
]

INDEX_COLUMNS = ["Cd_Exercicio", "Cd_Orgao", "Cd_Funcao", "Categoria_Despesa"]


def descobrir_url_atual(meses_para_tras: int = 12) -> str:
    """Tenta achar o CSV mais recente caminhando do mês atual para trás."""
    today = datetime.now()
    for delta in range(meses_para_tras):
        ano = today.year
        mes = today.month - delta
        while mes <= 0:
            mes += 12
            ano -= 1
        url = URL_TEMPLATE.format(ano=ano, mmaa=f"{mes:02d}{ano % 100:02d}")
        try:
            r = requests.head(url, timeout=20, allow_redirects=True)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            return url
    raise RuntimeError(
        f"Nenhum CSV encontrado nos últimos {meses_para_tras} meses no padrão de URL."
    )


def _parse_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def remoto_mais_novo(url: str, destino: Path) -> bool | None:
    """Compara Last-Modified do remoto com mtime do cache local.

    Retorna True se o remoto for mais novo (precisa baixar), False se o cache
    já está em dia, ou None se não conseguiu decidir (HEAD falhou ou o
    servidor não devolveu Last-Modified).
    """
    if not destino.exists():
        return True
    try:
        r = requests.head(url, timeout=20, allow_redirects=True)
        r.raise_for_status()
    except requests.RequestException:
        return None
    remote_dt = _parse_last_modified(r.headers.get("Last-Modified"))
    if remote_dt is None:
        return None
    local_dt = datetime.fromtimestamp(destino.stat().st_mtime, tz=timezone.utc)
    return remote_dt > local_dt


def baixar_csv(url: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"Baixando {url}")
    print(f"  destino: {destino}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        baixado = 0
        with open(destino, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
                baixado += len(chunk)
                if total:
                    pct = 100 * baixado / total
                    print(
                        f"  {pct:5.1f}% — {baixado / 1e6:7.1f} MB / {total / 1e6:.1f} MB",
                        end="\r",
                    )
        print()
        remote_dt = _parse_last_modified(r.headers.get("Last-Modified"))
    if remote_dt is not None:
        ts = remote_dt.timestamp()
        os.utime(destino, (ts, ts))
    return destino


def _detectar_encoding(csv_path: Path) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            with open(csv_path, "r", encoding=enc) as f:
                f.readline()
            return enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Nenhum encoding funcionou (tentou utf-8 e latin-1).")


def carregar_sqlite(
    csv_path: Path, db_path: Path = DB_PATH, tabela: str = TABLE
) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute(f"DROP TABLE IF EXISTS {tabela}")
    encoding = _detectar_encoding(csv_path)
    print(f"Carregando {csv_path.name} em {db_path}::{tabela} (encoding {encoding})")

    chunks = pd.read_csv(
        csv_path,
        sep=";",
        encoding=encoding,
        dtype=str,
        chunksize=100_000,
        low_memory=False,
    )
    total = 0
    for i, chunk in enumerate(chunks, start=1):
        for col in NUMERIC_COLUMNS:
            if col in chunk.columns:
                chunk[col] = pd.to_numeric(
                    chunk[col].str.replace(",", ".", regex=False),
                    errors="coerce",
                )
        chunk.to_sql(tabela, conn, if_exists="append", index=False)
        total += len(chunk)
        print(f"  bloco {i}: +{len(chunk):,} linhas — total {total:,}", end="\r")
    print()

    print("Criando índices...")
    for col in INDEX_COLUMNS:
        try:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{col}" ON {tabela}("{col}")'
            )
        except sqlite3.OperationalError as exc:
            print(f"  aviso: índice em {col} falhou ({exc})")
    conn.commit()
    conn.close()
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--url", help="URL do CSV (sobrescreve default e ORCAMENTO_CSV_URL)."
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Detecta automaticamente o CSV mais recente.",
    )
    parser.add_argument(
        "--csv", help="Caminho de CSV local; se passado, pula download."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebaixa mesmo se já houver cache local.",
    )
    args = parser.parse_args(argv)

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"ERRO: CSV não encontrado em {csv_path}", file=sys.stderr)
            return 1
    else:
        if args.discover:
            url = descobrir_url_atual()
            print(f"URL descoberta: {url}")
        else:
            url = args.url or os.getenv("ORCAMENTO_CSV_URL", URL_PADRAO)

        DATA_DIR.mkdir(exist_ok=True)
        csv_path = DATA_DIR / url.rsplit("/", 1)[-1]
        if args.force:
            baixar_csv(url, csv_path)
        else:
            status = remoto_mais_novo(url, csv_path)
            if status is False:
                print(
                    f"Cache em {csv_path} já reflete a versão remota "
                    "(Last-Modified inalterado). BD não precisa ser recarregado."
                )
                return 0
            if status is None and csv_path.exists():
                print(
                    "Last-Modified indisponível; reaproveitando cache local "
                    "e recarregando o BD por garantia."
                )
            else:
                baixar_csv(url, csv_path)

    n = carregar_sqlite(csv_path)
    print(f"Pronto. {n:,} linhas em {DB_PATH}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
