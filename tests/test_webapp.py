from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from expense_skills.models import OUTPUT_FIELDS
from expense_skills.webapp import ExpenseReviewApplication


class ExpenseReviewApplicationTests(unittest.TestCase):
    def test_save_updates_knowledge_base_and_insights_locally(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            knowledge = root / "merchant_knowledge_base.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
                writer.writeheader()
                writer.writerow(
                    {
                        "banco": "Banco",
                        "periodo_referencia": "Jan/2026",
                        "data_transacao": "01/01/2026",
                        "cartao": "1234",
                        "descricao": "NETFLIX",
                        "parcela": "",
                        "valor": "39.90",
                        "tipo": "Despesa/Parcelamento",
                        "categoria": "",
                        "categoria_nativa": "",
                    }
                )

            application = ExpenseReviewApplication(
                source,
                root / "output",
                knowledge,
            )
            rows = [decision.to_review_row() for decision in application.decisions]
            rows[0].update(
                {
                    "nome_amigavel": "Netflix Brasil",
                    "categoria": "Serviços Recorrentes",
                    "aprovado": "sim",
                }
            )

            result = application.save_review(rows)

            self.assertTrue(result["insights_updated_locally"])
            self.assertFalse(result["ai_reprocessing_required"])
            self.assertEqual(result["pending_review"], 0)
            self.assertIn("Netflix Brasil", knowledge.read_text(encoding="utf-8"))
            self.assertIn("Netflix Brasil", application.insights_html)
            self.assertIn('href="/classification"', application.insights_html)
            self.assertIn("Salvar rascunho", application.review_html)
            self.assertIn("Aprovar selecionados e atualizar insights", application.review_html)
            self.assertIn("Plano estratégico de redução", application.insights_html)
            self.assertIn("Potencial de economia", application.insights_html)
            self.assertIn("Previsão de encerramento", application.insights_html)
            self.assertTrue((root / "output" / "analysis_results.json").is_file())
            self.assertTrue((root / "output" / "merchant_review.html").is_file())
            self.assertTrue((root / "output" / "analise_estrategica_despesas.html").is_file())

    def test_unapproved_edits_remain_drafts_without_changing_knowledge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            knowledge = root / "merchant_knowledge_base.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
                writer.writeheader()
                writer.writerow(
                    {
                        "banco": "Banco",
                        "periodo_referencia": "Jan/2026",
                        "data_transacao": "01/01/2026",
                        "cartao": "1234",
                        "descricao": "LOJA SEM REGRA",
                        "parcela": "",
                        "valor": "10.00",
                        "tipo": "Despesa/Parcelamento",
                        "categoria": "",
                        "categoria_nativa": "",
                    }
                )
            application = ExpenseReviewApplication(source, root / "output", knowledge)
            rows = [decision.to_review_row() for decision in application.decisions]
            rows[0].update(
                {
                    "nome_amigavel": "Rascunho Loja",
                    "categoria": "Casa e Utilidades",
                    "aprovado": "nao",
                }
            )

            result = application.save_review(rows, mode="draft")

            self.assertEqual(result["pending_review"], 1)
            self.assertFalse(result["insights_updated_locally"])
            self.assertEqual(result["next_url"], "/classification")
            self.assertNotIn("Rascunho Loja", knowledge.read_text(encoding="utf-8"))
            self.assertEqual(application.decisions[0].friendly_name, "Rascunho Loja")
            self.assertTrue((root / "output" / "merchant_review_draft.csv").is_file())

            with self.assertRaisesRegex(ValueError, "nenhum merchant foi aprovado"):
                application.save_review(rows, mode="approve")


if __name__ == "__main__":
    unittest.main()
