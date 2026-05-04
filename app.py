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

FASES = ["Orçada", "Atualizada", "Empenhada", "Liquidada", "Paga"]

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


@st.cache_data
def listar_fontes_disponiveis() -> list[tuple[str, str]]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT DISTINCT Cd_Fonte, Ds_Fonte FROM {TABLE} "
        "WHERE Cd_Fonte IS NOT NULL "
        "ORDER BY CAST(Cd_Fonte AS INTEGER)",
        conn,
    )
    conn.close()
    return [
        (str(row.Cd_Fonte), str(row.Ds_Fonte) if row.Ds_Fonte else "")
        for row in df.itertuples()
    ]


@st.cache_data(show_spinner="Lendo dados do BD local...")
def carregar_agregado(
    anos: tuple[int, ...], fontes: tuple[str, ...] = ()
) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    placeholders_anos = ",".join("?" * len(anos))
    params: list = list(anos)
    where_extra = ""
    if fontes:
        placeholders_fontes = ",".join("?" * len(fontes))
        where_extra = f" AND Cd_Fonte IN ({placeholders_fontes})"
        params.extend(fontes)
    query = f"""
        SELECT
            CAST(Cd_Exercicio AS INTEGER) AS Ano,
            Cd_Orgao,
            Ds_Orgao,
            Cd_Funcao,
            Ds_Funcao,
            Categoria_Despesa AS Cd_Categoria,
            Ds_Categoria,
            Grupo_Despesa AS Cd_Grupo,
            Ds_Grupo,
            SUM(Vl_Orcado_Ano) AS "Orçada",
            SUM(Vl_Orcado_Atualizado) AS "Atualizada",
            SUM(Vl_EmpenhadoLiquido) AS Empenhada,
            SUM(Vl_Liquidado) AS Liquidada,
            SUM(Vl_Pago) AS Paga
        FROM {TABLE}
        WHERE CAST(Cd_Exercicio AS INTEGER) IN ({placeholders_anos}){where_extra}
        GROUP BY Cd_Exercicio, Cd_Orgao, Ds_Orgao, Cd_Funcao, Ds_Funcao,
                 Categoria_Despesa, Ds_Categoria, Grupo_Despesa, Ds_Grupo
    """
    df = pd.read_sql(query, conn, params=params)
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
        df.groupby(["Ano", cod_col, rotulo_dim], as_index=False)[FASES].sum()
    )

    st.subheader("Totais por ano")
    for ano in sorted(anos):
        cols = st.columns(len(FASES))
        sub = agg[agg["Ano"] == ano]
        for i, fase in enumerate(FASES):
            with cols[i]:
                st.metric(f"{fase} • {ano}", formatar_brl(sub[fase].sum()))

    st.subheader("Comparação entre anos — Top 15")
    fase_barra = st.selectbox(
        "Fase da despesa",
        FASES,
        index=FASES.index("Empenhada"),
        key=f"fase_barra_{titulo}",
    )
    top = (
        agg.groupby(rotulo_dim)[fase_barra].sum().nlargest(15).index.tolist()
    )
    agg_top = agg[agg[rotulo_dim].isin(top)].copy()
    agg_top["Ano"] = agg_top["Ano"].astype(str)
    ordem_categorias = (
        agg_top.groupby(rotulo_dim)[fase_barra]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )
    ordem_anos = [str(a) for a in sorted(anos)]
    fig_bar = px.bar(
        agg_top.sort_values(["Ano", rotulo_dim]),
        x=rotulo_dim,
        y=fase_barra,
        color="Ano",
        barmode="group",
        title=f"Top 15 — {fase_barra}",
        labels={fase_barra: f"{fase_barra} (R$)"},
        category_orders={rotulo_dim: ordem_categorias, "Ano": ordem_anos},
    )
    fig_bar.update_layout(xaxis_tickangle=-45, height=520)
    st.plotly_chart(fig_bar, use_container_width=True)

    with st.expander("Ver tabela agregada"):
        tabela = agg.copy()
        for fase in FASES:
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

    fontes_disp = listar_fontes_disponiveis()
    fonte_label_to_cod = {
        f"{cod} — {desc}" if desc else cod: cod for cod, desc in fontes_disp
    }

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
        fontes_labels = st.multiselect(
            "Fonte de recurso",
            options=list(fonte_label_to_cod.keys()),
            default=[],
            help="Vazio = todas as fontes.",
        )
        if st.button("Limpar cache e recarregar"):
            st.cache_data.clear()
            st.rerun()

    if not anos:
        st.info("Selecione ao menos um ano na barra lateral para começar.")
        st.stop()

    fontes_codigos = tuple(fonte_label_to_cod[lbl] for lbl in fontes_labels)
    df_all = carregar_agregado(tuple(sorted(anos)), fontes_codigos)
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
        nivel = st.radio(
            "Nível de detalhe",
            options=["Categoria Econômica", "Grupo de Despesa"],
            horizontal=True,
            key="nivel_categoria",
        )
        if nivel == "Categoria Econômica":
            cod_col, desc_col, rotulo = "Cd_Categoria", "Ds_Categoria", "Categoria"
        else:
            cod_col, desc_col, rotulo = "Cd_Grupo", "Ds_Grupo", "Grupo"
        render_secao(
            df_all,
            anos,
            cod_col=cod_col,
            desc_col=desc_col,
            titulo=f"Despesas por {nivel}",
            rotulo_dim=rotulo,
        )


if __name__ == "__main__":
    main()
