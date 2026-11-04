---
name: analise-estrategica-despesas
description: Processe faturas de ponta a ponta, conciliando cada total antes de enriquecer merchants com pesquisa e revisão humana, categorizar e gerar um plano acionável de redução de despesas. Use para uma ou várias faturas em CSV, OFX ou ZIP e para reabrir uma análise consolidada.
metadata:
  version: "1.3.0"
---

# Análise estratégica de despesas

Gere uma análise acionável em português do Brasil, distinguindo fatos calculados de estimativas.

## Triagem obrigatória

Ao ser chamada, identifique os itens já presentes e conduza o usuário pelo que estiver faltando; não espere que ele saiba quais arquivos ou metadados enviar.

- Se ainda não houver `consolidado.csv`, peça as faturas/extratos e os totais de cada fatura. O comando unificado abaixo executa a consolidação e a reconciliação antes da análise.
- Se houver um consolidado, confira também `consolidation_report.json` quando disponível. Uma divergência ou uma fatura sem total esperado deve permanecer visível como limitação da análise.
- Carregue automaticamente a base local persistente da skill. Use `--knowledge-base` somente para importar ou selecionar uma base diferente de forma explícita.
- Pergunte se há classificações históricas ou categorias customizadas. Elas são opcionais e sua ausência não bloqueia o fluxo.
- Pergunte por objetivos ou restrições específicos somente se forem relevantes; na ausência deles, faça a análise completa padrão.

Não repita perguntas já respondidas pelos arquivos ou pela conversa. Antes de executar, apresente uma lista curta e concreta das pendências. A análise deve parar automaticamente se algum total estiver ausente, não verificado ou divergente.

## Fluxo

1. Para arquivos brutos, prefira uma única ação:

   ```bash
   python scripts/process_expenses.py <entrada-ou-zip> <diretorio-saida> \
     --expected-totals <totais.csv> [--categories categorias.csv] [--open]
   ```

   O CSV de totais usa `banco,periodo_referencia,total_esperado`. O comando consolida, deduplica, concilia, gera os artefatos analíticos e abre a aplicação local. Se houver divergência, total ausente ou arquivo pendente, deve sair com código 2 e não iniciar a análise. Use `--no-serve` somente em automação ou quando desejar apenas os arquivos.

2. Se o usuário já forneceu um `consolidado.csv` reconciliado, abra diretamente a aplicação local:

   ```bash
   python scripts/review_merchants.py serve <consolidado.csv> <diretorio-saida> \
     [--knowledge-base <merchant_knowledge_base.csv>] [--categories categorias.csv] [--open]
   ```

   A aplicação deve permanecer em `127.0.0.1`. O menu `Insights` apresenta os resultados; `Classificação` contém somente a revisão dos merchants. A tela não usa checkboxes nem seleção parcial. Um único botão `Aprovar revisão` incorpora todas as linhas exibidas, recalcula a análise determinística e redireciona para o plano atualizado. O clique do usuário é a aprovação explícita do conjunto completo; nunca acione o botão em nome dele.

   Por padrão, a revisão é gravada em `~/.local/share/analise-despesas-skills/merchant_knowledge_base.csv`, com acesso restrito ao usuário, e deve ser reutilizada automaticamente em execuções futuras. `ANALISE_DESPESAS_STATE_DIR` pode substituir a raiz local quando o ambiente exigir outro local persistente.

3. Use o fluxo por arquivos abaixo apenas quando não for possível manter o servidor local. Prepare a revisão dos merchants únicos consultando primeiro a base aprovada:

   ```bash
   python scripts/review_merchants.py prepare <consolidado.csv> <diretorio-saida> \
     [--knowledge-base <merchant_knowledge_base.csv>] [--categories categorias.csv]
   ```

   Se o usuário fornecer classificações anteriores no formato `descricao,categoria[,categoria_nativa]`, adapte-as antes da revisão:

   ```bash
   python scripts/review_merchants.py import-legacy <classificacoes.csv> <diretorio-saida> \
     [--knowledge-base <merchant_knowledge_base.csv>]
   ```

   Preserve a categoria anterior como sugestão, nunca como nova aprovação automática. Converta `Despesas Diversas` para `Desconhecida`, sinalize divergências entre categorias anteriores e exclua registros puramente contábeis. Use `categoria_nativa` apenas como contexto visível para o revisor.

