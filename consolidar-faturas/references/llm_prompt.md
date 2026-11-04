# Extração assistida de documentos financeiros

Use este guia somente para formatos que o núcleo determinístico não processa diretamente, como PDF e imagem.

## Ordem de preferência

1. CSV ou OFX original do banco.
2. Texto incorporado no PDF, preservando colunas e seções.
3. Leitura visual/OCR da imagem, com conferência humana quando houver ambiguidade.

Converta o resultado para o esquema de `format_specifications.md` e então execute `scripts/consolidate_invoices.py`.

## Regras de segurança

- Transcreva apenas transações efetivamente visíveis na fonte.
- Não crie um lançamento para compensar diferença entre subtotal e total.
- Não adivinhe cartão, data, parcela, sinal ou descrição.
- Quando um campo não estiver visível, deixe-o vazio se o esquema permitir.
- Se uma transação inteira estiver ilegível ou uma seção estiver ausente, registre o arquivo como incompleto e solicite uma fonte melhor.
- Uma diferença de conciliação é evidência de extração incompleta ou regra inadequada; não é autorização para ajustar dados.

## PDFs com múltiplas colunas

Extraia cada coluna separadamente e preserve a ordem visual. Cabeçalhos, rodapés, limites e ofertas não são transações. Compare quantidade de linhas, subtotais e total da fatura, mas mantenha qualquer divergência explícita.

## Imagens

Registre quais páginas/cartões estão visíveis. OCR de baixa confiança exige conferência do usuário. Não derive o valor líquido de uma seção ausente por equação contábil.

## Reconciliação

Quando houver total explícito, forneça-o em um CSV com:

```csv
banco,periodo_referencia,total_esperado
Banco Exemplo,Jan/2026,1234.56
```

O processo aceita diferença máxima de R$ 0,02. Sem total explícito, o status correto é `não verificado`.
