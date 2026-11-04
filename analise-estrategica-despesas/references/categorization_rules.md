# Regras de categorização

O código em `src/expense_skills/categorization.py` é a fonte executável das regras padrão.

## Prioridade contábil

1. Estornos ou devoluções de IOF e tarifas permanecem em `Tributos e Encargos`.
2. Transações cujo tipo é `Pagamento`, `Crédito` ou `Saldo Anterior` pertencem a `Pagamentos e Créditos`, exceto o caso tributário acima.
3. Despesas positivas usam palavras-chave de categorias comerciais.
4. Ausência de correspondência segura resulta em nome `Desconhecido`, categoria `Desconhecida` e confidence 0%.

Termos curtos, como `TIM`, usam limites de palavra para evitar correspondências acidentais. Regras específicas como `UBER *ONE` e `UBER EATS` precedem `UBER` genérico.

## Categorias customizadas

O arquivo deve usar:

```csv
categoria,palavras_chave,prioridade
Cafés,cafeteria|coffee shop|cafe expresso,10
```

- Separe palavras-chave por `|` ou `;`.
- Menor prioridade numérica é avaliada primeiro.
- O arquivo substitui as categorias comerciais padrão.
- As regras contábeis de pagamentos, créditos e tributos permanecem ativas.

Revise `data_quality.uncategorized_expense_pct` após cada execução. Acima de 10%, investigue as descrições mais relevantes antes de transformar as métricas em recomendações. A decisão aprovada é persistida na base de merchants e tem precedência sobre essas regras nas execuções seguintes.
