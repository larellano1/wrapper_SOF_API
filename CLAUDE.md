# Projeto: Integração com SOF API (Prefeitura de São Paulo)

Este projeto integra com a **SOF API v4** — Sistema de Orçamento e Finanças da Prefeitura de São Paulo, mantida pela SUTEM (Subsecretaria do Tesouro Municipal). A API expõe dados de execução orçamentária (despesa e receita) do município desde 2003.

## Manual de referência

O manual oficial completo está em `docs/2024_09_16_MANUAL_SOF_API.pdf` (versão 4.0.0, set/2024). **Antes de implementar qualquer endpoint novo, leia as seções relevantes do PDF** — não confie apenas neste resumo para detalhes de campos de retorno ou parâmetros menos comuns.

## Visão geral da API

- **Padrão**: Web Service REST, método `GET`, retorno `JSON`.
- **Base URL**: `https://gateway.apilib.prefeitura.sp.gov.br/sf/sof/v4`
- **Autenticação**: Bearer token no header `Authorization`.
  - Modelo: `Authorization: Bearer <token>`
  - Token gerado em https://apilib.prefeitura.sp.gov.br via cadastro de aplicação e inscrição na API SOF.
  - Validade do token configurável (padrão 3600s; usar `-1` no campo "Período de validade" para máximo).
- **Formato de URL com filtros**:
  ```
  https://gateway.apilib.prefeitura.sp.gov.br/sf/sof/v4/<consulta>?<param1>=<valor1>&<param2>=<valor2>
  ```

## Estrutura de retorno (padrão em TODAS as consultas)

```json
{
  "metaDados": {
    "txtStatus": "OK | SEM_REGISTROS | ERRO",
    "txtMensagemErro": "",
    "qtdPaginas": 1
  },
  "lst<NomeDaConsulta>": [ { ... }, { ... } ]
}
```

- **Atenção**: a chave do envelope é `metaDados` (D maiúsculo) na resposta real, embora o manual PDF a grafe como `metadados`. Use `metaDados` ao acessar.
- `txtStatus`: `OK` (sucesso com dados), `SEM_REGISTROS` (sucesso sem dados), `ERRO` (falha no processamento — checar `txtMensagemErro`).
- `qtdPaginas`: número total de páginas de resultado.
- A lista de dados tem nome variável conforme a consulta (ex: `lstDespesas`, `lstEmpenhos`, `lstContratos`).

## Paginação

- Cada página retorna **no máximo 50 registros**.
- Consultas com menos de 50 registros têm apenas 1 página.
- Para acessar páginas seguintes, refazer a chamada incluindo o parâmetro `numPagina=<N>`.
- Se `qtdPaginas > 1` e `numPagina` não for informado, retorna a primeira página.
- **Sempre implementar paginação** em código que possa retornar volumes grandes (despesas, empenhos, contratos, credores).

## Convenções de nomenclatura

A API usa prefixos consistentes nos campos (úteis para tipagem em código):

- `cod*` — códigos identificadores (ex: `codEmpenho`, `codOrgao`, `codContrato`)
- `num*` — números de identificação ou contagem (ex: `numCpfCnpj`, `numProcesso`, `numPagina`)
- `dat*` — datas, geralmente no formato string `dd/mm/aaaa` (ex: `datEmpenho`, `datVigencia`)
- `val*` — valores monetários, geralmente `Decimal(18,2)` (ex: `valLiquidado`, `valTotalEmpenhado`)
- `txt*` — descrições textuais (ex: `txtRazaoSocial`, `txtDescricaoOrgao`)
- `ano*` / `mes*` — ano/mês de exercício ou movimento

## Endpoints disponíveis

