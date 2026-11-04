---
name: analise-estrategica-despesas
description: Enriqueça merchants com revisão humana e base de conhecimento, categorize e analise um consolidado financeiro para identificar concentração, recorrências, parcelamentos, tendências e oportunidades de redução. Use após a consolidação; não use para extrair PDFs ou conciliar faturas.
metadata:
  version: "1.3.0"
---

# Análise estratégica de despesas

Gere uma análise acionável em português do Brasil, distinguindo fatos calculados de estimativas.

## Triagem obrigatória

Ao ser chamada, identifique os itens já presentes e conduza o usuário pelo que estiver faltando; não espere que ele saiba quais arquivos ou metadados enviar.

- Se ainda não houver `consolidado.csv`, peça as faturas/extratos e os totais de cada fatura e siga primeiro a skill `consolidar-faturas`, inclusive sua reconciliação. Não tente analisar diretamente arquivos brutos.
- Se houver um consolidado, confira também `consolidation_report.json` quando disponível. Uma divergência ou uma fatura sem total esperado deve permanecer visível como limitação da análise.
- Pergunte se existe `merchant_knowledge_base.csv` de uma execução anterior. Se não existir, informe que uma base vazia será criada; se o ambiente não for persistente, explique que o arquivo gerado deve ser guardado para a próxima execução.
- Pergunte se há classificações históricas ou categorias customizadas. Elas são opcionais e sua ausência não bloqueia o fluxo.
- Pergunte por objetivos ou restrições específicos somente se forem relevantes; na ausência deles, faça a análise completa padrão.

Não repita perguntas já respondidas pelos arquivos ou pela conversa. Só inicie a análise depois de ter um consolidado processável e de o usuário ter respondido sobre a existência da base anterior. Antes disso, apresente uma lista curta e concreta das pendências.

## Fluxo

1. Prefira a aplicação local com páginas separadas de insights e classificação:

   ```bash
   python scripts/review_merchants.py serve <consolidado.csv> <diretorio-saida> \
     --knowledge-base <merchant_knowledge_base.csv> [--categories categorias.csv] [--open]
   ```

   A aplicação deve permanecer em `127.0.0.1`. O menu `Insights` apresenta os resultados; `Classificação` contém somente a revisão dos merchants. Ao selecionar `Salvar e atualizar insights`, importe as linhas aprovadas, preserve alterações não aprovadas como rascunho, execute novamente a análise determinística e redirecione para os insights atualizados.

2. Use o fluxo por arquivos abaixo apenas quando não for possível manter o servidor local. Prepare a revisão dos merchants únicos consultando primeiro a base aprovada:

   ```bash
   python scripts/review_merchants.py prepare <consolidado.csv> <diretorio-saida> \
     --knowledge-base <merchant_knowledge_base.csv> [--categories categorias.csv]
   ```

   Se o usuário fornecer classificações anteriores no formato `descricao,categoria[,categoria_nativa]`, adapte-as antes da revisão:

   ```bash
   python scripts/review_merchants.py import-legacy <classificacoes.csv> <diretorio-saida> \
     [--knowledge-base <merchant_knowledge_base.csv>]
   ```

   Preserve a categoria anterior como sugestão, nunca como nova aprovação automática. Converta `Despesas Diversas` para `Desconhecida`, sinalize divergências entre categorias anteriores e exclua registros puramente contábeis. Use `categoria_nativa` apenas como contexto visível para o revisor.

