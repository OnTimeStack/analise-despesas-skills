"""Deterministic ingestion, reconciliation, deduplication, and consolidation."""

from __future__ import annotations

import csv
import json
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, Protocol

from .models import OUTPUT_FIELDS, Transaction, ValidationError
from .parsing import (
    ParseError,
    format_money,
    format_period,
    normalize_text,
    parse_money,
    parse_period,
    period_key,
)

SUPPORTED_EXTENSIONS = {".csv", ".ofx"}
AGENT_ASSISTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


class ConsolidationError(RuntimeError):
    """Raised when consolidation cannot continue without risking bad data."""


@dataclass(slots=True)
class ExtractedDocument:
    source: Path
    transactions: list[Transaction]
    bank: str
    period: str
    expected_total: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    bank: str
    period: str
    calculated: Decimal
    expected: Decimal | None
    difference: Decimal | None
    status: str
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "banco": self.bank,
            "periodo": self.period,
            "calculado": float(self.calculated),
            "esperado": float(self.expected) if self.expected is not None else None,
            "diferenca": float(self.difference) if self.difference is not None else None,
            "status": self.status,
            "origem": self.source,
        }


@dataclass(slots=True)
class ConsolidationReport:
    transactions: int = 0
    duplicates_removed: int = 0
    processed_files: list[str] = field(default_factory=list)
    unsupported_files: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    reconciliations: list[ReconciliationResult] = field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        return bool(
            self.unsupported_files
            or self.validation_errors
            or any(item.status != "conciliado" for item in self.reconciliations)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "transacoes": self.transactions,
            "duplicatas_removidas": self.duplicates_removed,
            "arquivos_processados": self.processed_files,
            "arquivos_nao_processados": self.unsupported_files,
            "erros_validacao": self.validation_errors,
            "reconciliacoes": [item.to_dict() for item in self.reconciliations],
            "requer_confirmacao": self.requires_confirmation,
        }


class Extractor(Protocol):
    def supports(self, path: Path) -> bool: ...

    def extract(self, path: Path) -> ExtractedDocument: ...


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    sample = path.read_text(encoding="utf-8-sig")[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, dialect=dialect)
        return list(reader.fieldnames or []), list(reader)


class StandardCsvExtractor:
    REQUIRED: ClassVar[set[str]] = {"banco", "periodo_referencia", "descricao", "valor"}

    def supports(self, path: Path) -> bool:
        if path.suffix.casefold() != ".csv":
            return False
        try:
            headers, _ = _read_csv(path)
        except (OSError, UnicodeError, csv.Error):
            return False
        return self.REQUIRED.issubset({normalize_text(header) for header in headers})

    def extract(self, path: Path) -> ExtractedDocument:
        _, rows = _read_csv(path)
        transactions = [
            Transaction.from_mapping(row, source=path.name) for row in rows if any(row.values())
        ]
        if not transactions:
            raise ConsolidationError(f"CSV padronizado sem transações: {path.name}")
        banks = {transaction.banco for transaction in transactions}
        periods = {transaction.periodo_referencia for transaction in transactions}
        bank = next(iter(banks)) if len(banks) == 1 else "Múltiplas origens"
        period = next(iter(periods)) if len(periods) == 1 else "Múltiplos períodos"
        return ExtractedDocument(path, transactions, bank, period)


class C6CsvExtractor:
    REQUIRED: ClassVar[set[str]] = {"valor (em r$)", "data de compra", "descricao"}

    def supports(self, path: Path) -> bool:
        if path.suffix.casefold() != ".csv":
            return False
        try:
            headers, _ = _read_csv(path)
        except (OSError, UnicodeError, csv.Error):
            return False
        return self.REQUIRED.issubset({normalize_text(header) for header in headers})

    def extract(self, path: Path) -> ExtractedDocument:
        headers, rows = _read_csv(path)
        normalized_headers = {normalize_text(header): header for header in headers}
        period = _period_from_filename(path.name)
        if not period:
            raise ConsolidationError(
                f"não foi possível determinar o período de {path.name}; inclua Mmm-AAAA no nome"
            )
        transactions: list[Transaction] = []
        for row in rows:
            mapped = {
                "banco": "C6 Bank",
                "periodo_referencia": period,
                "data_transacao": row.get(normalized_headers.get("data de compra", ""), ""),
                "cartao": row.get(normalized_headers.get("final do cartao", ""), ""),
                "descricao": row.get(normalized_headers.get("descricao", ""), ""),
                "parcela": row.get(normalized_headers.get("parcela", ""), ""),
                "valor": row.get(normalized_headers.get("valor (em r$)", ""), ""),
                "categoria_nativa": row.get(normalized_headers.get("categoria", ""), ""),
            }
            transactions.append(Transaction.from_mapping(mapped, source=path.name))
        return ExtractedDocument(path, transactions, "C6 Bank", period)