### Consultas de execução orçamentária
| Endpoint | Descrição | Obrigatórios |
|---|---|---|
| `/despesas` | Dotação orçamentária | `anoDotacao`, `mesDotacao` |
| `/empenhos` | Empenhos | `anoEmpenho`, `mesEmpenho` |
| `/contratos` | Contratos (desde 2006) | `anoContrato` |
| `/despesasCredor` | Despesa agregada por credor | `anoExercicio`, `mesEmpenho` |
| `/liquidacoes` | Liquidações de empenho | `codEmpenho`, `anoEmpenho`, `codEmpresa` |
| `/movimentosReceita` | Receita arrecadada | `anoExercicio` |
| `/compromissosPagar` | Compromissos a pagar (novo na v4) | `anoEmpenho` |
| `/movimentoCartoesDeDespesa` | Movimento de cartões de despesa | `dataInicio`, `dataFinal` |
| `/cartoesDeDespesas` | Cartões de despesa | nenhum obrigatório, mas pelo menos 1 eletivo |

### Consultas cadastrais (16 ao todo)
| Endpoint | Descrição | Obrigatórios |
|---|---|---|
| `/credores` | Credores (CPF/CNPJ) | nenhum |
| `/credoresDeContrato` | Credores de um contrato específico | `anoExercicio`, `codEmpresa`, `codContrato` |
| `/contasReceita` | Contas de receita | `anoExercicio` |
| `/empresas` | Entidades da administração municipal | `anoExercicio` |
| `/orgaos` | Órgãos | `anoExercicio` |
| `/unidades` | Unidades orçamentárias | `codOrgao`, `anoExercicio` |
| `/funcoes` | Funções de governo | `anoExercicio` |
| `/subFuncoes` | Subfunções | `anoExercicio` |
| `/programas` | Programas de governo | `anoExercicio` |
| `/projetosAtividades` | Projetos/atividades | `anoExercicio` |
| `/categorias` | Categorias econômicas | `anoExercicio` |
| `/grupos` | Grupos de despesa | `anoExercicio` |
| `/modalidades` | Modalidades de aplicação | `anoExercicio` |
| `/elementos` | Elementos de despesa | `anoExercicio` |
| `/subElementos` | Subelementos | `codCategoria`, `codGrupo`, `codModalidade`, `codElemento`, `anoExercicio` |
| `/itensDespesa` | Itens de despesa | `codCategoria`, `codGrupo`, `codModalidade`, `codElemento`, `codSubElemento`, `anoExercicio` |
| `/fonteRecursos` | Fontes de recurso | `anoExercicio` |

## Conceitos-chave do orçamento público municipal

Estes conceitos aparecem nos campos de retorno e são essenciais para interpretar os dados:

**Hierarquia institucional**: Empresa → Órgão → Unidade. `codEmpresa` é o código da entidade da administração municipal; `codOrgao` é a desagregação setorial; `codUnidade` é a divisão administrativa do órgão.

**Hierarquia funcional/programática**: Função → Subfunção → Programa → Projeto/Atividade. Função é a alocação temática (saúde, educação, etc.); programa é o conjunto de atividades para atender uma função.

**Classificação econômica da despesa**: Categoria (Correntes/Capital) → Grupo (1-Pessoal e Encargos, 2-Juros e Encargos da Dívida, 3-Outras Despesas Correntes, 4-Investimentos, 5-Inversões Financeiras, 6-Amortização da Dívida) → Modalidade (aplicação direta vs. transferência) → Elemento → Subelemento → Item de despesa.

**Estágios da despesa**: Orçamento (`valOrcadoInicial` → `valOrcadoAtualizado` após suplementações/reduções) → Reserva (`valReservado`) → Empenho (`valTotalEmpenhado` / `valEmpenhadoLiquido` = empenhado menos cancelamentos) → Liquidação (`valLiquidado` — verificação de que o objeto foi entregue) → Pagamento (`valPagoExercicio` no mesmo ano, `valPagoRestos` em exercícios subsequentes).

**Modalidades de licitação** (`codModalidade`): 1-Concurso, 2-Convite, 3-Tomada de Preços, 4-Concorrência, 6-Dispensa de Licitação, 7-Inexigibilidade, 9-Adiantamento/Suprimento de Fundos, 12-Pregão, 13-Leilão.

