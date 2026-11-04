from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expense_skills.categorization import Categorizer
from expense_skills.models import Transaction
from expense_skills.parsing import ParseError, parse_money


class MoneyParsingTests(unittest.TestCase):
    def test_parses_brazilian_and_international_formats(self):
        self.assertEqual(parse_money("R$ 1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_money("1,234.56"), Decimal("1234.56"))
        self.assertEqual(parse_money("(42,10)"), Decimal("-42.10"))

    def test_rejects_invalid_money_instead_of_returning_zero(self):
        with self.assertRaises(ParseError):
            parse_money("valor desconhecido")


class CategorizationTests(unittest.TestCase):
    def _transaction(self, description: str, amount: str = "10.00", tipo: str = "") -> Transaction:
        return Transaction.from_mapping(
            {
                "banco": "Banco",
                "periodo_referencia": "Jan/2026",
                "data_transacao": "01/01/2026",
                "descricao": description,
                "valor": amount,
                "tipo": tipo,
            }
        )

    def test_specific_uber_rules_win_before_generic_transport(self):
        categorizer = Categorizer()
        self.assertEqual(
            categorizer.categorize(self._transaction("UBER *ONE")).category,
            "Serviços Recorrentes",
        )
        self.assertEqual(
            categorizer.categorize(self._transaction("UBER EATS")).category,
            "Restaurante e Lanchonete",
        )

    def test_short_keywords_use_word_boundaries(self):
        categorizer = Categorizer()
        self.assertNotEqual(
            categorizer.categorize(self._transaction("ULTIMATE SOFTWARE")).category,
            "Comunicação e Conectividade",
        )

    def test_credit_type_overrides_merchant_but_keeps_iof_reversal_as_tax(self):
        categorizer = Categorizer()
        refund = self._transaction("ESTORNO NETFLIX", "-10.00")
        tax_refund = self._transaction("DEVOLUCAO IOF", "-3.00")
        self.assertEqual(categorizer.categorize(refund).category, "Pagamentos e Créditos")
        self.assertEqual(categorizer.categorize(tax_refund).category, "Tributos e Encargos")

    def test_custom_categories_file_is_used(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "categories.csv"
            path.write_text(
                "categoria,palavras_chave,prioridade\nCafé,cafeteria|coffee,10\n",
                encoding="utf-8",
            )
            categorizer = Categorizer.from_csv(path)
            match = categorizer.categorize(self._transaction("COFFEE SHOP"))
            self.assertEqual(match.category, "Café")


if __name__ == "__main__":
    unittest.main()
