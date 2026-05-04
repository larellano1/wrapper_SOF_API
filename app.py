"""Dashboard Orçamentário da Prefeitura de São Paulo.

Lê dados de um SQLite local (`despesas.db`) populado por `etl_orcamento.py`
a partir do CSV consolidado da Execução Orçamentária da PMSP.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

DB_PATH = Path(__file__).parent / "despesas.db"
TABLE = "execucao"

FASES = ["Orçada", "Atualizada", "Empenhada", "Liquidada", "Paga", "Disponível"]
FASES_FLUXO = ["Empenhada", "Liquidada", "Paga"]
MESES_PT = [
    "", "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]

UNIDADES = {
    "R$": (1.0, "R$"),
    "R$ milhões": (1_000_000.0, "R$ mi"),
    "R$ bilhões": (1_000_000_000.0, "R$ bi"),
}

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


def _parse_data_pt(valor: str) -> datetime | None:
    if not valor or valor.lower() in {"none", "nan", "nat"}:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(valor, fmt)
        except ValueError:
            continue
    return None


@st.cache_data
def mes_de_corte_por_ano() -> dict[int, int]:
    """Retorna {ano: mês_máximo_de_DataFinal} a partir do BD.

    Para anos passados normalmente é 12 (snapshot final do exercício); para o
    ano corrente, é o mês da última extração.
    """
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT Cd_Exercicio, MAX(DataFinal) AS DataFinal FROM {TABLE} "
        "WHERE DataFinal IS NOT NULL GROUP BY Cd_Exercicio",
        conn,
    )
    conn.close()
    cortes: dict[int, int] = {}
    for row in df.itertuples():
        try:
            ano = int(row.Cd_Exercicio)
        except (TypeError, ValueError):
            continue
        d = _parse_data_pt(str(row.DataFinal))
        if d is not None:
            cortes[ano] = d.month
    return cortes


@st.cache_data
def listar_orgaos_disponiveis() -> list[tuple[str, str]]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        f"SELECT DISTINCT Cd_Orgao, Ds_Orgao FROM {TABLE} "
        "WHERE Cd_Orgao IS NOT NULL "
        "ORDER BY CAST(Cd_Orgao AS INTEGER)",
        conn,
    )
    conn.close()
    return [
        (str(row.Cd_Orgao), str(row.Ds_Orgao) if row.Ds_Orgao else "")
        for row in df.itertuples()
    ]


@st.cache_data(show_spinner="Lendo dados do BD local...")
def carregar_agregado(
    anos: tuple[int, ...],
    fontes: tuple[str, ...] = (),
    orgaos: tuple[str, ...] = (),
) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    placeholders_anos = ",".join("?" * len(anos))
    params: list = list(anos)
    where_extra = ""
    if fontes:
        placeholders_fontes = ",".join("?" * len(fontes))
        where_extra += f" AND Cd_Fonte IN ({placeholders_fontes})"
        params.extend(fontes)
    if orgaos:
        placeholders_orgaos = ",".join("?" * len(orgaos))
        where_extra += f" AND Cd_Orgao IN ({placeholders_orgaos})"
        params.extend(orgaos)
    query = f"""
        SELECT
            CAST(Cd_Exercicio AS INTEGER) AS Ano,
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
            SUM(Vl_Pago) AS Paga,
            SUM(Disponivel) AS "Disponível"
        FROM {TABLE}
        WHERE CAST(Cd_Exercicio AS INTEGER) IN ({placeholders_anos}){where_extra}
        GROUP BY Cd_Exercicio, Cd_Funcao, Ds_Funcao,
                 Categoria_Despesa, Ds_Categoria, Grupo_Despesa, Ds_Grupo
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


def aplicar_anualizacao(
    df: pd.DataFrame, cortes: dict[int, int]
) -> tuple[pd.DataFrame, dict[int, float]]:
    """Multiplica fases de fluxo do ano corrente por (12 / mês_corte).

    Retorna o DataFrame ajustado e um dict {ano: fator} para exibição.
    """
    df = df.copy()
    fatores: dict[int, float] = {}
    for ano, mes in cortes.items():
        if not mes or mes >= 12:
            continue
        fator = 12 / mes
        fatores[ano] = fator
        mask = df["Ano"] == ano
        for fase in FASES_FLUXO:
            df.loc[mask, fase] = df.loc[mask, fase] * fator
    return df, fatores


