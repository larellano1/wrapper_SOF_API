"""Q&A em linguagem natural sobre o BD orçamentário, via Claude API.

Expõe `perguntar(texto)` que devolve um dict com `texto` (markdown) e
opcionalmente `grafico` (spec para Plotly). Internamente faz um loop de
tool-use com Claude Haiku 4.5: o modelo pode chamar `buscar_dimensao`
(busca aproximada nas descrições de órgão/função/etc.) e `consultar`
(SELECT no SQLite read-only) até decidir responder.

Configuração:
    ANTHROPIC_API_KEY no .env (gerada em https://console.anthropic.com)
    NL_QUERY_MODEL (opcional) — modelo Claude, default `claude-haiku-4-5`
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

DB_PATH = Path(__file__).parent / "despesas.db"
TABLE = "execucao"
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_ITERS = 10
MAX_LINHAS_RETORNO = 200

# Mapeamento Ds_* -> coluna do código associado (nem sempre é Cd_*).
DESC_TO_COD = {
    "Ds_Orgao": "Cd_Orgao",
    "Ds_Unidade": "Cd_Unidade",
    "Ds_Funcao": "Cd_Funcao",
    "Ds_SubFuncao": "Cd_SubFuncao",
    "Ds_Programa": "Cd_Programa",
    "Ds_Projeto_Atividade": "ProjetoAtividade",
    "Ds_Categoria": "Categoria_Despesa",
    "Ds_Grupo": "Grupo_Despesa",
    "Ds_Modalidade": "Cd_Modalidade",
    "Ds_Despesa": "Cd_Despesa",
    "Ds_Fonte": "Cd_Fonte",
}

SYSTEM_PROMPT = """Você é um analista de dados especializado no orçamento da Prefeitura de São Paulo.
Responde em português brasileiro, de forma objetiva e com números concretos.

Você tem acesso a uma tabela SQLite chamada `execucao` com dados de execução
orçamentária da PMSP de 2003 até o ano corrente.

Colunas-chave (tipos numéricos já convertidos, NÃO precisa de CAST):

- `Cd_Exercicio` (INTEGER): ano do orçamento.
- `Cd_AnoExecucao` (INTEGER): ano em que a movimentação ocorreu. Quando
  Cd_Exercicio ≠ Cd_AnoExecucao, a linha é execução de **restos a pagar**
  de um orçamento antigo. Para "execução pura" do exercício, filtre
  Cd_Exercicio = Cd_AnoExecucao.
- Hierarquia institucional: `Cd_Orgao` / `Ds_Orgao`, `Cd_Unidade` / `Ds_Unidade`.
- Hierarquia funcional: `Cd_Funcao` / `Ds_Funcao`, `Cd_SubFuncao` / `Ds_SubFuncao`,
  `Cd_Programa` / `Ds_Programa`, `ProjetoAtividade` / `Ds_Projeto_Atividade`.
- Classificação econômica:
  - `Categoria_Despesa` (1=Correntes, 2=Capital) e `Ds_Categoria`.
  - `Grupo_Despesa` (1-Pessoal, 2-Juros, 3-Outras Correntes, 4-Investimentos,
    5-Inversões, 6-Amortização) e `Ds_Grupo`.
  - `Cd_Modalidade` / `Ds_Modalidade`.
  - `Cd_Elemento` (sem Ds_Elemento na base).
  - `Cd_Despesa` / `Ds_Despesa` — descrição completa do item de despesa
    (ex.: "Sentenças Judiciais" provavelmente está aqui).
- Fonte: `Cd_Fonte` / `Ds_Fonte`.
- Valores em R$ (números): `Vl_Orcado_Ano`, `Vl_Orcado_Atualizado`,
  `Vl_EmpenhadoLiquido`, `Vl_Liquidado`, `Vl_Pago`, `Disponivel`.

Workflow:
1. Se a pergunta cita um nome específico (ex.: "Sentenças Judiciais",
   "Saúde", "Educação"), use `buscar_dimensao` primeiro para descobrir
   em que coluna está e qual o código.
2. Use `consultar` para rodar SELECT agregado (SUM, GROUP BY).
3. Quando tiver os dados, chame `responder` com texto em markdown e,
   quando fizer sentido, um gráfico (bar para comparar dimensões, line
   para evolução temporal).

Boas práticas:
- Para crescimento entre anos, calcule % e absoluto.
- Apresente valores grandes em milhões ou bilhões (formate com vírgula
  decimal brasileira no markdown).
- Para comparações de anos parciais (ano corrente vs anos cheios),
  alerte o usuário sobre a parcialidade.
- Se buscar_dimensao trouxer múltiplos hits, escolha o mais provável e
  cite no texto qual foi adotado.
