"""Dashboard Orçamentário da Prefeitura de São Paulo.

Consome a API do SOF (Sistema Orçamentário Financeiro) via wrapper local
e exibe despesas (empenhada, liquidada e paga) por Órgão, Função e
Categoria Econômica, com comparação entre anos e evolução temporal.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from consultas_api_sof import (  # noqa: E402
    Categorias,
    Despesas,
    Funcoes,
    Orgaos,
)


def _check_credentials() -> str | None:
    if os.getenv("SOF_API_TOKEN"):
        return None
    if os.getenv("SOF_API_CONSUMER_KEY") and os.getenv("SOF_API_CONSUMER_SECRET"):
        return None
    return (
        "Credenciais da API SOF não configuradas. Crie um arquivo `.env` "
        "(use `.env.example` como base) com `SOF_API_CONSUMER_KEY` e "
        "`SOF_API_CONSUMER_SECRET`, ou exporte `SOF_API_TOKEN`. "
        "Cadastro: https://apilib.prefeitura.sp.gov.br/store/"
    )


st.set_page_config(
    page_title="Dashboard Orçamentário - PMSP",
    page_icon="📊",
    layout="wide",
)


VALOR_CANDIDATOS = {
    "Empenhada": ["valTotalEmpenhadoLiquido", "valTotalEmpenhado", "valEmpenhadoLiquido"],
    "Liquidada": ["valTotalLiquidadoLiquido", "valTotalLiquidado", "valLiquidadoLiquido"],
    "Paga": ["valTotalPagoExercicio", "valTotalPago", "valPagoExercicio"],
}

DESC_CANDIDATOS = {
    "codOrgao": ["txtDescricaoOrgao", "txtOrgao", "nomOrgao"],
    "codFuncao": ["txtDescricaoFuncao", "txtFuncao", "nomFuncao"],
    "codCategoria": ["txtDescricaoCategoria", "txtCategoria", "nomCategoria"],
}


def _primeira_coluna_existente(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _to_numeric(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce").fillna(0.0)


@st.cache_data(show_spinner="Consultando API SOF — pode demorar alguns minutos…")
def carregar_despesas(ano: int, mes: int) -> pd.DataFrame:
    return Despesas(ano_dotacao=ano, mes_dotacao=mes).dados


@st.cache_data(show_spinner="Carregando descrições…")
def carregar_orgaos(ano: int) -> pd.DataFrame:
    return Orgaos(ano=ano).dados


@st.cache_data(show_spinner="Carregando descrições…")
def carregar_funcoes(ano: int) -> pd.DataFrame:
    return Funcoes(ano=ano).dados


@st.cache_data(show_spinner="Carregando descrições…")
def carregar_categorias(ano: int) -> pd.DataFrame:
    return Categorias(ano=ano).dados


def normalizar_fases(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for fase, cands in VALOR_CANDIDATOS.items():
        col = _primeira_coluna_existente(df, cands)
        df[fase] = _to_numeric(df[col]) if col else 0.0
    return df


def mapa_descricoes(df_desc: pd.DataFrame, cod_col: str) -> dict[str, str]:
    if df_desc is None or df_desc.empty or cod_col not in df_desc.columns:
        return {}
    desc_col = _primeira_coluna_existente(df_desc, DESC_CANDIDATOS[cod_col])
    if desc_col is None:
        return {}
    return dict(zip(df_desc[cod_col].astype(str), df_desc[desc_col].astype(str)))


def formatar_brl(valor: float) -> str:
    s = f"R$ {valor:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_secao(
    df_all: pd.DataFrame,
    anos: list[int],
    dim_cod: str,
    fetcher_desc,
    titulo: str,
    rotulo_dim: str,
) -> None:
    st.header(titulo)

    if dim_cod not in df_all.columns:
        st.warning(
            f"O campo `{dim_cod}` não foi encontrado no retorno da API. "
            "Confira o formato dos dados retornados."
        )
        return

    ultimo_ano = max(anos)
    try:
        df_desc = fetcher_desc(ultimo_ano)
    except Exception as exc:
        st.warning(f"Não foi possível carregar descrições: {exc}")
        df_desc = pd.DataFrame()
    descricoes = mapa_descricoes(df_desc, dim_cod)

    df_x = df_all.copy()
    df_x[dim_cod] = df_x[dim_cod].astype(str)
    df_x[rotulo_dim] = df_x[dim_cod].map(descricoes).fillna(df_x[dim_cod])

    agg = (
        df_x.groupby(["Ano", dim_cod, rotulo_dim], as_index=False)[
            ["Empenhada", "Liquidada", "Paga"]
        ]
        .sum()
    )

    st.subheader("Totais por ano")
    for ano in sorted(anos):
        cols = st.columns(3)
        sub = agg[agg["Ano"] == ano]
        for i, fase in enumerate(["Empenhada", "Liquidada", "Paga"]):
            with cols[i]:
                st.metric(f"{fase} • {ano}", formatar_brl(sub[fase].sum()))

    st.subheader("Comparação entre anos — Top 15")
    fase_barra = st.selectbox(
        "Fase da despesa",
        ["Empenhada", "Liquidada", "Paga"],
        key=f"fase_barra_{titulo}",
    )
    top = (
        agg.groupby(rotulo_dim)[fase_barra]
        .sum()
        .nlargest(15)
        .index.tolist()
    )
    agg_top = agg[agg[rotulo_dim].isin(top)].copy()
    agg_top["Ano"] = agg_top["Ano"].astype(str)
    fig_bar = px.bar(
        agg_top.sort_values(fase_barra, ascending=False),
        x=rotulo_dim,
        y=fase_barra,
        color="Ano",
        barmode="group",
        title=f"Top 15 — {fase_barra}",
        labels={fase_barra: f"{fase_barra} (R$)"},
    )
    fig_bar.update_layout(xaxis_tickangle=-45, height=520)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader(f"Evolução por {rotulo_dim.lower()}")
    opcoes = sorted(agg[rotulo_dim].unique())
    default_sel = opcoes[: min(3, len(opcoes))]
    selecionados = st.multiselect(
        f"Selecione {rotulo_dim.lower()}(s) para visualizar a evolução",
        options=opcoes,
        default=default_sel,
        key=f"evol_sel_{titulo}",
    )
    if selecionados:
        df_evol = agg[agg[rotulo_dim].isin(selecionados)]
        df_long = df_evol.melt(
            id_vars=["Ano", rotulo_dim],
            value_vars=["Empenhada", "Liquidada", "Paga"],
            var_name="Fase",
            value_name="Valor",
        )
        fig_line = px.line(
            df_long.sort_values("Ano"),
            x="Ano",
            y="Valor",
            color=rotulo_dim,
            line_dash="Fase",
            markers=True,
            title="Evolução das fases por ano",
            labels={"Valor": "R$"},
        )
        fig_line.update_layout(height=520)
        st.plotly_chart(fig_line, use_container_width=True)

    with st.expander("Ver tabela agregada"):
        tabela = agg.copy()
        for fase in ["Empenhada", "Liquidada", "Paga"]:
            tabela[fase] = tabela[fase].map(formatar_brl)
        st.dataframe(tabela, use_container_width=True)


def main() -> None:
    st.title("Dashboard Orçamentário — Prefeitura de São Paulo")
    st.caption(
        "Fonte: API do SOF (Sistema Orçamentário Financeiro) da PMSP — "
        "valores em R$, agregados a partir de `consultarDespesas`."
    )

    erro_cred = _check_credentials()
    if erro_cred:
        st.error(erro_cred)
        st.stop()

    ano_atual = datetime.now().year
    with st.sidebar:
        st.header("Filtros")
        anos = st.multiselect(
            "Anos para comparação",
            options=list(range(2018, ano_atual + 1)),
            default=[ano_atual - 1, ano_atual],
            help="A API SOF disponibiliza dados a partir de 2003, mas os "
            "endpoints podem ter limites por ano.",
        )
        mes = st.slider(
            "Mês de referência (acumulado até)",
            min_value=1,
            max_value=12,
            value=12,
            help="A consulta de Despesas retorna valores acumulados até o mês "
            "indicado. Use 12 para fechamento anual.",
        )
        if st.button("Limpar cache e recarregar"):
            st.cache_data.clear()
            st.rerun()

    if not anos:
        st.info("Selecione ao menos um ano na barra lateral para começar.")
        st.stop()

    dfs: list[pd.DataFrame] = []
    erros: list[str] = []
    for ano in sorted(anos):
        try:
            df = carregar_despesas(ano, mes)
        except Exception as exc:
            erros.append(f"{ano}: {exc}")
            continue
        if df is None or df.empty:
            erros.append(f"{ano}: sem dados retornados.")
            continue
        df = normalizar_fases(df)
        df["Ano"] = ano
        dfs.append(df)

    if erros:
        for e in erros:
            st.warning(e)

    if not dfs:
        st.error("Não foi possível carregar dados para nenhum dos anos selecionados.")
        st.stop()

    df_all = pd.concat(dfs, ignore_index=True)

    aba_orgao, aba_funcao, aba_cat = st.tabs(
        [
            "Despesas por Órgão",
            "Despesas por Função",
            "Despesas por Categoria Econômica",
        ]
    )

    with aba_orgao:
        render_secao(
            df_all,
            anos,
            dim_cod="codOrgao",
            fetcher_desc=carregar_orgaos,
            titulo="Despesas por Órgão",
            rotulo_dim="Órgão",
        )

    with aba_funcao:
        render_secao(
            df_all,
            anos,
            dim_cod="codFuncao",
            fetcher_desc=carregar_funcoes,
            titulo="Despesas por Função",
            rotulo_dim="Função",
        )

    with aba_cat:
        render_secao(
            df_all,
            anos,
            dim_cod="codCategoria",
            fetcher_desc=carregar_categorias,
            titulo="Despesas por Categoria Econômica",
            rotulo_dim="Categoria",
        )


if __name__ == "__main__":
    main()
