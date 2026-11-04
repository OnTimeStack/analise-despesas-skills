---
name: analise-estrategica-despesas
description: Processe faturas de ponta a ponta, conciliando cada total antes de enriquecer merchants com pesquisa e revisão humana, categorizar e gerar um plano acionável de redução de despesas. Use para uma ou várias faturas em CSV, OFX ou ZIP e para reabrir uma análise consolidada.
metadata:
  version: "1.3.0"
---

# Análise estratégica de despesas

Esta entrada é mantida para compatibilidade com instalações anteriores. O núcleo é compartilhado com o plugin ChatGPT/Codex em `../src/expense_skills`.

## Triagem obrigatória

Ao ser chamada, verifique primeiro os anexos e a conversa e peça somente o que estiver faltando; não suponha que o usuário saiba o que enviar. Se não houver `consolidado.csv`, solicite as faturas/extratos e os totais de cada fatura e execute primeiro `consolidar-faturas`. Para cada fatura, obtenha um total esperado ou uma declaração explícita de que ele não está disponível. Não analise arquivos brutos diretamente.

Com o consolidado, confira `consolidation_report.json` quando existir e mantenha divergências visíveis. Pergunte se o usuário possui `merchant_knowledge_base.csv`; se não possuir, avise que uma base vazia será criada e que o arquivo gerado deve ser guardado para reutilização. Pergunte também se há classificações históricas ou categorias customizadas, deixando claro que são opcionais. Só inicie a análise depois de ter um consolidado processável e uma resposta sobre a base anterior. Não repita informações já inferidas com segurança dos arquivos.

## Execução unificada com revisão humana obrigatória

Para arquivos brutos, use preferencialmente uma única ação:

```bash
python scripts/process_expenses.py <entrada-ou-zip> <diretorio-saida> \
  --expected-totals <totais.csv> [--knowledge-base merchant_knowledge_base.csv] \
  [--categories categorias.csv] [--open]
```

Ela consolida, deduplica e concilia cada banco/período antes de gerar a análise e abrir a revisão. Total ausente, divergência ou arquivo pendente encerra o comando com código 2 antes da análise. `--no-serve` gera somente os artefatos.

Se já existir um `consolidado.csv` reconciliado, abra diretamente a aplicação:

Prefira a aplicação local integrada:

```bash
python scripts/review_merchants.py serve <consolidado.csv> <diretorio-saida> \
  --knowledge-base <merchant_knowledge_base.csv> [--categories categorias.csv] [--open]
```

Ela oferece páginas separadas de `Insights` e `Classificação`. `Salvar rascunho` não altera o plano; `Aprovar selecionados e atualizar insights` incorpora somente as linhas marcadas, recalcula os insights localmente e abre o plano atualizado. Nunca aprove merchants em nome do usuário. IA externa não é necessária para os cálculos determinísticos e não deve ser chamada automaticamente.

Antes de pedir aprovação, pesquise na internet somente os merchants que permanecerem como `Desconhecido`/`Desconhecida`. Use apenas o descritor público e, quando já conhecida sem expor a fatura, a localização provável; nunca envie valores, datas, banco, cartão ou o conjunto de transações. Priorize páginas oficiais, diretórios de shopping, cadastros públicos e conselhos profissionais. Use categoria nativa e ocorrências somente como contexto local, não como prova de identidade.

Quando a evidência corresponder ao descritor, preencha nome amigável e categoria apenas como sugestão local, mantenha confidence abaixo de 100% e não marque aprovação. Registre as fontes para explicá-las ao usuário. Nomes de pessoa, descritores genéricos ou candidatos conflitantes continuam como `Desconhecido`/`Desconhecida`; não force uma classificação. A etapa não usa serviços pagos ou medidos implicitamente e não substitui a revisão humana.

Use o fluxo por arquivos somente quando o servidor local não estiver disponível:

```bash
python scripts/review_merchants.py prepare <consolidado.csv> <diretorio-saida> \
  --knowledge-base <merchant_knowledge_base.csv> [--categories categorias.csv]
```

Entregue `merchant_review.html`, resuma quantas sugestões foram enriquecidas e quais continuaram desconhecidas, e pare até o usuário revisar os nomes únicos, editar nome amigável/categoria, aprovar e devolver o CSV baixado. Não aprove em nome do usuário. Depois importe e analise:

Para classificações anteriores em `descricao,categoria[,categoria_nativa]`, use primeiro:

```bash
python scripts/review_merchants.py import-legacy <classificacoes.csv> <diretorio-saida> \
  [--knowledge-base <merchant_knowledge_base.csv>]
```

O adaptador preserva categorias úteis como sugestões, converte o fallback antigo em `Desconhecida`, expõe divergências e mantém tudo pendente de revisão no modelo atual.

```bash
python scripts/review_merchants.py approve <merchant_review_approved.csv> \
  --knowledge-base <merchant_knowledge_base.csv>
python scripts/analyze_expenses.py <consolidado.csv> <diretorio-saida> \
  --merchant-kb <merchant_knowledge_base.csv> --require-reviewed \
  [--categories categorias.csv] [--reclassify]
```

Use os agregados de `analysis_results.json` como única fonte para o dashboard e para a conversa, sempre exibindo o nome amigável. Sem evidência razoável, mantenha nome `Desconhecido`, categoria `Desconhecida` e confidence 0% para o humano decidir. Preserve a base CSV aprovada entre execuções; ela evita reclassificação e funciona igualmente no Claude e no ChatGPT/Codex.

Entregue `analise_estrategica_despesas.html` autocontido, `consolidado_categorizado.csv`, `analysis_results.json`, `consolidation_report.json` e a base de merchants reutilizável. O dashboard deve separar despesas brutas, créditos e total líquido e mostrar ações por fase, recorrências, parcelas e faixas de economia como cenários.

Categorias customizadas usam `categoria,palavras_chave,prioridade`, com palavras-chave separadas por `|`.
