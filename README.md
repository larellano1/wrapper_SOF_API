# wrapper_SOF_API
 wapper em python para a API do SOF (Sistema Orçamentário financeiro da Prefeitura Municipal de São Paulo). Parseia os jsons e gera dataframes e/ou .csvs para cada consulta disponível na API
 
 
## modulo = superclasse_api

Contém a superclasse que abstrai as consultas à API, parseia os Jsons gerando DataFrames e que inclui a possibilidade de criar .csvs que são escritos de formas incremental, linha por linha, conforme as requisições à API vão sendo realizadas (é útil para consultas muito grandes, para evitar estouro de memória e/ou perda dos dados devido a um possível erro na requisição).

## modulo = consultas_api

Contém as classes herdeiras da superclasse que replicam todas as consultas que podem ser realizadas à API, assim como seus respectivos parâmetros obrigatórios e opcionais

## Configuração da API SOF

A partir de **agosto/2023** a API SOF foi migrada da Prodam para a APILIB
da Prefeitura de São Paulo. O host antigo (`gatewayapi.prodam.sp.gov.br`) **não
funciona mais**. O novo host é `gateway.apilib.prefeitura.sp.gov.br` e exige
credenciais próprias.

### Passos para obter credenciais

1. Cadastre-se em https://apilib.prefeitura.sp.gov.br/store/
2. Crie uma aplicação e copie **Consumer Key** e **Consumer Secret**
3. Faça _subscribe_ na API **SOF** (na vitrine de APIs)
4. Copie o arquivo `.env.example` para `.env` na raiz do projeto e preencha:

   ```
   SOF_API_CONSUMER_KEY=sua_consumer_key
   SOF_API_CONSUMER_SECRET=sua_consumer_secret
   ```

   O wrapper se encarrega de obter e renovar tokens automaticamente.

   Alternativa rápida (token expira em 1h): cole um token gerado pela UI:
   ```
   SOF_API_TOKEN=eyJ...
   ```

## Dashboard orçamentário (Streamlit)

O arquivo `app.py` contém um dashboard em Streamlit que consome o wrapper e
apresenta as despesas da Prefeitura de São Paulo (Empenhada, Liquidada e Paga)
em três visões — **Órgão**, **Função** e **Categoria Econômica** — com
comparação entre anos e evolução temporal.

### Como executar

```bash
pip install -r requirements.txt
# configure o .env conforme seção acima
streamlit run app.py            # ou: python -m streamlit run app.py
```

Use a barra lateral para selecionar os anos a comparar e o mês de referência
(acumulado até). Os dados são cacheados em memória pelo Streamlit; o botão
"Limpar cache e recarregar" força um novo refetch da API.
