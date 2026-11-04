---
name: consolidar-faturas
description: Extraia, valide, reconcilie e consolide transações de faturas ou extratos em CSV e OFX, incluindo ZIPs. Use PDF e imagem apenas com extração assistida e confirmação quando houver incerteza. Não use para recomendações de corte de gastos.
---

# Consolidar faturas e extratos

Produza dados financeiros rastreáveis sem criar lançamentos para fechar diferenças.

## Triagem obrigatória

Ao ser chamada, primeiro verifique o que o usuário já forneceu e peça somente o que estiver faltando. Não presuma que ele conhece os requisitos. Explique que, para começar, são necessários:

- todos os arquivos de faturas ou extratos do período; prefira CSV ou OFX, aceite ZIP e informe que PDF/imagem exige extração assistida;
- para cada fatura, o total exato exibido no documento, associado ao arquivo, banco/cartão e período de referência;
- identificação de banco/cartão, período ou moeda somente quando isso não puder ser determinado com segurança no próprio arquivo.

Ofereça um modelo simples para a resposta, por exemplo: `arquivo | banco/cartão | período | total da fatura`. Se o total não estiver disponível, peça que o usuário declare isso explicitamente; registre a fatura como não verificada em vez de inventar o valor. Não repita perguntas respondidas pelos anexos ou pela conversa.

Pode inspecionar os arquivos recebidos para descobrir campos e apontar pendências, mas não conclua a consolidação enquanto não houver ao menos um arquivo processável e, para cada fatura, um total esperado ou uma declaração explícita de que ele está indisponível. Se houver várias faturas, confirme que a lista está completa antes do processamento final.

## Fluxo

1. Faça a triagem acima e inspecione todos os arquivos antes de processar.
2. Para CSV e OFX, execute o script determinístico:

   ```bash
   python scripts/consolidate_invoices.py <entrada-ou-zip> <diretorio-saida> [--expected-totals totais.csv]
   ```

3. Para PDF ou imagem, extraia visualmente apenas dados legíveis, registre a origem e converta-os para o esquema padronizado antes de executar o script novamente. Nunca deduza uma transação pela diferença entre subtotal e total.
4. Leia `consolidation_report.json`. Se `requer_confirmacao` for verdadeiro ou o processo sair com código 2, apresente ao usuário os arquivos pendentes e as divergências; não declare reconciliação concluída.
5. Entregue `consolidado.csv`, `padronizado.zip`, `consolidation_report.json` e `consolidation_summary.log`.

## Totais esperados

O CSV opcional usa as colunas `banco,periodo_referencia,total_esperado`. Ausência de total esperado significa “não verificado”, não “conciliado”.

## Invariantes

- Valores positivos são despesas; pagamentos e créditos são negativos.
- Preserve banco, período, cartão e categoria nativa.
- Não converta erro de parsing em zero.
- Não ignore arquivos, duplicatas ou diferenças silenciosamente.
- Deixe `categoria` vazia; a skill `analise-estrategica-despesas` é a única responsável pela categorização analítica.

Para o esquema completo, leia `references/format-specification.md`.

