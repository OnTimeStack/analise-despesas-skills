from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from expense_skills.analysis import AnalysisError, ExpenseAnalyzer
from expense_skills.merchants import MerchantKnowledgeBase
from expense_skills.models import OUTPUT_FIELDS


def write_transactions(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def row(period: str, description: str, value: str, **overrides: str) -> dict[str, str]:
    result = {
        "banco": "Banco A",
        "periodo_referencia": period,
        "data_transacao": "01/01/2026",
        "cartao": "1234",
        "descricao": description,
        "parcela": "",
        "valor": value,
        "tipo": "Despesa/Parcelamento",
        "categoria": "",
        "categoria_nativa": "",
    }
    result.update(overrides)
    return result


class AnalysisTests(unittest.TestCase):
    def test_excludes_previous_balance_and_advances_stale_installments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            rows = [
                row("Jan/2026", "SALDO ANTERIOR", "1000.00", tipo="Saldo Anterior"),
                row("Jan/2026", "COMPRA ANTIGA", "50.00", banco="Banco B", parcela="01/02"),
                row("Fev/2026", "IFOOD", "100.00"),
                row("Mar/2026", "IFOOD", "150.00"),
                row("Mar/2026", "OPENAI 1234", "50.00"),
                row("Mar/2026", "OPENAI 5678", "50.00"),
            ]
            write_transactions(source, rows)
            results = ExpenseAnalyzer(source, output_dir=root / "output").run()

            self.assertEqual(results["overview"]["total_latest"], 250.0)
            self.assertEqual(results["installments"]["count"], 0)
            self.assertEqual(results["recurring_services"]["possible_duplicates"], 1)
            self.assertEqual(results["recurring_services"]["items"][0]["descricao"], "OpenAI")
            self.assertEqual(results["merchant_enrichment"]["unique_merchants"], 4)
            self.assertEqual(results["data_quality"]["duplicates_removed"], 0)
            self.assertTrue(results["insights"])

    def test_exact_duplicates_do_not_inflate_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            duplicate = row("Jan/2026", "IFOOD", "100.00")
            write_transactions(source, [duplicate, duplicate])
            results = ExpenseAnalyzer(source, output_dir=root / "output").run()
            self.assertEqual(results["overview"]["total_latest"], 100.0)
            self.assertEqual(results["data_quality"]["duplicates_removed"], 1)

    def test_same_transaction_shape_in_different_periods_is_not_a_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            write_transactions(
                source,
                [
                    row("Jan/2026", "NETFLIX", "10.00"),
                    row("Fev/2026", "NETFLIX", "10.00"),
                ],
            )

            results = ExpenseAnalyzer(source, output_dir=root / "output").run()

            self.assertEqual(results["data_quality"]["duplicates_removed"], 0)
            self.assertEqual(results["data_quality"]["input_rows_after_deduplication"], 2)
            self.assertEqual(results["recurring_services"]["items"][0]["meses_observados"], 2)

    def test_invalid_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            write_transactions(source, [row("Jan/2026", "Compra", "???")])
            with self.assertRaises(AnalysisError):
                ExpenseAnalyzer(source, output_dir=root / "output").run()

    def test_requires_human_review_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            write_transactions(source, [row("Jan/2026", "NETFLIX", "10.00")])

            with self.assertRaisesRegex(AnalysisError, "revisão humana pendente"):
                ExpenseAnalyzer(
                    source,
                    output_dir=root / "output",
                    merchant_kb_path=root / "merchant_knowledge_base.csv",
                    require_reviewed=True,
                ).run()

    def test_approved_knowledge_enables_analysis_and_friendly_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            review = root / "review.csv"
            knowledge_path = root / "merchant_knowledge_base.csv"
            write_transactions(source, [row("Jan/2026", "LOJA ORIGINAL", "25.00")])
            review.write_text(
                "merchant_key,nome_original,variantes_originais,nome_amigavel,"
                "confidence_percent,categoria,origem_classificacao,ocorrencias,aprovado\n"
                "loja original,LOJA ORIGINAL,LOJA ORIGINAL,Loja Amigável,0,"
                "Casa e Utilidades,sem_evidencia_suficiente,1,sim\n",
                encoding="utf-8",
            )
            MerchantKnowledgeBase.load(knowledge_path).merge_review(review)

            results = ExpenseAnalyzer(
                source,
                output_dir=root / "output",
                merchant_kb_path=knowledge_path,
                require_reviewed=True,
            ).run()
            output = (root / "output" / "consolidado_categorizado.csv").read_text(encoding="utf-8")

            self.assertEqual(results["top_expenses"][0]["descricao"], "Loja Amigável")
            self.assertEqual(results["merchant_enrichment"]["knowledge_base_hits"], 1)
            self.assertIn("merchant_nome_amigavel", output)
            self.assertIn("Loja Amigável", output)


if __name__ == "__main__":
    unittest.main()
