# wrapper_SOF_API

Repositório com dois usos principais:

1. **Dashboard orçamentário** (Streamlit) que lê do CSV consolidado da Execução
   Orçamentária da Prefeitura de São Paulo via SQLite local.
2. **Wrapper Python da API SOF** (Sistema de Orçamento e Finanças) para
   consultas pontuais granulares (empenhos por contrato, liquidações por
   empenho, etc.) — útil quando o CSV consolidado não atende.

## Dashboard orçamentário (Streamlit)

O `app.py` apresenta despesas (Empenhada líquida, Liquidada e Paga) em três
visões — **Órgão**, **Função** e **Categoria Econômica** — com comparação
entre anos e evolução temporal.

A fonte é o CSV consolidado disponível em
`https://orcamento.prefeitura.sp.gov.br/orcamento/uploads/<ano>/basedadosexecucaoConsolidadosComRestos_<mmaa>.csv`,
que cobre **2003 até o ano corrente** num único arquivo (~200 MB) e é regerado
mensalmente.

### Como executar

```bash
pip install -r requirements.txt

# 1) Baixa o CSV mais recente e popula o SQLite local (despesas.db).
#    Pode levar alguns minutos por causa do download e do parse.
python etl_orcamento.py

# 2) Sobe o dashboard, que lê de despesas.db.
streamlit run app.py            # ou: python -m streamlit run app.py
```

### Opções do ETL

```bash
python etl_orcamento.py --discover   # detecta o CSV mais recente automaticamente
python etl_orcamento.py --url <url>  # força URL específica
python etl_orcamento.py --csv data/x.csv  # usa CSV local, sem download
python etl_orcamento.py --force      # rebaixa mesmo se já houver cache
```

A URL default também pode ser sobrescrita via variável de ambiente
`ORCAMENTO_CSV_URL`. Para automatizar atualização diária, agende
`python etl_orcamento.py --discover` em cron/systemd-timer — antes de
baixar, o ETL faz um `HEAD` no servidor e compara o `Last-Modified` com
o mtime do cache local; se nada mudou, sai em poucos segundos sem
rebaixar 200 MB nem reprocessar o BD.

## Wrapper da API SOF (uso opcional)

Para consultas granulares à API SOF v4 (host `gateway.apilib.prefeitura.sp.gov.br`),
use as classes em `consultas_api_sof.py` (ex.: `Empenhos`, `Liquidacoes`,
`Contratos`).

### Credenciais

1. Cadastre-se em https://apilib.prefeitura.sp.gov.br/store/
2. Crie uma aplicação e copie **Consumer Key** e **Consumer Secret**
3. Faça _subscribe_ na API **SOF** (na vitrine de APIs)
4. Copie `.env.example` para `.env` e preencha:

   ```
   SOF_API_CONSUMER_KEY=sua_consumer_key
   SOF_API_CONSUMER_SECRET=sua_consumer_secret
   ```

   O wrapper renova tokens automaticamente.

   Alternativa rápida (token expira em 1h):
   ```
   SOF_API_TOKEN=eyJ...
   ```

### Módulos

- `superclasse_api_sof.py` — `RequisicaoApi` abstrai paginação, autenticação
  e parsing JSON para DataFrame.
- `consultas_api_sof.py` — classes herdeiras (`Empenhos`, `Despesas`,
  `Contratos`, etc.) com os parâmetros de cada endpoint v4.

Ver `CLAUDE.md` para a referência completa dos endpoints disponíveis.
