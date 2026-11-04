# Análise de despesas — skills e núcleo compartilhado

Plugin reutilizável para ChatGPT, Codex e agentes compatíveis com Agent Skills. O fluxo separa integridade de extração e conciliação da interpretação estratégica:

```text
CSV / OFX / ZIP ──► consolidar-faturas ──► consolidado.csv
PDF / imagem ──► extração assistida ─────┘        │
                                                    ▼
                                  revisão de merchants
                                  humano + base CSV
                                                    │
                                                    ▼
                               analise-estrategica-despesas
                                                    │
                              JSON + CSV categorizado + dashboard
```

## O que mudou

- Um único núcleo em `src/expense_skills` atende as skills legadas e o plugin ChatGPT/Codex.
- Valores monetários inválidos interrompem o processamento; não viram zero silenciosamente.
- Duplicatas são removidas por chave contábil e reportadas.
- `Saldo Anterior`, pagamentos e créditos não entram como despesa do período.
- Categorias customizadas são realmente carregadas.
- Parcelas de bancos ausentes no mês mais recente são avançadas pelo tempo decorrido.
- Tendências informam a janela e a qualidade dos dados.
- PDFs e imagens nunca geram transações por diferença matemática; extrações incompletas exigem confirmação.
- O dashboard não depende de fontes ou bibliotecas externas.
- Merchants são revisados uma única vez por nome original e reutilizados por uma base de conhecimento portátil.
- Sugestões inseguras falham para `Desconhecido`/`Desconhecida`, evitando falsos positivos.

## Arquitetura

```text
plugin.json                         manifesto portátil ChatGPT/Codex
skills/                             skills canônicas do plugin
src/expense_skills/
├── models.py                       entidades e invariantes financeiros
├── parsing.py                      dinheiro, datas, períodos e parcelas
├── categorization.py               regras padrão e customizadas
├── merchants.py                    enriquecimento, revisão HTML e base aprovada
├── consolidation.py               ingestão, reconciliação e saídas
├── analysis.py                     métricas, qualidade e insights
└── cli.py                          adaptadores de linha de comando
consolidar-faturas/                 entrada legada compatível
analise-estrategica-despesas/       entrada legada compatível
tests/                              testes locais sem dependências externas
```

O núcleo usa apenas a biblioteca padrão do Python. CSV e OFX são processados deterministicamente. PDF e imagem exigem leitura assistida pelo agente e conversão para o esquema padronizado.

## Instalação e pontos de entrada

O repositório oferece três formas equivalentes de uso:

| Ambiente | Entrada | Implementação compartilhada |
|---|---|---|
| ChatGPT/Codex e Agent Skills | `plugin.json` e `skills/` | `src/expense_skills/` |
| Claude e instalações anteriores | `consolidar-faturas/` e `analise-estrategica-despesas/` | `src/expense_skills/` |
| Terminal/Python | comandos definidos em `pyproject.toml` | `src/expense_skills/` |

Para desenvolvimento local:

```bash
uv sync
```

Depois disso, use os scripts das skills mostrados abaixo ou os comandos instalados `consolidar-faturas`, `revisar-merchants` e `analisar-despesas`. Os wrappers não possuem regras próprias: todos chamam o mesmo núcleo, evitando divergência entre agentes.

### Comportamento esperado no chat

O usuário pode simplesmente pedir uma análise de despesas. A skill deve então:

1. inventariar anexos e informações já fornecidas;
2. explicar, em linguagem simples, o que ainda precisa ser enviado;
3. pedir o total de cada fatura ou uma declaração explícita de que ele não está disponível;
4. perguntar se existe uma base de merchants anterior;
5. consolidar e reconciliar antes de iniciar a análise;
6. abrir a revisão humana dos merchants e, após a aprovação, atualizar os insights localmente.

O agente não deve responder apenas com nomes técnicos de arquivos. Quando o usuário não tiver uma base anterior ou categorias próprias, ele deve explicar que esses itens são opcionais e seguir com uma base vazia e as categorias padrão.

## Triagem guiada ao iniciar

Quando uma das skills é chamada, ela primeiro inventaria o que já foi anexado e solicita somente as informações ausentes. O usuário recebe um checklist simples, sem precisar conhecer previamente o pipeline:

- arquivos de todas as faturas ou extratos;
- `arquivo | banco/cartão | período | total` para cada fatura;
- confirmação explícita quando um total não estiver disponível;
- base de merchants anterior, classificações históricas ou categorias próprias, quando existirem.

Banco, período e moeda são solicitados apenas quando não puderem ser identificados com segurança no documento. Classificações e categorias anteriores são opcionais. A consolidação exige ao menos um arquivo processável e registra como não verificada qualquer fatura cujo total tenha sido declarado indisponível; a análise só começa depois que houver um consolidado processável e uma resposta sobre a existência da base anterior.

## Consolidação

```bash
python skills/consolidar-faturas/scripts/consolidate_invoices.py entrada output
```

Com totais explícitos:

```bash
python skills/consolidar-faturas/scripts/consolidate_invoices.py \
  entrada output --expected-totals totais.csv
```

`totais.csv`:

```csv
banco,periodo_referencia,total_esperado
Banco Exemplo,Jan/2026,1234.56
```

Saídas:

- `consolidado.csv`
- `padronizado.zip`
- `consolidation_report.json`
- `consolidation_summary.log`