- Se não houver dados, diga claramente em vez de inventar.
"""


TOOLS = [
    {
        "name": "buscar_dimensao",
        "description": (
            "Busca aproximada (LIKE) por um termo nas descrições das "
            "dimensões. Use quando o usuário menciona um nome (órgão, "
            "função, programa, item de despesa) e você precisa do código."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {
                    "type": "string",
                    "description": "Termo a buscar (ex.: 'Sentenças Judiciais').",
                },
                "colunas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Subconjunto de colunas Ds_* a buscar. Se vazio, "
                        "busca em todas as descrições. Opções: "
                        "Ds_Orgao, Ds_Unidade, Ds_Funcao, Ds_SubFuncao, "
                        "Ds_Programa, Ds_Projeto_Atividade, Ds_Categoria, "
                        "Ds_Grupo, Ds_Modalidade, Ds_Despesa, Ds_Fonte."
                    ),
                },
            },
            "required": ["termo"],
        },
    },
    {
        "name": "consultar",
        "description": (
            "Executa um SELECT no SQLite read-only contra a tabela "
            "`execucao`. Apenas SELECT é permitido. Use SUM agregado e "
            "GROUP BY quando comparar anos ou dimensões."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL SELECT válido para SQLite.",
                }
            },
            "required": ["sql"],
        },
    },
    {
        "name": "responder",
        "description": (
            "Devolve a resposta final ao usuário com texto em markdown "
            "e, opcionalmente, um gráfico simples."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Resposta em markdown (português).",
                },
                "grafico": {
                    "type": "object",
                    "description": "Spec opcional do gráfico.",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": ["bar", "line", "none"],
                        },
                        "x": {
                            "type": "array",
                            "items": {"type": ["string", "number"]},
                        },
                        "y": {"type": "array", "items": {"type": "number"}},
                        "x_label": {"type": "string"},
                        "y_label": {"type": "string"},
                        "titulo": {"type": "string"},
                    },
                },
            },
            "required": ["texto"],
        },
    },
]


def _conectar_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _buscar_dimensao(termo: str, colunas: list[str] | None = None) -> dict:
    if not colunas:
        colunas = list(DESC_TO_COD.keys())
    pad = f"%{termo}%"
    conn = _conectar_ro()
    out: dict[str, Any] = {}
    for col_desc in colunas:
        col_cod = DESC_TO_COD.get(col_desc)
        if col_cod is None:
            out[col_desc] = {"erro": "coluna desconhecida"}
            continue
        try:
            df = pd.read_sql(
                f"SELECT DISTINCT {col_cod} AS codigo, {col_desc} AS descricao "
                f"FROM {TABLE} WHERE {col_desc} LIKE ? "
                f"ORDER BY {col_cod} LIMIT 25",
                conn,
                params=(pad,),
            )
        except Exception as exc:
            out[col_desc] = {"erro": str(exc)}
            continue
        if not df.empty:
            out[col_desc] = df.to_dict(orient="records")
    conn.close()
    if not out:
        return {"info": f"Nenhum match para '{termo}' nas descrições."}
    return out


_PROIBIDOS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA",
)


def _consultar(sql: str) -> dict:
    sql_up = " " + sql.strip().upper() + " "
    if not (sql_up.lstrip().startswith("SELECT") or sql_up.lstrip().startswith("WITH")):
        return {"erro": "Apenas SELECT/WITH é permitido."}
    for kw in _PROIBIDOS:
        if f" {kw} " in sql_up:
            return {"erro": f"Comando {kw} não permitido."}
    conn = _conectar_ro()
    try:
        df = pd.read_sql(sql, conn)
    except Exception as exc:
        conn.close()
        return {"erro": str(exc)}
    conn.close()
    truncado = len(df) > MAX_LINHAS_RETORNO
    if truncado:
        df = df.head(MAX_LINHAS_RETORNO)
    return {
        "linhas": df.to_dict(orient="records"),
        "n_linhas": len(df),
        "truncado": truncado,
    }


def perguntar(pergunta: str) -> dict:
    """Executa o loop de tool-use e devolve dict com `texto` e `grafico`."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "erro": (
                "ANTHROPIC_API_KEY não configurada. Gere uma key em "
                "https://console.anthropic.com e adicione ao arquivo .env."
            )
        }
    if not DB_PATH.exists():
        return {"erro": f"BD local não encontrado: {DB_PATH}"}

    try:
        from anthropic import Anthropic
    except ImportError:
        return {"erro": "Pacote `anthropic` não instalado. Rode: pip install anthropic"}

    model = os.getenv("NL_QUERY_MODEL", DEFAULT_MODEL)
    client = Anthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": pergunta}]
    trace: list[dict] = []

    for _ in range(MAX_ITERS):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except Exception as exc:
            return {"erro": f"Erro na API Anthropic: {exc}"}

        if resp.stop_reason == "end_turn":
            texto = "".join(
                getattr(b, "text", "") for b in resp.content if hasattr(b, "text")
            )
            return {"texto": texto or "(modelo não retornou texto)", "grafico": None, "trace": trace}

        if resp.stop_reason != "tool_use":
            return {"erro": f"stop_reason inesperado: {resp.stop_reason}", "trace": trace}

        messages.append({"role": "assistant", "content": resp.content})

        tool_results: list[dict] = []
        for bloco in resp.content:
            if getattr(bloco, "type", None) != "tool_use":
                continue

            nome = bloco.name
            entrada = bloco.input or {}

            if nome == "responder":
                trace.append({"tool": nome, "input": entrada})
                return {
                    "texto": entrada.get("texto", ""),
                    "grafico": entrada.get("grafico"),
                    "trace": trace,
                }
            if nome == "buscar_dimensao":
                resultado = _buscar_dimensao(
                    termo=entrada.get("termo", ""),
                    colunas=entrada.get("colunas"),
                )
            elif nome == "consultar":
                resultado = _consultar(sql=entrada.get("sql", ""))
            else:
                resultado = {"erro": f"Tool desconhecida: {nome}"}

            trace.append({"tool": nome, "input": entrada, "resultado": resultado})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": bloco.id,
                    "content": json.dumps(
                        resultado, default=str, ensure_ascii=False
                    ),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return {"erro": f"Loop de tool-use excedeu {MAX_ITERS} iterações.", "trace": trace}
