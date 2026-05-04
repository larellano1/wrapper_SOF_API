"""Dashboard Orçamentário da Prefeitura de São Paulo.

Lê dados de um SQLite local (`despesas.db`) populado por `etl_orcamento.py`
a partir do CSV consolidado da Execução Orçamentária da PMSP.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = Path(__file__).parent / "despesas.db"
TABLE = "execucao"

st.set_page_config(
    page_title="Dashboard Orçamentário - PMSP",
    page_icon=":bar_chart:",
    layout="wide",
)


@st.cache_data
def listar_anos_disponiveis() -> list[int]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT DISTINCT Cd_Exercicio FROM {TABLE} "
        "WHERE Cd_Exercicio IS NOT NULL ORDER BY Cd_Exercicio",
        conn,
    )
    conn.close()
    anos = []
    for valor in df["Cd_Exercicio"]:
        try:
            anos.append(int(valor))
        except (TypeError, ValueError):
            continue
    return anos


@st.cache_data(show_spinner="Lendo dados do BD local...")
def carregar_agregado(anos: tuple[int, ...]) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(anos))
    query = f"""
        SELECT
            CAST(Cd_Exercicio AS INTEGER) AS Ano,
            Cd_Orgao,
            Ds_Orgao,
            Cd_Funcao,
            Ds_Funcao,
            Categoria_Despesa AS Cd_Categoria,
            Ds_Categoria,
            SUM(Vl_EmpenhadoLiquido) AS Empenhada,
            SUM(Vl_Liquidado) AS Liquidada,
            SUM(Vl_Pago) AS Paga
        FROM {TABLE}
        WHERE CAST(Cd_Exercicio AS INTEGER) IN ({placeholders})
        GROUP BY Cd_Exercicio, Cd_Orgao, Ds_Orgao, Cd_Funcao, Ds_Funcao,
                 Categoria_Despesa, Ds_Categoria
    """
    df = pd.read_sql(query, conn, params=list(anos))
    conn.close()
    return df


def formatar_brl(valor: float) -> str:
    s = f"R$ {valor:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_secao(
    df_all: pd.DataFrame,
    anos: list[int],
    cod_col: str,
    desc_col: str,
    titulo: str,
    rotulo_dim: str,
) -> None:
    st.header(titulo)
    df = df_all.copy()
    df[cod_col] = df[cod_col].astype(str)
    df[rotulo_dim] = df[desc_col].fillna(df[cod_col])

    agg = (
        df.groupby(["Ano", cod_col, rotulo_dim], as_index=False)[
            ["Empenhada", "Liquidada", "Paga"]
        ].sum()
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
        agg.groupby(rotulo_dim)[fase_barra].sum().nlargest(15).index.tolist()
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
        "Fonte: Base de Dados da Execução Orçamentária (CSV consolidado, "
        "`orcamento.prefeitura.sp.gov.br`) — carregada em SQLite local "
        "via `etl_orcamento.py`. Valores: Empenhada (líquida), Liquidada e Paga."
    )

    anos_disp = listar_anos_disponiveis()
    if not anos_disp:
        st.error(
            f"Banco de dados local não encontrado em `{DB_PATH}`. "
            "Execute primeiro: `python etl_orcamento.py` para baixar o CSV "
            "e popular o SQLite."
        )
        st.stop()

    with st.sidebar:
        st.header("Filtros")
        max_ano = max(anos_disp)
        default_anos = (
            [max_ano - 1, max_ano] if (max_ano - 1) in anos_disp else [max_ano]
        )
        anos = st.multiselect(
            "Anos para comparação",
            options=anos_disp,
            default=default_anos,
        )
        if st.button("Limpar cache e recarregar"):
            st.cache_data.clear()
            st.rerun()

    if not anos:
        st.info("Selecione ao menos um ano na barra lateral para começar.")
        st.stop()

    df_all = carregar_agregado(tuple(sorted(anos)))
    if df_all.empty:
        st.error("Nenhum dado encontrado para os anos selecionados.")
        st.stop()

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
            cod_col="Cd_Orgao",
            desc_col="Ds_Orgao",
            titulo="Despesas por Órgão",
            rotulo_dim="Órgão",
        )

    with aba_funcao:
        render_secao(
            df_all,
            anos,
            cod_col="Cd_Funcao",
            desc_col="Ds_Funcao",
            titulo="Despesas por Função",
            rotulo_dim="Função",
        )

    with aba_cat:
        render_secao(
            df_all,
            anos,
            cod_col="Cd_Categoria",
            desc_col="Ds_Categoria",
            titulo="Despesas por Categoria Econômica",
            rotulo_dim="Categoria",
        )


if __name__ == "__main__":
    main()