class OfxExtractor:
    def supports(self, path: Path) -> bool:
        return path.suffix.casefold() == ".ofx"

    def extract(self, path: Path) -> ExtractedDocument:
        content = _read_text_fallback(path)
        bank = _ofx_tag(content, "BANKNAME") or _ofx_tag(content, "ORG") or path.stem.split("-")[0]
        date_value = _ofx_tag(content, "DTEND") or _ofx_tag(content, "DTASOF")
        period = _period_from_ofx_date(date_value) or _period_from_filename(path.name)
        if not period:
            raise ConsolidationError(f"OFX sem período identificável: {path.name}")

        blocks = re.findall(
            r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|</CCSTMTRS>|$)",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        transactions: list[Transaction] = []
        for block in blocks:
            amount_raw = _ofx_tag(block, "TRNAMT")
            date_raw = _ofx_tag(block, "DTPOSTED")
            description = _ofx_tag(block, "MEMO") or _ofx_tag(block, "NAME")
            if not amount_raw or not date_raw or not description:
                continue
            amount = -parse_money(amount_raw)
            posted = re.sub(r"\D", "", date_raw)[:8]
            if len(posted) != 8:
                raise ConsolidationError(f"data OFX inválida em {path.name}: {date_raw!r}")
            installment_match = re.search(r"parcela\s+(\d+\s*/\s*\d+)", description, re.IGNORECASE)
            installment = installment_match.group(1) if installment_match else ""
            if installment_match:
                description = re.sub(
                    r"\s*-?\s*parcela\s+\d+\s*/\s*\d+", "", description, flags=re.IGNORECASE
                ).strip()
            mapped = {
                "banco": bank,
                "periodo_referencia": period,
                "data_transacao": f"{posted[6:8]}/{posted[4:6]}/{posted[:4]}",
                "cartao": "",
                "descricao": description,
                "parcela": installment,
                "valor": amount,
            }
            transactions.append(Transaction.from_mapping(mapped, source=path.name))
        if not transactions:
            raise ConsolidationError(f"OFX sem blocos STMTTRN válidos: {path.name}")

        balance_raw = _ofx_tag(content, "BALAMT")
        expected = abs(parse_money(balance_raw)) if balance_raw else None
        return ExtractedDocument(path, transactions, bank, period, expected)


class ExpectedTotals:
    def __init__(
        self,
        values: dict[tuple[str, str], Decimal] | None = None,
        *,
        source: Path | None = None,
    ):
        self.values = values or {}
        self.source = source

    @classmethod
    def from_csv(cls, path: Path) -> ExpectedTotals:
        _, rows = _read_csv(path)
        values: dict[tuple[str, str], Decimal] = {}
        for line_number, row in enumerate(rows, start=2):
            bank = str(row.get("banco") or "").strip()
            period = str(row.get("periodo_referencia") or row.get("periodo") or "").strip()
            amount = row.get("total_esperado") or row.get("expected_total")
            if not bank or not period or amount in (None, ""):
                raise ConsolidationError(f"totais esperados inválidos na linha {line_number}")
            parse_period(period)
            values[(normalize_text(bank), period)] = parse_money(amount)
        return cls(values, source=path.resolve())

    def get(self, bank: str, period: str) -> Decimal | None:
        return self.values.get((normalize_text(bank), period))


