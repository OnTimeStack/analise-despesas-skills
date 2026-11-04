from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from expense_skills.cli import merchant_review_main
from expense_skills.models import OUTPUT_FIELDS


class MerchantReviewCliTests(unittest.TestCase):
    def test_prepare_and_approve_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "consolidado.csv"
            review_dir = root / "review"
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
                        "descricao": "LOJA SEM CADASTRO",
                        "parcela": "",
                        "valor": "10.00",
                        "tipo": "Despesa/Parcelamento",
                        "categoria": "",
                        "categoria_nativa": "",
                    }
                )

            result = merchant_review_main(
                [
                    "prepare",
                    str(source),
                    str(review_dir),
                    "--knowledge-base",
                    str(knowledge),
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((review_dir / "merchant_review.html").is_file())

            review_path = review_dir / "merchant_review.csv"
            with review_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = tuple(rows[0])
            rows[0].update(
                {
                    "nome_amigavel": "Loja Revisada",
                    "categoria": "Casa e Utilidades",
                    "aprovado": "sim",
                }
            )
            with review_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            result = merchant_review_main(
                ["approve", str(review_path), "--knowledge-base", str(knowledge)]
            )
            self.assertEqual(result, 0)
            self.assertIn("Loja Revisada", knowledge.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