4. Antes da revisão humana, faça uma pesquisa complementar somente para as linhas que continuarem como `Desconhecido`/`Desconhecida` após a base aprovada, as regras determinísticas e os dados históricos. Quando houver acesso à internet:

   - pesquise o descritor público do merchant, individualmente ou em pequenos grupos relacionados, usando nome comercial e localização provável quando ela já estiver disponível sem expor a fatura;
   - nunca envie valor, data, banco, cartão, conjunto de transações ou qualquer outro dado financeiro a mecanismos de busca ou serviços externos;
   - priorize site oficial, diretório oficial de shopping, cadastro público de empresa ou conselho profissional e páginas institucionais. Use agregadores e trechos de busca apenas como apoio; descritores genéricos ou nomes de pessoa exigem correspondência adicional de localidade e atividade;
   - use `categoria_nativa`, ocorrências e contexto do consolidado apenas localmente para avaliar candidatos. Eles não bastam, isoladamente, para identificar o merchant;
   - ao encontrar evidência razoável, preencha somente a sugestão de nome amigável e categoria na página local ou no rascunho. Mantenha a linha pendente, sem marcar aprovação e sem elevar confidence para 100%; registre fontes ou uma justificativa curta nas notas de trabalho para conseguir explicar a sugestão ao usuário;
   - se houver múltiplos candidatos plausíveis, nenhuma correspondência confiável ou acesso indisponível, preserve `Desconhecido`, `Desconhecida` e confidence 0%. Não force uma classificação para reduzir a contagem de desconhecidos.

   A pesquisa pública enriquece o rascunho, mas não altera a exigência de aprovação humana. Serviços pagos, medidos ou que exijam transmitir dados financeiros não fazem parte desta etapa implícita.

5. Entregue `merchant_review.html` ao usuário e pare quando estiver usando o fluxo por arquivos. A aprovação precisa ser humana: não presuma concordância. A página lista somente nomes únicos, em ordem alfabética, e permite ordenar e filtrar as colunas, editar nome amigável/categoria e baixar a revisão completa como aprovada. Informe quantas sugestões a pesquisa resolveu, quais permaneceram desconhecidas e as principais fontes utilizadas.
6. Depois que o usuário devolver o CSV baixado, importe a revisão completa:

   ```bash
   python scripts/review_merchants.py approve <merchant_review_approved.csv> \
     [--knowledge-base <merchant_knowledge_base.csv>]
   ```

7. Execute a análise exigindo que todos os merchants estejam aprovados:

   ```bash
   python scripts/analyze_expenses.py <consolidado.csv> <diretorio-saida> \
     --merchant-kb <merchant_knowledge_base.csv> --require-reviewed \
     [--categories categorias.csv] [--reclassify]
   ```

8. Leia `analysis_results.json`. Use exclusivamente seus agregados para totais, percentuais, compromissos futuros e faixas de economia. Nomes exibidos em relatórios e insights devem ser os nomes amigáveis.
9. Verifique `data_quality` antes de interpretar tendências. Com menos de três períodos, descreva tendências como evidência limitada. Se mais de 10% das despesas estiverem em `Desconhecida`, destaque a necessidade de revisão.
10. Entregue o dashboard autocontido `analise_estrategica_despesas.html`, seguindo `references/dashboard.md`, além de `consolidado_categorizado.csv`, `analysis_results.json`, `consolidation_report.json` e a base de merchants reutilizável.

## Segurança da classificação

- A base aprovada tem precedência e evita reclassificar merchants já conhecidos.
- Sem evidência razoável para o nome amigável, use `Desconhecido`, categoria `Desconhecida` e confidence 0%; deixe o humano preencher.
- Uma sugestão determinística não é aprovação. O clique humano em `Aprovar revisão` aprova o conjunto completo, atribui confidence 100% e grava todas as linhas na base.
- Uma classificação legada pode preencher a sugestão e seu contexto, mas continua pendente até a revisão no formato atual.
- Reutilize automaticamente a base local persistente entre execuções. Em ambientes efêmeros, exporte-a para um local persistente antes do encerramento.
- Recalcule localmente sempre que as regras determinísticas forem suficientes. Só use IA para uma nova narrativa ou interpretação que não possa ser derivada de `analysis_results.json`; chamadas externas pagas exigem autorização de custo própria e nunca são disparadas implicitamente pelo navegador.

## Regras de interpretação

- Trate `savings_potential` como cenário, nunca como economia garantida.
- Não recomende cancelar parcelas já contratadas; mostre o compromisso restante e a liberação futura de caixa.
- Uma cobrança recorrente repetida é “possível duplicidade” até o usuário confirmar.
- Priorize ações específicas de baixo esforço e alto impacto, mas evite julgamento moral.
- Restrinja-se à análise de despesas; não ofereça recomendação de investimento.

## Categorias customizadas

O CSV opcional usa `categoria,palavras_chave,prioridade`; separe palavras-chave por `|`. Ele substitui as regras comerciais padrão, preservando apenas as regras contábeis de pagamentos, créditos e tributos.

