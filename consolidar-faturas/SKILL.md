---
name: consolidar-faturas
description: Extraia, valide, reconcilie e consolide transações de faturas ou extratos em CSV e OFX, incluindo ZIPs. Use PDF e imagem apenas com extração assistida e confirmação quando houver incerteza. Não use para recomendações de corte de gastos.
metadata:
  version: "1.3.0"
---

# Consolidar faturas e extratos

Esta entrada é mantida para compatibilidade com instalações anteriores. O núcleo é compartilhado com o plugin ChatGPT/Codex em `../src/expense_skills`.

## Triagem obrigatória

Ao ser chamada, verifique os anexos e a conversa e peça somente o que estiver faltando. O usuário não precisa conhecer o formato de entrada. Solicite todos os arquivos de faturas/extratos e, para cada fatura, `arquivo | banco/cartão | período | total exato da fatura`. Prefira CSV/OFX, aceite ZIP e avise que PDF/imagem exige extração assistida. Peça banco, período ou moeda apenas se o arquivo não permitir identificá-los com segurança.

Se algum total não estiver disponível, peça uma declaração explícita e marque essa fatura como não verificada; nunca invente o valor. Pode inspecionar os anexos para levantar pendências, mas não conclua a consolidação sem ao menos um arquivo processável e sem um total esperado ou declaração de indisponibilidade para cada fatura. Com múltiplas faturas, confirme que a lista está completa.

## Execução

```bash
python scripts/consolidate_invoices.py <entrada-ou-zip> <diretorio-saida> [--expected-totals totais.csv]
```

O CSV de totais usa `banco,periodo_referencia,total_esperado`. Leia `consolidation_report.json`; código de saída 2 ou `requer_confirmacao=true` significa que há divergência, erro ou arquivo ainda não extraído.

Para PDF e imagem, transcreva somente dados legíveis para o esquema de `references/format_specifications.md` e execute novamente. Nunca reconstrua transações pela diferença entre totais.

Entregue `consolidado.csv`, `padronizado.zip`, `consolidation_report.json` e `consolidation_summary.log`. Deixe `categoria` vazia para a skill de análise.