**Tipos de contratação** (`codTipoContratacao`): 1-Sem Ônus, 2-Termo de Contrato, 3-Termo de Co-patrocínio, 4-Termo de Convênio, 5-Nota de Empenho, 6-Ordem de Compra, 7-Termo de Cooperação, 8-Ordem de Execução de Serviço, 9-Contrato da Dívida, 10-Contratação com Receita, 12-Contrato de Gestão, 13-Termo de Parceria, 14-Termo de Compromisso de Concessão de Incentivo, 15-Termo de Compromisso PTRF, 16-Termo de Matrícula ao Curso de Residência Médica, 17-Termo de Adesão PDDE, 18-Termo de Compromisso e Cooperação Financeira-Vinc Confissão Dívida, 19-Termo de Permissão Onerosa de Uso, 20-Termo de Carta-Contrato, 21-Termo de Repasse PNAE.

**Natureza jurídica do credor** (`txtTipoNatureza` / `txtTipoFornecedor`): `F` = Física, `J` = Jurídica, `E` = Especial.

## Ressalvas importantes sobre os dados

- Dados disponíveis desde **2003** (despesa e receita); contratos desde **2006**.
- A **Secretaria Municipal da Saúde (órgão 18)** foi sucedida pelo **Fundo Municipal da Saúde (órgão 84)** a partir de 2013. Ainda há resíduos da Ação 4121 no órgão 18 em 2013, migrando para 84 em 2014. Consultas históricas devem considerar ambos.
- **Câmara Municipal e Tribunal de Contas do Município** executam orçamento em sistemas próprios — apenas resultados de despesas são consolidados no SOF. **Não há dados de contratos e empenhos** para essas entidades.
- `datAssinaturaContrato` e `datPublicacaoContrato` **não são campos obrigatórios** no SOF — podem vir vazios.
- `codProcesso` pode ter 12 ou 16 dígitos (Simproc físico vs. SEI digital).
- Quando o parâmetro `Mês` é solicitado, o retorno é **acumulado até aquela competência**, não o valor isolado do mês.

## Padrões de uso recomendados

### Cliente HTTP genérico (Python)

```python
import requests
from typing import Optional

BASE_URL = "https://gateway.apilib.prefeitura.sp.gov.br/sf/sof/v4"

class SOFClient:
    def __init__(self, token: str):
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, endpoint: str, **params) -> dict:
        # Remove params None para não poluir a query string
        params = {k: v for k, v in params.items() if v is not None}
        r = requests.get(f"{BASE_URL}/{endpoint}", headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data["metadados"]["txtStatus"] == "ERRO":
            raise RuntimeError(data["metadados"]["txtMensagemErro"])
        return data

    def get_all_pages(self, endpoint: str, list_key: str, **params) -> list:
        """Itera por todas as páginas e retorna lista completa."""
        results = []
        page = 1
        while True:
            data = self.get(endpoint, numPagina=page, **params)
            results.extend(data.get(list_key, []))
            if page >= data["metadados"]["qtdPaginas"]:
                break
            page += 1
        return results
```

### Boas práticas
- **Sempre paginar** em consultas que possam ter `qtdPaginas > 1`.
- **Validar `txtStatus`** antes de processar a lista — `SEM_REGISTROS` é normal e não deve ser tratado como erro.
- **Cachear consultas cadastrais** (órgãos, funções, programas, etc.) — mudam pouco dentro de um exercício.
- **Não armazenar o token em código** — usar variável de ambiente (`SOF_API_TOKEN`).
- **Respeitar rate limits** — a quota é configurável por aplicação (campo "Quota Por Token"); em caso de 429, implementar backoff.
- **Datas vêm como string `dd/mm/aaaa`** — converter para `datetime` ao processar.

## Quando consultar o PDF diretamente

Recorra ao `docs/2024_09_16_MANUAL_SOF_API.pdf` quando precisar:
- Lista completa de campos de retorno de um endpoint específico (este resumo não cobre todos).
- Tipos exatos (`String(N)`, `Decimal(18,2)`, etc.) para tipagem rigorosa.
- Screenshots dos passos de cadastro/geração de token na vitrine APILIB.
- Exemplos de payloads reais retornados pela API.