3. Antes da revisão humana, faça uma pesquisa complementar somente para as linhas que continuarem como `Desconhecido`/`Desconhecida` após a base aprovada, as regras determinísticas e os dados históricos. Quando houver acesso à internet:

   - pesquise o descritor público do merchant, individualmente ou em pequenos grupos relacionados, usando nome comercial e localização provável quando ela já estiver disponível sem expor a fatura;
   - nunca envie valor, data, banco, cartão, conjunto de transações ou qualquer outro dado financeiro a mecanismos de busca ou serviços externos;
   - priorize site oficial, diretório oficial de shopping, cadastro público de empresa ou conselho profissional e páginas institucionais. Use agregadores e trechos de busca apenas como apoio; descritores genéricos ou nomes de pessoa exigem correspondência adicional de localidade e atividade;
   - use `categoria_nativa`, ocorrências e contexto do consolidado apenas localmente para avaliar candidatos. Eles não bastam, isoladamente, para identificar o merchant;
   - ao encontrar evidência razoável, preencha somente a sugestão de nome amigável e categoria na página local ou no rascunho. Mantenha a linha pendente, sem marcar aprovação e sem elevar confidence para 100%; registre fontes ou uma justificativa curta nas notas de trabalho para conseguir explicar a sugestão ao usuário;
   - se houver múltiplos candidatos plausíveis, nenhuma correspondência confiável ou acesso indisponível, preserve `Desconhecido`, `Desconhecida` e confidence 0%. Não force uma classificação para reduzir a contagem de desconhecidos.

   A pesquisa pública enriquece o rascunho, mas não altera a exigência de aprovação humana. Serviços pagos, medidos ou que exijam transmitir dados financeiros não fazem parte desta etapa implícita.

4. Entregue `merchant_review.html` ao usuário e pare. A aprovação precisa ser humana: não marque itens nem presuma concordância. A página lista somente nomes únicos, em ordem alfabética, e permite ordenar e filtrar todas as colunas, editar nome amigável/categoria e baixar o CSV revisado. Informe quantas sugestões a pesquisa resolveu, quais permaneceram desconhecidas e as principais fontes utilizadas.
5. Depois que o usuário devolver o CSV baixado, importe somente as linhas explicitamente aprovadas:

   ```bash
   python scripts/review_merchants.py approve <merchant_review_approved.csv> \
     --knowledge-base <merchant_knowledge_base.csv>
   ```

6. Execute a análise exigindo que todos os merchants estejam aprovados:

   ```bash
   python scripts/analyze_expenses.py <consolidado.csv> <diretorio-saida> \
     --merchant-kb <merchant_knowledge_base.csv> --require-reviewed \
     [--categories categorias.csv] [--reclassify]
   ```

7. Leia `analysis_results.json`. Use exclusivamente seus agregados para totais, percentuais, compromissos futuros e faixas de economia. Nomes exibidos em relatórios e insights devem ser os nomes amigáveis.
8. Verifique `data_quality` antes de interpretar tendências. Com menos de três períodos, descreva tendências como evidência limitada. Se mais de 10% das despesas estiverem em `Desconhecida`, destaque a necessidade de revisão.
9. Gere um dashboard HTML autocontido seguindo `references/dashboard.md`, sem bibliotecas, fontes ou chamadas externas. Entregue também `consolidado_categorizado.csv` e `analysis_results.json`.

## Segurança da classificação

- A base aprovada tem precedência e evita reclassificar merchants já conhecidos.
- Sem evidência razoável para o nome amigável, use `Desconhecido`, categoria `Desconhecida` e confidence 0%; deixe o humano preencher.
- Uma sugestão determinística não é aprovação. Somente uma linha aprovada e importada recebe confidence 100% e entra na base.
- Uma classificação legada pode preencher a sugestão e seu contexto, mas continua pendente até a revisão no formato atual.
- Preserve `merchant_knowledge_base.csv` entre execuções. Em ambientes sem armazenamento persistente, peça ao usuário para guardar e anexar novamente esse arquivo.
- Recalcule localmente sempre que as regras determinísticas forem suficientes. Só use IA para uma nova narrativa ou interpretação que não possa ser derivada de `analysis_results.json`; chamadas externas pagas exigem autorização de custo própria e nunca são disparadas implicitamente pelo navegador.

## Regras de interpretação

- Trate `savings_potential` como cenário, nunca como economia garantida.
- Não recomende cancelar parcelas já contratadas; mostre o compromisso restante e a liberação futura de caixa.
- Uma cobrança recorrente repetida é “possível duplicidade” até o usuário confirmar.
- Priorize ações específicas de baixo esforço e alto impacto, mas evite julgamento moral.
- Restrinja-se à análise de despesas; não ofereça recomendação de investimento.

## Categorias customizadas

O CSV opcional usa `categoria,palavras_chave,prioridade`; separe palavras-chave por `|`. Ele substitui as regras comerciais padrão, preservando apenas as regras contábeis de pagamentos, créditos e tributos.

