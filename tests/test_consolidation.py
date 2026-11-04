from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from expense_skills.consolidation import ExpectedTotals, InvoiceConsolidator

FIELDS = [
    "banco",
    "periodo_referencia",
    "data_transacao",
    "cartao",
    "descricao",
    "parcela",
    "valor",
    "tipo",
    "categoria",
    "categoria_nativa",
]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class ConsolidationTests(unittest.TestCase):
    def test_deduplicates_and_reconciles_standardized_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            row = {
                "banco": "Banco A",
                "periodo_referencia": "Jan/2026",
                "data_transacao": "01/01/2026",
                "cartao": "1234",
                "descricao": "Compra",
                "parcela": "",
                "valor": "10,00",
                "tipo": "Despesa/Parcelamento",
                "categoria": "",
                "categoria_nativa": "",
            }
            write_csv(input_dir / "one.csv", [row, row])
            expected_path = root / "expected.csv"
            expected_path.write_text(
                "banco,periodo_referencia,total_esperado\nBanco A,Jan/2026,10.00\n",
                encoding="utf-8",
            )

            report = InvoiceConsolidator(
                input_dir,
                output_dir,
                expected_totals=ExpectedTotals.from_csv(expected_path),
            ).run()

            self.assertEqual(report.transactions, 1)
            self.assertEqual(report.duplicates_removed, 1)
            self.assertEqual(report.reconciliations[0].status, "conciliado")
            self.assertFalse(report.requires_confirmation)
            self.assertTrue((output_dir / "consolidado.csv").is_file())
            self.assertTrue((output_dir / "padronizado.zip").is_file())

    def test_groups_split_sources_and_ignores_nested_previous_output(self):
        with tempfile.TemporaryDirectory() as temp:
            input_dir = Path(temp)
            output_dir = input_dir / "output"
            base = {
                "banco": "Banco A",
                "periodo_referencia": "Jan/2026",
                "data_transacao": "01/01/2026",
                "cartao": "",
                "parcela": "",
                "tipo": "Despesa/Parcelamento",
                "categoria": "",
                "categoria_nativa": "",
            }
            write_csv(input_dir / "part-one.csv", [{**base, "descricao": "A", "valor": "6.00"}])
            write_csv(input_dir / "part-two.csv", [{**base, "descricao": "B", "valor": "4.00"}])
            expected_path = input_dir / "expected.csv"
            expected_path.write_text(
                "banco,periodo_referencia,total_esperado\nBanco A,Jan/2026,10.00\n",
                encoding="utf-8",
            )
            expected = ExpectedTotals.from_csv(expected_path)

            first = InvoiceConsolidator(input_dir, output_dir, expected_totals=expected).run()
            second = InvoiceConsolidator(input_dir, output_dir, expected_totals=expected).run()

            self.assertEqual(first.reconciliations[0].status, "conciliado")
            self.assertEqual(second.reconciliations[0].status, "conciliado")
            self.assertEqual(second.transactions, 2)
            self.assertEqual(sorted(second.processed_files), ["part-one.csv", "part-two.csv"])

    def test_reports_agent_assisted_files_without_inventing_transactions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "fatura.pdf").write_bytes(b"%PDF-placeholder")
            write_csv(
                input_dir / "data.csv",
                [
                    {
                        "banco": "Banco A",
                        "periodo_referencia": "Jan/2026",
                        "data_transacao": "01/01/2026",
                        "cartao": "",
                        "descricao": "Compra",
                        "parcela": "",
                        "valor": "10.00",
                        "tipo": "Despesa/Parcelamento",
                        "categoria": "",
                        "categoria_nativa": "",
                    }
                ],
            )
            report = InvoiceConsolidator(input_dir, output_dir).run()
            self.assertEqual(report.unsupported_files, ["fatura.pdf"])
            self.assertTrue(report.requires_confirmation)
            machine_report = json.loads((output_dir / "consolidation_report.json").read_text())
            self.assertEqual(machine_report["arquivos_nao_processados"], ["fatura.pdf"])

    def test_missing_expected_total_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fatura.csv"
            output = root / "output"
            write_csv(
                source,
                [
                    {
                        "banco": "Banco A",
                        "periodo_referencia": "Jan/2026",
                        "data_transacao": "01/01/2026",
                        "cartao": "",
                        "descricao": "Compra",
                        "parcela": "",
                        "valor": "10.00",
                        "tipo": "Despesa/Parcelamento",
                        "categoria": "",
                        "categoria_nativa": "",
                    }
                ],
            )

            report = InvoiceConsolidator(source, output).run()

            self.assertEqual(report.reconciliations[0].status, "não verificado")
            self.assertTrue(report.requires_confirmation)

    def test_reads_basic_ofx_without_external_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ofx = root / "statement.ofx"
            ofx.write_text(
                "OFXHEADER:100\n<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>\n"
                "<BANKTRANLIST><DTEND>20260131<STMTTRN><DTPOSTED>20260115\n"
                "<TRNAMT>-12.34<MEMO>CAFE</STMTTRN></BANKTRANLIST>\n"
                "<LEDGERBAL><BALAMT>12.34</LEDGERBAL><BANKNAME>Banco A</STMTRS></OFX>",
                encoding="utf-8",
            )
            output = root / "output"
            report = InvoiceConsolidator(ofx, output).run()
            self.assertEqual(report.transactions, 1)
            self.assertEqual(report.reconciliations[0].status, "conciliado")


if __name__ == "__main__":
    unittest.main()
