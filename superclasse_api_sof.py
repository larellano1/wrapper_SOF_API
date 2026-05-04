"""Superclasse para requisições à API SOF (Sistema Orçamentário Financeiro) da PMSP.

A API SOF foi migrada da Prodam para a APILIB da Prefeitura em agosto/2023:
    https://apilib.prefeitura.sp.gov.br/store/

Configuração via variáveis de ambiente (ou arquivo .env na raiz do projeto):

    SOF_API_BASE_URL          URL base da API
                              (default: https://gateway.apilib.prefeitura.sp.gov.br/sf/sof/v4)

    --- modo simples: token estático colado da UI da APILIB (expira em ~1h) ---
    SOF_API_TOKEN             access token Bearer

    --- modo recomendado: OAuth2 client credentials com refresh automático ---
    SOF_API_CONSUMER_KEY      consumer key da aplicação no APILIB
    SOF_API_CONSUMER_SECRET   consumer secret da aplicação no APILIB
    SOF_API_TOKEN_URL         endpoint de token
                              (default: https://gateway.apilib.prefeitura.sp.gov.br/token)

    SOF_API_VERIFY_SSL        "false" para desabilitar verificação SSL (default: true)
"""

from __future__ import annotations

import base64
import os
import time
from typing import Optional

import pandas as pd
import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class RequisicaoApi:
    """Abstrai requisições paginadas para a API SOF e devolve DataFrame.

    Mantém compatibilidade com as classes herdeiras em ``consultas_api_sof.py``.
    """

    DEFAULT_BASE_URL = (
        "https://gateway.apilib.prefeitura.sp.gov.br/sf/sof/v4"
    )
    DEFAULT_TOKEN_URL = "https://gateway.apilib.prefeitura.sp.gov.br/token"

    _cached_token: Optional[str] = None
    _cached_token_expires_at: float = 0.0

    @classmethod
    def _base_url(cls) -> str:
        return os.getenv("SOF_API_BASE_URL", cls.DEFAULT_BASE_URL).rstrip("/")

    @classmethod
    def _verify_ssl(cls) -> bool:
        return os.getenv("SOF_API_VERIFY_SSL", "true").lower() != "false"

    @classmethod
    def _get_token(cls) -> str:
        static_token = os.getenv("SOF_API_TOKEN")
        if static_token:
            return static_token

        ck = os.getenv("SOF_API_CONSUMER_KEY")
        cs = os.getenv("SOF_API_CONSUMER_SECRET")
        if not (ck and cs):
            raise RuntimeError(
                "API SOF não configurada. Defina SOF_API_TOKEN ou "
                "SOF_API_CONSUMER_KEY e SOF_API_CONSUMER_SECRET no ambiente "
                "(ou em um .env). Cadastro em "
                "https://apilib.prefeitura.sp.gov.br/store/"
            )

        now = time.time()
        if cls._cached_token and now < cls._cached_token_expires_at:
            return cls._cached_token

        token_url = os.getenv("SOF_API_TOKEN_URL", cls.DEFAULT_TOKEN_URL)
        basic = base64.b64encode(f"{ck}:{cs}".encode()).decode()
        resp = requests.post(
            token_url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
            timeout=30,
            verify=cls._verify_ssl(),
        )
        resp.raise_for_status()
        body = resp.json()
        cls._cached_token = body["access_token"]
        cls._cached_token_expires_at = now + int(body.get("expires_in", 3600)) - 60
        return cls._cached_token

    def __aux_dict_consulta(self, dict_consulta):
        if not dict_consulta:
            return ""
        return "&".join(f"{k}={v}" for k, v in dict_consulta.items())

    def __requisicao(self, num_pag, consulta, dict_consulta=""):
        params_str = self.__aux_dict_consulta(dict_consulta)
        base = self._base_url()
        if params_str:
            url = f"{base}/{consulta}?{params_str}&numPagina={num_pag}"
        else:
            url = f"{base}/{consulta}?numPagina={num_pag}"

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "User-Agent": "wrapper-sof-api/1.0",
            "Accept": "application/json",
        }

        with requests.get(
            url, headers=headers, timeout=60, verify=self._verify_ssl()
        ) as r:
            r.raise_for_status()
            return r.json()

    def __formater_csv(self, dados, key_dados):
        if dados["metadados"]["txtStatus"] == "ERRO":
            return dados["metadados"]["txtMensagemErro"]

        valores = [c for c in dados[key_dados]]
        dic_dados = {coluna: [] for coluna in list(valores[0].keys())}

        for valor in valores:
            for key, value in valor.items():
                value = str(value)
                value = value.replace("\n", " ")
                value = value.replace(";", ",")
                value = value.replace("\r", " ")
                dic_dados[key].append(value)

        return dic_dados

    def __aux_csv_writer(self, colunas, dados_requisi, key_dados, consulta):
        dici = self.__formater_csv(dados_requisi, key_dados)

        with open("dados_{}.csv".format(consulta), "a") as f:
            for col in colunas:
                for z in range(len(dici[colunas[0]])):
                    line = [str(dici[col][z]) for col in colunas]
                    f.write(";".join(line) + "\n")

    def puxar_todos_valores(self, key_dados, consulta, dict_consulta, csv=False):
        """Consome todas as páginas da consulta e devolve DataFrame consolidado."""

        dados = []

        primeira_requisicao = self.__requisicao(1, consulta, dict_consulta)

        if primeira_requisicao.get("metadados", {}).get("txtStatus") == "ERRO":
            raise RuntimeError(
                "API SOF retornou erro na primeira página: "
                f"{primeira_requisicao['metadados'].get('txtMensagemErro')}"
            )

        if not primeira_requisicao.get(key_dados):
            return pd.DataFrame()

        qtd_paginas = primeira_requisicao["metadados"]["qtdPaginas"]
        print("O total de paginas é :::" + str(qtd_paginas))

        if csv:
            colunas = [
                str(coluna) for coluna in list(primeira_requisicao[key_dados][0].keys())
            ]

            with open("dados_{}.csv".format(consulta), "w") as f:
                f.write(";".join(colunas) + "\n")

        for i in range(1, qtd_paginas + 1):
            dados_requisi = self.__requisicao(i, consulta, dict_consulta)
            if dados_requisi["metadados"]["txtStatus"] == "ERRO":
                print(
                    "ERRO - pagina {pg} - txt erro :: {erro}".format(
                        pg=i, erro=dados_requisi["metadados"]["txtMensagemErro"]
                    )
                )
            else:
                dados.append(dados_requisi[key_dados])
                if csv:
                    self.__aux_csv_writer(colunas, dados_requisi, key_dados, consulta)

        dados = [dic_ for lista in dados for dic_ in lista]

        return pd.DataFrame(dados)
