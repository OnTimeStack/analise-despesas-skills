# Esquema padronizado

Use UTF-8, separador vírgula e as colunas nesta ordem:

`banco,periodo_referencia,data_transacao,cartao,descricao,parcela,valor,tipo,categoria,categoria_nativa`

- `periodo_referencia`: `Mmm/AAAA`, com abreviações em português.
- `data_transacao`: `DD/MM/AAAA`; vazia somente quando a fonte não informa a data.
- `parcela`: `NN/NN` ou vazio.
- `valor`: duas casas decimais; positivo para despesa e negativo para crédito/pagamento.
- `tipo`: `Despesa/Parcelamento`, `Pagamento`, `Crédito` ou `Saldo Anterior`.
- `categoria`: vazia nesta etapa.

A chave de duplicidade é banco, data, descrição normalizada, valor, cartão e parcela. Uma conciliação aceita diferença máxima de R$ 0,02.