Código de saída 2 ou `requer_confirmacao=true` significa divergência, arquivo não processado ou erro de validação. Artefatos parciais não devem ser apresentados como reconciliação concluída.

## Revisão humana de merchants

### Aplicação local

O fluxo recomendado mantém insights e classificação em páginas separadas:

```bash
python skills/analise-estrategica-despesas/scripts/review_merchants.py serve \
  output/consolidado.csv analysis-output \
  --knowledge-base merchant_knowledge_base.csv --open
```

A aplicação fica disponível apenas em `127.0.0.1`:

- `Insights`: visão atualizada de totais, categorias, prioridades, maiores despesas e recorrências;
- `Classificação`: tabela editável e filtrável de merchants únicos;
- `Salvar e atualizar insights`: importa aprovações, mantém alterações pendentes em `merchant_review_draft.csv`, recalcula `analysis_results.json` e volta para os insights atualizados.

Esse processamento é local e determinístico. Nenhuma chamada de IA é necessária para atualizar as métricas. Uma nova narrativa gerada por IA pode ser produzida separadamente quando solicitada, sujeita aos controles de custo aplicáveis.

### Fluxo por arquivos

Prepare a revisão usando a base existente, mesmo que ela ainda não exista:

```bash
python skills/analise-estrategica-despesas/scripts/review_merchants.py prepare \
  output/consolidado.csv merchant-review \
  --knowledge-base merchant_knowledge_base.csv
```

Abra `merchant-review/merchant_review.html`. A tela autocontida apresenta somente merchants únicos, ordenados alfabeticamente, e permite:

- ordenar e filtrar por qualquer coluna;
- comparar nome original, nome amigável, confidence, categoria, origem e ocorrências;
- editar nome amigável e categoria;
- aprovar itens individualmente ou em lote e baixar `merchant_review_approved.csv`.

Importe somente depois da revisão humana:

```bash
python skills/analise-estrategica-despesas/scripts/review_merchants.py approve \
  merchant_review_approved.csv --knowledge-base merchant_knowledge_base.csv
```

Somente linhas marcadas como aprovadas entram na base. Elas passam a ter confidence 100% e são reutilizadas sem nova classificação. Se não houver evidência razoável, a sugestão fica como nome `Desconhecido`, categoria `Desconhecida` e confidence 0%, para evitar falsos positivos.

Classificações anteriores em `descricao,categoria[,categoria_nativa]` podem alimentar a mesma revisão:

```bash
python skills/analise-estrategica-despesas/scripts/review_merchants.py import-legacy \
  classificacoes-anteriores.csv merchant-review \
  --knowledge-base merchant_knowledge_base.csv
```

O importador agrupa descrições únicas, preserva categorias anteriores como sugestões, mostra categorias nativas como contexto, converte `Despesas Diversas` para `Desconhecida`, sinaliza conflitos e exclui pagamentos/encargos puramente contábeis. Nenhuma linha legada é aprovada automaticamente.

## Análise estratégica

```bash
python skills/analise-estrategica-despesas/scripts/analyze_expenses.py \
  output/consolidado.csv analysis-output \
  --merchant-kb merchant_knowledge_base.csv --require-reviewed
```

Categorias customizadas:

```bash
python skills/analise-estrategica-despesas/scripts/analyze_expenses.py \
  output/consolidado.csv analysis-output --categories categorias.csv \
  --merchant-kb merchant_knowledge_base.csv --require-reviewed
```

O formato é `categoria,palavras_chave,prioridade`, com palavras-chave separadas por `|`. A análise gera:

- `analysis_results.json`: métricas, qualidade, cenários e insights estruturados;
- `consolidado_categorizado.csv`: transações categorizadas, com nome amigável, confidence, aprovação e origem da classificação;
- `analise_estrategica_despesas.html`: produzido pelo agente exclusivamente a partir dos agregados JSON.

Relatórios, rankings, recorrências e insights usam o nome amigável. O nome original permanece no CSV e nos campos de auditoria do JSON.

### Portabilidade da base

`merchant_knowledge_base.csv` é a fonte compartilhada entre Claude, ChatGPT e Codex; não depende da memória de um provedor. Em execução local, mantenha o arquivo no workspace. Em um chat sem armazenamento persistente, guarde-o fora da conversa e anexe-o novamente na próxima análise. Isso também torna o histórico auditável e evita gastar tokens reclassificando merchants conhecidos.

## Testes

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
```

Os testes não fazem chamadas de rede nem usam serviços pagos.

## Harnesses para agentes

- `AGENTS.md` é o contrato canônico para Codex e agentes compatíveis: arquitetura, invariantes financeiros, privacidade, custos e matriz de validação.
- `CLAUDE.md` adiciona as particularidades de execução do Claude e referencia o contrato canônico.
- As instruções funcionais consumidas em runtime permanecem nos arquivos `SKILL.md`; os harnesses orientam quem modifica o repositório.

Ao alterar o fluxo, mantenha sincronizadas as skills canônicas em `skills/` e as entradas legadas. Ao alterar regras de negócio, modifique `src/expense_skills/` e adicione ou ajuste testes em `tests/`.

## Privacidade e segurança

O código não envia dados financeiros para serviços externos. Logs agregam contagens, totais e status, evitando repetir descrições de transações. Antes de compartilhar artefatos, revise nomes, finais de cartão e estabelecimentos que possam identificar o titular.