def formatar_brl(valor: float, divisor: float = 1.0) -> str:
    v = valor / divisor
    casas = 0 if divisor == 1.0 else 2
    s = f"R$ {v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_secao(
    df_all: pd.DataFrame,
    anos: list[int],
    cod_col: str,
    desc_col: str,
    titulo: str,
    rotulo_dim: str,
    unidade: tuple[float, str] = (1.0, "R$"),
) -> None:
    divisor, sufixo = unidade
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
                st.metric(
                    f"{fase} • {ano}",
                    formatar_brl(sub[fase].sum(), divisor),
                )

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
    agg_plot = agg_top.sort_values(["Ano", rotulo_dim]).copy()
    agg_plot[fase_barra] = agg_plot[fase_barra] / divisor
    fig_bar = px.bar(
        agg_plot,
        x=rotulo_dim,
        y=fase_barra,
        color="Ano",
        barmode="group",
        title=f"Top 15 — {fase_barra}",
        labels={fase_barra: f"{fase_barra} ({sufixo})"},
        category_orders={rotulo_dim: ordem_categorias, "Ano": ordem_anos},
    )
    fig_bar.update_layout(xaxis_tickangle=-45, height=520)
    st.plotly_chart(fig_bar, use_container_width=True)

    with st.expander("Ver tabela agregada"):
        tabela = agg.copy()
        for fase in FASES:
            tabela[fase] = tabela[fase].map(
                lambda v, d=divisor: formatar_brl(v, d)
            )
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
    orgaos_disp = listar_orgaos_disponiveis()
    orgao_label_to_cod = {
        f"{cod} — {desc}" if desc else cod: cod for cod, desc in orgaos_disp
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
        orgaos_labels = st.multiselect(
            "Órgão",
            options=list(orgao_label_to_cod.keys()),
            default=[],
            help="Vazio = todos os órgãos.",
        )
        fontes_labels = st.multiselect(
            "Fonte de recurso",
            options=list(fonte_label_to_cod.keys()),
            default=[],
            help="Vazio = todas as fontes.",
        )
        unidade_label = st.radio(
            "Unidade de medida",
            options=list(UNIDADES.keys()),
            index=2,
        )
        modo_comparacao = st.radio(
            "Modo de comparação",
            options=["Acumulado", "Anualizado"],
            index=0,
            help=(
                "Acumulado: valores como estão no BD (ano corrente parcial). "
                "Anualizado: Empenhada / Liquidada / Paga do ano corrente "
                "são escaladas por 12 ÷ mês_corte para projetar o ano cheio. "
                "Orçada, Atualizada e Disponível não são afetadas."
            ),
        )
        if st.button("Limpar cache e recarregar"):
            st.cache_data.clear()
            st.rerun()

    if not anos:
        st.info("Selecione ao menos um ano na barra lateral para começar.")
        st.stop()

    fontes_codigos = tuple(fonte_label_to_cod[lbl] for lbl in fontes_labels)
    orgaos_codigos = tuple(orgao_label_to_cod[lbl] for lbl in orgaos_labels)
    unidade = UNIDADES[unidade_label]
    df_all = carregar_agregado(
        tuple(sorted(anos)), fontes_codigos, orgaos_codigos
    )
    if df_all.empty:
        st.error("Nenhum dado encontrado para os filtros selecionados.")
        st.stop()

    if modo_comparacao == "Anualizado":
        cortes = mes_de_corte_por_ano()
        df_all, fatores = aplicar_anualizacao(df_all, cortes)
        if fatores:
            partes = [
                f"{ano} ×{fator:.2f} (snapshot até {MESES_PT[cortes[ano]]})"
                for ano, fator in sorted(fatores.items())
            ]
            st.info(
                "Modo **Anualizado** ativo — Empenhada/Liquidada/Paga foram "
                "projetadas para o ano cheio: " + "; ".join(partes) + ". "
                "Orçada, Atualizada e Disponível permanecem inalteradas."
            )
        else:
            st.caption(
                "Modo Anualizado: nenhum ano selecionado é parcial; "
                "valores idênticos ao modo Acumulado."
            )

    aba_funcao, aba_cat = st.tabs(
        [
            "Despesas por Função",
            "Despesas por Categoria Econômica",
        ]
    )

    with aba_funcao:
        render_secao(
            df_all,
            anos,
            cod_col="Cd_Funcao",
            desc_col="Ds_Funcao",
            titulo="Despesas por Função",
            rotulo_dim="Função",
            unidade=unidade,
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
            unidade=unidade,
        )


if __name__ == "__main__":
    main()
