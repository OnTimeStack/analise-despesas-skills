from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from expense_skills.merchants import (
    UNKNOWN_CATEGORY,
    UNKNOWN_MERCHANT,
    MerchantEnricher,
    MerchantKnowledgeBase,
    prepare_legacy_merchant_review,
    prepare_merchant_review,
)
from expense_skills.models import Transaction


def transaction(description: str) -> Transaction:
    return Transaction.from_mapping(
        {
            "banco": "Banco",
            "periodo_referencia": "Jan/2026",
            "data_transacao": "01/01/2026",
            "descricao": description,
            "valor": "10.00",
        }
    )


class MerchantEnrichmentTests(unittest.TestCase):
    def test_groups_unique_names_and_sorts_alphabetically(self):
        decisions = MerchantEnricher().build_decisions(
            [transaction("NETFLIX"), transaction("netflix"), transaction("ADOBE")]
        )

        self.assertEqual([item.original_name for item in decisions], ["ADOBE", "NETFLIX"])
        self.assertEqual(decisions[1].occurrences, 2)
        self.assertEqual(decisions[1].friendly_name, "Netflix")
        self.assertEqual(decisions[1].category, "Serviços Recorrentes")
        self.assertGreater(decisions[1].confidence_percent, 0)

    def test_ambiguous_description_fails_closed(self):
        decision = MerchantEnricher().build_decisions([transaction("SUPERMERCADO XYZ")])[0]

        self.assertEqual(decision.friendly_name, UNKNOWN_MERCHANT)
        self.assertEqual(decision.category, UNKNOWN_CATEGORY)
        self.assertEqual(decision.confidence_percent, 0)

    def test_approved_review_becomes_reusable_knowledge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            knowledge_path = root / "merchant_knowledge_base.csv"
            review_path = root / "merchant_review_approved.csv"
            decisions = MerchantEnricher().build_decisions([transaction("LOJA TESTE 42")])
            row = decisions[0].to_review_row()
            row.update(
                {
                    "nome_amigavel": "Loja Teste",
                    "categoria": "Casa e Utilidades",
                    "aprovado": "sim",
                }
            )
            with review_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=tuple(row))
                writer.writeheader()
                writer.writerow(row)

            knowledge = MerchantKnowledgeBase.load(knowledge_path)
            imported, pending = knowledge.merge_review(review_path)
            reloaded = MerchantKnowledgeBase.load(knowledge_path)
            decision = MerchantEnricher(knowledge_base=reloaded).build_decisions(
                [transaction("loja teste 42")]
            )[0]

            self.assertEqual((imported, pending), (1, 0))
            self.assertEqual(decision.friendly_name, "Loja Teste")
            self.assertEqual(decision.category, "Casa e Utilidades")
            self.assertEqual(decision.confidence_percent, 100)
            self.assertTrue(decision.approved)
            self.assertEqual(decision.source, "base_conhecimento")

    def test_review_html_is_self_contained_and_has_filters_and_sorting(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            prepare_merchant_review([transaction("NETFLIX")], output)
            page = (output / "merchant_review.html").read_text(encoding="utf-8")

            self.assertIn('data-sort="variantes_originais"', page)
            self.assertIn('data-filter="categoria"', page)
            self.assertIn("Baixar revisão CSV", page)
            self.assertNotIn("https://", page)
            self.assertNotIn("http://", page)

    def test_adapts_legacy_categories_without_auto_approving(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy.csv"
            source.write_text(
                "descricao,categoria,categoria_nativa\n"
                'NETFLIX,Serviços Recorrentes,"Serviços digitais"\n'
                'NETFLIX,Serviços Recorrentes,"Serviços digitais"\n'
                "LOJA CONFLITANTE,Casa e Utilidades,Varejo\n"
                "LOJA CONFLITANTE,Alimentação em Geral,Varejo\n"
                "COMPRA SEM CLASSE,Despesas Diversas,Empresa para empresa\n"
                "PAGAMENTO EFETUADO,Pagamentos e Créditos,-\n",
                encoding="utf-8",
            )

            decisions, summary = prepare_legacy_merchant_review(source, root / "output")
            by_original = {decision.original_name: decision for decision in decisions}

            self.assertEqual(summary["source_rows"], 6)
            self.assertEqual(summary["unique_source_merchants"], 4)
            self.assertEqual(summary["review_rows"], 3)
            self.assertEqual(summary["duplicates_collapsed"], 2)
            self.assertEqual(summary["excluded_non_merchants"], 1)
            self.assertEqual(summary["unresolved_category_conflicts"], 1)
            self.assertEqual(by_original["NETFLIX"].friendly_name, "Netflix")
            self.assertEqual(by_original["NETFLIX"].category, "Serviços Recorrentes")
            self.assertFalse(by_original["NETFLIX"].approved)
            self.assertEqual(by_original["LOJA CONFLITANTE"].category, UNKNOWN_CATEGORY)
            self.assertEqual(by_original["COMPRA SEM CLASSE"].category, UNKNOWN_CATEGORY)
            self.assertIn("Categorias nativas", by_original["NETFLIX"].classification_context)
            self.assertTrue((root / "output" / "legacy_import_report.json").is_file())

    def test_legacy_prefix_cleanup_does_not_truncate_ecommerce(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy.csv"
            source.write_text(
                "descricao,categoria\nECOMMERCE MI*MIZUNO BR,Despesas Diversas\n",
                encoding="utf-8",
            )

            decisions, _ = prepare_legacy_merchant_review(source, root / "output")

            self.assertEqual(decisions[0].friendly_name, "Ecommerce Mi Mizuno BR")

    def test_legacy_name_cleanup_removes_attached_numeric_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy.csv"
            source.write_text(
                "descricao,categoria\n57927841CAROLINA,Lazer e Entretenimento\n",
                encoding="utf-8",
            )

            decisions, _ = prepare_legacy_merchant_review(source, root / "output")

            self.assertEqual(decisions[0].friendly_name, "Carolina")


if __name__ == "__main__":
    unittest.main()