class InvoiceConsolidator:
    """Application service orchestrating extractors and output adapters."""

    def __init__(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        expected_totals: ExpectedTotals | None = None,
        extractors: tuple[Extractor, ...] | None = None,
    ):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.expected_totals = expected_totals or ExpectedTotals()
        self.extractors = extractors or (StandardCsvExtractor(), C6CsvExtractor(), OfxExtractor())

    def run(self) -> ConsolidationReport:
        if not self.input_path.exists():
            raise ConsolidationError(f"entrada não encontrada: {self.input_path}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report = ConsolidationReport()
        documents: list[ExtractedDocument] = []

        with tempfile.TemporaryDirectory(prefix="expense-skills-") as temporary:
            excluded_files = {self.expected_totals.source} if self.expected_totals.source else set()
            files = _discover_files(
                self.input_path,
                Path(temporary),
                excluded_files=excluded_files,
                excluded_roots={self.output_dir.resolve()},
            )
            for path in files:
                extractor = next((item for item in self.extractors if item.supports(path)), None)
                if extractor is None:
                    if (
                        path.suffix.casefold() in AGENT_ASSISTED_EXTENSIONS
                        or path.suffix.casefold() not in SUPPORTED_EXTENSIONS
                    ):
                        report.unsupported_files.append(path.name)
                    continue
                try:
                    document = extractor.extract(path)
                except (
                    ConsolidationError,
                    ValidationError,
                    ParseError,
                    OSError,
                    UnicodeError,
                ) as exc:
                    report.validation_errors.append(f"{path.name}: {exc}")
                    continue
                documents.append(document)
                report.processed_files.append(path.name)

        if not documents:
            self._write_report(report)
            raise ConsolidationError("nenhum arquivo pôde ser processado com segurança")

        all_transactions = [
            transaction for document in documents for transaction in document.transactions
        ]
        unique_transactions, duplicates = _deduplicate(all_transactions)
        report.duplicates_removed = duplicates
        report.transactions = len(unique_transactions)
        report.reconciliations = self._reconcile_all(documents)

        self._write_outputs(unique_transactions, report)
        return report

    def _reconcile_all(self, documents: list[ExtractedDocument]) -> list[ReconciliationResult]:
        grouped: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
        sources: dict[tuple[str, str], set[str]] = defaultdict(set)
        document_expected: dict[tuple[str, str], Decimal] = {}
        for document in documents:
            for transaction in document.transactions:
                key = (transaction.banco, transaction.periodo_referencia)
                grouped[key].append(transaction)
                sources[key].add(document.source.name)
            if (
                document.expected_total is not None
                and document.bank != "Múltiplas origens"
                and document.period != "Múltiplos períodos"
            ):
                document_expected[(document.bank, document.period)] = document.expected_total

        results = []
        for (bank, period), transactions in sorted(
            grouped.items(), key=lambda item: (normalize_text(item[0][0]), period_key(item[0][1]))
        ):
            expected = self.expected_totals.get(bank, period)
            if expected is None:
                expected = document_expected.get((bank, period))
            results.append(
                self._reconcile_group(
                    bank,
                    period,
                    transactions,
                    expected,
                    ", ".join(sorted(sources[(bank, period)])),
                )
            )
        return results

    @staticmethod
    def _reconcile_group(
        bank: str,
        period: str,
        transactions: list[Transaction],
        expected: Decimal | None,
        source: str,
    ) -> ReconciliationResult:
        document_transactions, _ = _deduplicate(transactions)
        calculated = sum(
            (
                transaction.valor
                for transaction in document_transactions
                if transaction.tipo != "Pagamento"
            ),
            Decimal("0.00"),
        )
        if expected is None:
            return ReconciliationResult(
                bank, period, calculated, None, None, "não verificado", source
            )
        difference = calculated - expected
        status = "conciliado" if abs(difference) <= Decimal("0.02") else "divergente"
        return ReconciliationResult(bank, period, calculated, expected, difference, status, source)

    def _write_outputs(self, transactions: list[Transaction], report: ConsolidationReport) -> None:
        standardized_dir = self.output_dir / "padronizado"
        standardized_dir.mkdir(parents=True, exist_ok=True)
        by_bank: dict[str, list[Transaction]] = defaultdict(list)
        for transaction in transactions:
            by_bank[transaction.banco].append(transaction)

        for bank, bank_transactions in sorted(
            by_bank.items(), key=lambda item: normalize_text(item[0])
        ):
            filename = f"faturas_{_slug(bank)}.csv"
            _write_transactions(standardized_dir / filename, bank_transactions)

        _write_transactions(self.output_dir / "consolidado.csv", transactions)
        with zipfile.ZipFile(
            self.output_dir / "padronizado.zip", "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(standardized_dir.glob("*.csv")):
                archive.write(path, path.name)
        self._write_report(report)
        self._write_summary(report, by_bank)

    def _write_report(self, report: ConsolidationReport) -> None:
        path = self.output_dir / "consolidation_report.json"
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_summary(
        self, report: ConsolidationReport, by_bank: dict[str, list[Transaction]]
    ) -> None:
        lines = [
            "Consolidation Summary",
            "=====================",
            f"Transactions: {report.transactions}",
            f"Duplicates removed: {report.duplicates_removed}",
            "",
            "Reconciliation:",
        ]
        for item in report.reconciliations:
            expected = format_money(item.expected) if item.expected is not None else "n/a"
            difference = format_money(item.difference) if item.difference is not None else "n/a"
            calculated = format_money(item.calculated)
            lines.append(
                f"- {item.bank} {item.period}: {item.status}; calculated={calculated}; "
                f"expected={expected}; difference={difference}"
            )
        if report.unsupported_files:
            lines.extend(("", "Files requiring agent-assisted extraction:"))
            lines.extend(f"- {name}" for name in report.unsupported_files)
        if report.validation_errors:
            lines.extend(("", "Validation errors:"))
            lines.extend(f"- {error}" for error in report.validation_errors)
        lines.extend(("", "Totals by bank:"))
        for bank, transactions in sorted(by_bank.items(), key=lambda item: normalize_text(item[0])):
            total = sum((transaction.valor for transaction in transactions), Decimal("0.00"))
            lines.append(f"- {bank}: {format_money(total)}")
        (self.output_dir / "consolidation_summary.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _write_transactions(path: Path, transactions: list[Transaction]) -> None:
    ordered = sorted(
        transactions,
        key=lambda item: (
            normalize_text(item.banco),
            period_key(item.periodo_referencia),
            item.data_transacao,
            normalize_text(item.descricao),
        ),
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(transaction.to_csv_row() for transaction in ordered)


def _deduplicate(transactions: list[Transaction]) -> tuple[list[Transaction], int]:
    seen: set[tuple[str, ...]] = set()
    unique: list[Transaction] = []
    for transaction in transactions:
        key = transaction.deduplication_key
        if key in seen:
            continue
        seen.add(key)
        unique.append(transaction)
    return unique, len(transactions) - len(unique)


def _discover_files(
    input_path: Path,
    temporary_root: Path,
    *,
    excluded_files: set[Path] | None = None,
    excluded_roots: set[Path] | None = None,
) -> list[Path]:
    excluded_files = {path.resolve() for path in (excluded_files or set())}
    excluded_roots = {path.resolve() for path in (excluded_roots or set())}
    initial = (
        [input_path]
        if input_path.is_file()
        else sorted(path for path in input_path.rglob("*") if path.is_file())
    )
    discovered: list[Path] = []
    for path in initial:
        resolved = path.resolve()
        if resolved in excluded_files or any(
            resolved.is_relative_to(root) for root in excluded_roots
        ):
            continue
        if path.suffix.casefold() != ".zip":
            discovered.append(path)
            continue
        extract_dir = temporary_root / _slug(path.stem)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                destination = (extract_dir / member.filename).resolve()
                if not destination.is_relative_to(extract_dir.resolve()):
                    raise ConsolidationError(f"ZIP contém caminho inseguro: {member.filename}")
            archive.extractall(extract_dir)
        discovered.extend(sorted(item for item in extract_dir.rglob("*") if item.is_file()))
    return discovered


def _read_text_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ConsolidationError(f"codificação não suportada: {path.name}")


def _ofx_tag(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*([^<\r\n]+)", content, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _period_from_ofx_date(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 6:
        return ""
    year, month = int(digits[:4]), int(digits[4:6])
    return format_period(year, month) if 1 <= month <= 12 else ""


def _period_from_filename(filename: str) -> str:
    normalized = normalize_text(filename)
    month_names = "|".join(
        ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    )
    match = re.search(rf"(?:^|\W)({month_names})[a-z]*\W+(20\d{{2}})(?:\W|$)", normalized)
    if match:
        year, month = parse_period(f"{match.group(1).capitalize()}/{match.group(2)}")
        return format_period(year, month)
    match = re.search(r"(20\d{2})[-_ ](0?[1-9]|1[0-2])", normalized)
    if match:
        return format_period(int(match.group(1)), int(match.group(2)))
    return ""


def _slug(value: str) -> str:
    normalized = normalize_text(value)
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "origem"
