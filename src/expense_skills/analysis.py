"""Strategic expense analysis built on validated domain transactions."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from .categorization import Categorizer
from .merchants import (
    UNKNOWN_CATEGORY,
    MerchantDecision,
    MerchantEnricher,
    MerchantKnowledgeBase,
    merchant_key,
)
from .models import ANALYSIS_OUTPUT_FIELDS, Transaction, ValidationError
from .parsing import format_money, month_distance, normalize_text, parse_installment, period_key


class AnalysisError(RuntimeError):
    """Raised when an analysis input cannot be trusted."""


class ExpenseAnalyzer:
    def __init__(
        self,
        consolidado_path: Path,
        categories_path: Path | None = None,
        output_dir: Path | None = None,
        *,
        reclassify: bool = False,
        merchant_kb_path: Path | None = None,
        require_reviewed: bool = False,
    ):
        self.consolidado_path = Path(consolidado_path)
        self.output_dir = Path(output_dir or ".")
        self.categorizer = (
            Categorizer.from_csv(Path(categories_path)) if categories_path else Categorizer()
        )
        self.reclassify = reclassify
        self.merchant_knowledge_base = (
            MerchantKnowledgeBase.load(Path(merchant_kb_path)) if merchant_kb_path else None
        )
        self.require_reviewed = require_reviewed
        self.transactions: list[Transaction] = []
        self.periods: list[str] = []
        self.latest_period: str | None = None
        self.duplicates_removed = 0
        self.category_matches: dict[tuple[str, ...], float] = {}
        self.merchant_decisions: list[MerchantDecision] = []

    def run(self) -> dict[str, object]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        self._enrich_merchants()
        self._write_categorized_csv()

        overview = self._overview()
        categories = self._categories()
        recurring = self._recurring()
        installments = self._installments()
        trends = self._trends()
        quality = self._data_quality()
        savings = self._savings_potential(categories, recurring)
        results: dict[str, object] = {
            "overview": overview,
            "categories": categories,
            "banks_and_cards": self._banks_and_cards(),
            "installments": installments,
            "recurring_services": recurring,
            "top_expenses": self._top_expenses(),
            "category_details": self._category_details(),
            "trends": trends,
            "savings_potential": savings,
            "data_quality": quality,
            "merchant_enrichment": self._merchant_enrichment_summary(),
            "insights": self._insights(
                overview, categories, recurring, installments, trends, quality
            ),
        }
        (self.output_dir / "analysis_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return results

    def _load(self) -> None:
        if not self.consolidado_path.is_file():
            raise AnalysisError(f"consolidado não encontrado: {self.consolidado_path}")

        unique, self.duplicates_removed = load_transactions_csv(self.consolidado_path)
        self.transactions = unique
        self.periods = sorted(
            {transaction.periodo_referencia for transaction in unique}, key=period_key
        )
        self.latest_period = self.periods[-1] if self.periods else None

    def _enrich_merchants(self) -> None:
        self.merchant_decisions = MerchantEnricher(
            self.categorizer, self.merchant_knowledge_base
        ).build_decisions(self.transactions)
        pending = [decision for decision in self.merchant_decisions if not decision.approved]
        if self.require_reviewed and pending:
            raise AnalysisError(
                f"revisão humana pendente para {len(pending)} merchant(s) único(s); "
                "prepare, aprove e importe merchant_review.csv antes da análise"
            )

        decisions = {decision.merchant_key: decision for decision in self.merchant_decisions}
        enriched: list[Transaction] = []
        for transaction in self.transactions:
            if transaction.is_expense:
                decision = decisions[merchant_key(transaction.descricao)]
                enriched.append(
                    transaction.with_merchant(
                        friendly_name=decision.friendly_name,
                        category=decision.category,
                        confidence_percent=decision.confidence_percent,
                        reviewed=decision.approved,
                        source=decision.source,
                    )
                )
                self.category_matches[transaction.deduplication_key] = (
                    decision.confidence_percent / 100
                )
                continue
            if transaction.categoria and not self.reclassify:
                enriched.append(transaction)
                self.category_matches[transaction.deduplication_key] = 1.0
                continue
            match = self.categorizer.categorize(transaction)
            enriched.append(transaction.with_category(match.category))
            self.category_matches[transaction.deduplication_key] = match.confidence
        self.transactions = enriched

    def _expenses(self, period: str | None = None) -> list[Transaction]:
        return [
            transaction
            for transaction in self.transactions
            if transaction.is_expense
            and (period is None or transaction.periodo_referencia == period)
        ]

    def _overview(self) -> dict[str, object]:
        latest = self._expenses(self.latest_period)
        banks_latest = {transaction.banco for transaction in latest}
        banks_all = {transaction.banco for transaction in self.transactions}
        cards = {
            (transaction.banco, transaction.cartao) for transaction in latest if transaction.cartao
        }
        installments = [item for item in latest if parse_installment(item.parcela)]
        cash = [item for item in latest if not parse_installment(item.parcela)]
        return {
            "latest_period": self.latest_period,
            "all_periods": self.periods,
            "total_latest": _number(_sum(item.valor for item in latest)),
            "transaction_count_latest": len(latest),
            "banks_latest": sorted(banks_latest),
            "banks_all": sorted(banks_all),
            "banks_missing_latest": sorted(banks_all - banks_latest),
            "card_count": len(cards),
            "installment_total": _number(_sum(item.valor for item in installments)),
            "installment_count": len(installments),
            "avista_total": _number(_sum(item.valor for item in cash)),
            "avista_count": len(cash),
        }

    def _categories(self) -> list[dict[str, object]]:
        expenses = self._expenses(self.latest_period)
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        counts: Counter[str] = Counter()
        for transaction in expenses:
            totals[transaction.categoria or "Sem Categoria"] += transaction.valor
            counts[transaction.categoria or "Sem Categoria"] += 1
        grand_total = _sum(totals.values())
        return [
            {
                "categoria": category,
                "total": _number(total),
                "count": counts[category],
                "pct": round(float(total / grand_total * 100), 1) if grand_total else 0.0,
            }
            for category, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]

    def _banks_and_cards(self) -> list[dict[str, object]]:
        expenses = self._expenses(self.latest_period)
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        counts: Counter[str] = Counter()
        cards: dict[str, set[str]] = defaultdict(set)
        for transaction in expenses:
            totals[transaction.banco] += transaction.valor
            counts[transaction.banco] += 1
            if transaction.cartao:
                cards[transaction.banco].add(transaction.cartao)
        grand_total = _sum(totals.values())
        return [
            {
                "banco": bank,
                "total": _number(total),
                "count": counts[bank],
                "pct": round(float(total / grand_total * 100), 1) if grand_total else 0.0,
                "card_count": len(cards[bank]),
            }
            for bank, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]

    def _installments(self) -> dict[str, object]:
        if not self.latest_period:
            return _empty_installments()

        banks_latest = {item.banco for item in self._expenses(self.latest_period)}
        bank_periods: dict[str, list[str]] = defaultdict(list)
        for transaction in self.transactions:
            if transaction.is_expense:
                bank_periods[transaction.banco].append(transaction.periodo_referencia)

        candidates: list[dict[str, object]] = []
        for bank, periods in bank_periods.items():
            source_period = (
                self.latest_period if bank in banks_latest else max(set(periods), key=period_key)
            )
            elapsed = month_distance(source_period, self.latest_period)
            for transaction in self._expenses(source_period):
                if transaction.banco != bank:
                    continue
                parsed = parse_installment(transaction.parcela)
                if not parsed:
                    continue
                current, total = parsed
                adjusted_current = min(total, current + elapsed)
                remaining = total - adjusted_current
                if remaining <= 0:
                    continue
                candidates.append(
                    {
                        "descricao": transaction.display_name,
                        "descricao_original": transaction.descricao,
                        "valor_mensal": _number(transaction.valor),
                        "parcela_atual": adjusted_current,
                        "parcela_total": total,
                        "restantes": remaining,
                        "comprometido_futuro": _number(transaction.valor * remaining),
                        "categoria": transaction.categoria,
                        "banco": bank,
                        "cartao": transaction.cartao,
                        "periodo": source_period,
                        "estimado": elapsed > 0,
                    }
                )

        best: dict[tuple[object, ...], dict[str, object]] = {}
        for item in candidates:
            key = (
                normalize_text(item["descricao"]),
                item["valor_mensal"],
                item["banco"],
                item["cartao"],
                item["parcela_total"],
            )
            existing = best.get(key)
            if existing is None or _as_int(item["restantes"]) < _as_int(existing["restantes"]):
                best[key] = item
        unique = sorted(
            best.values(), key=lambda item: _as_float(item["comprometido_futuro"]), reverse=True
        )
        total_future = sum(
            (Decimal(str(item["comprometido_futuro"])) for item in unique), Decimal("0.00")
        )

        def bucket(items: list[dict[str, object]]) -> dict[str, object]:
            return {
                "count": len(items),
                "total_monthly": _number(
                    sum((Decimal(str(item["valor_mensal"])) for item in items), Decimal("0.00"))
                ),
            }

        return {
            "total_comprometido_futuro": _number(total_future),
            "count": len(unique),
            "items": unique[:20],
            "ending_soon": bucket([item for item in unique if _as_int(item["restantes"]) <= 2]),
            "ending_medium": bucket(
                [item for item in unique if 3 <= _as_int(item["restantes"]) <= 6]
            ),
            "ending_late": bucket([item for item in unique if _as_int(item["restantes"]) > 6]),
        }

    def _recurring(self) -> dict[str, object]:
        latest = [
            item
            for item in self._expenses(self.latest_period)
            if item.categoria == "Serviços Recorrentes"
        ]
        history: dict[str, set[str]] = defaultdict(set)
        for transaction in self._expenses():
            if transaction.categoria == "Serviços Recorrentes":
                history[merchant_key(transaction.display_name)].add(transaction.periodo_referencia)

        items = []
        merchant_counts = Counter(merchant_key(item.display_name) for item in latest)
        for transaction in sorted(latest, key=lambda item: item.valor, reverse=True):
            merchant = merchant_key(transaction.display_name)
            items.append(
                {
                    "descricao": transaction.display_name,
                    "descricao_original": transaction.descricao,
                    "valor": _number(transaction.valor),
                    "parcela": transaction.parcela,
                    "categoria_nativa": transaction.categoria_nativa,
                    "meses_observados": len(history[merchant]),
                    "possivel_duplicidade": merchant_counts[merchant] > 1,
                }
            )
        total = _sum(transaction.valor for transaction in latest)
        return {
            "items": items,
            "total": _number(total),
            "count": len(items),
            "annualized": _number(total * 12),
            "possible_duplicates": sum(1 for count in merchant_counts.values() if count > 1),
        }

    def _top_expenses(self) -> list[dict[str, object]]:
        return [
            {
                "descricao": item.display_name,
                "descricao_original": item.descricao,
                "valor": _number(item.valor),
                "categoria": item.categoria,
                "parcela": item.parcela,
                "banco": item.banco,
            }
            for item in sorted(
                self._expenses(self.latest_period), key=lambda item: item.valor, reverse=True
            )[:25]
        ]

    def _category_details(self) -> dict[str, object]:
        grouped: dict[str, list[Transaction]] = defaultdict(list)
        for transaction in self._expenses(self.latest_period):
            grouped[transaction.categoria or "Sem Categoria"].append(transaction)
        return {
            category: {
                "items": [
                    {
                        "descricao": item.display_name,
                        "descricao_original": item.descricao,
                        "valor": _number(item.valor),
                        "parcela": item.parcela,
                    }
                    for item in sorted(items, key=lambda item: item.valor, reverse=True)[:15]
                ],
                "total": _number(_sum(item.valor for item in items)),
                "count": len(items),
            }
            for category, items in grouped.items()
        }

    def _trends(self) -> list[dict[str, object]]:
        matrix: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal("0.00"))
        )
        for transaction in self._expenses():
            matrix[transaction.categoria][transaction.periodo_referencia] += transaction.valor

        results: list[dict[str, object]] = []
        for category, monthly_values in matrix.items():
            values = [monthly_values.get(period, Decimal("0.00")) for period in self.periods]
            recent = values[-3:]
            previous = values[-6:-3]
            recent_average = _sum(recent) / len(recent) if recent else Decimal("0.00")
            previous_average = _sum(previous) / len(previous) if previous else Decimal("0.00")
            if previous and previous_average > 0:
                change = float((recent_average - previous_average) / previous_average * 100)
                label = f"{change:+.1f}%"
                direction = "alta" if change > 10 else "queda" if change < -10 else "estável"
            elif recent_average > 0 and previous:
                change, label, direction = None, "novo", "novo"
            elif len(values) >= 2 and values[-2] > 0:
                change = float((values[-1] - values[-2]) / values[-2] * 100)
                label = f"{change:+.1f}%"
                direction = "alta" if change > 10 else "queda" if change < -10 else "estável"
            else:
                change, label, direction = None, "—", "insuficiente"
            results.append(
                {
                    "categoria": category,
                    "total": _number(_sum(values)),
                    "tendencia": label,
                    "change_pct": round(change, 1) if change is not None else None,
                    "direction": direction,
                    "monthly": {
                        period: _number(monthly_values.get(period, Decimal("0.00")))
                        for period in self.periods
                    },
                    "growing": change is not None and change > 10,
                    "is_spike": change is not None and change > 50,
                }
            )
        return sorted(results, key=lambda item: _as_float(item["total"]), reverse=True)

    def _savings_potential(
        self, categories: list[dict[str, object]], recurring: dict[str, object]
    ) -> dict[str, object]:
        totals = {item["categoria"]: Decimal(str(item["total"])) for item in categories}
        total_expenses = _sum(totals.values())
        recurring_total = Decimal(str(recurring["total"]))
        conservative = recurring_total * Decimal("0.50")
        discretionary = _sum(
            totals.get(category, Decimal("0.00"))
            for category in (
                "Restaurante e Lanchonete",
                "Lazer e Entretenimento",
                "Vestuário e Cuidados Pessoais",
            )
        )
        moderate = conservative + discretionary * Decimal("0.20")
        optimistic = moderate + totals.get("Alimentação em Geral", Decimal("0.00")) * Decimal(
            "0.15"
        )
        conservative = min(conservative, total_expenses)
        moderate = min(moderate, total_expenses)
        optimistic = min(optimistic, total_expenses)
        return {
            "conservative": _number(conservative),
            "moderate": _number(moderate),
            "optimistic": _number(optimistic),
            "total_expenses": _number(total_expenses),
            "conservative_pct": _pct(conservative, total_expenses),
            "moderate_pct": _pct(moderate, total_expenses),
            "optimistic_pct": _pct(optimistic, total_expenses),
            "assumptions": {
                "recurring_reduction_pct": 50,
                "discretionary_reduction_pct": 20,
                "food_optimization_pct": 15,
                "note": "Estimativas, não economia garantida; validar cada ação com o usuário.",
            },
        }

    def _data_quality(self) -> dict[str, object]:
        expenses = self._expenses()
        unknown = [item for item in expenses if item.categoria == UNKNOWN_CATEGORY]
        low_confidence = [
            item
            for item in expenses
            if self.category_matches.get(item.deduplication_key, 1.0) < 0.5
        ]
        return {
            "input_rows_after_deduplication": len(self.transactions),
            "duplicates_removed": self.duplicates_removed,
            "period_count": len(self.periods),
            "uncategorized_expense_count": len(unknown),
            "uncategorized_expense_pct": round(len(unknown) / len(expenses) * 100, 1)
            if expenses
            else 0.0,
            "low_confidence_category_count": len(low_confidence),
            "merchant_review_required": sum(
                1 for decision in self.merchant_decisions if not decision.approved
            ),
            "reliable_for_trends": len(self.periods) >= 3,
        }

    def _merchant_enrichment_summary(self) -> dict[str, object]:
        return {
            "unique_merchants": len(self.merchant_decisions),
            "approved_merchants": sum(
                1 for decision in self.merchant_decisions if decision.approved
            ),
            "pending_review": sum(
                1 for decision in self.merchant_decisions if not decision.approved
            ),
            "unknown_merchants": sum(
                1
                for decision in self.merchant_decisions
                if decision.friendly_name == "Desconhecido" or decision.category == UNKNOWN_CATEGORY
            ),
            "knowledge_base_hits": sum(
                1 for decision in self.merchant_decisions if decision.source == "base_conhecimento"
            ),
        }

    def _insights(
        self,
        overview: dict[str, object],
        categories: list[dict[str, object]],
        recurring: dict[str, object],
        installments: dict[str, object],
        trends: list[dict[str, object]],
        quality: dict[str, object],
    ) -> list[dict[str, object]]:
        insights: list[dict[str, object]] = []
        if categories:
            top = categories[0]
            insights.append(
                {
                    "priority": "alta" if _as_float(top["pct"]) >= 30 else "média",
                    "type": "concentração",
                    "title": f"{top['categoria']} concentra {top['pct']}% do período mais recente",
                    "evidence": {"amount": top["total"], "period": self.latest_period},
                }
            )
        if _as_int(recurring.get("possible_duplicates", 0)):
            insights.append(
                {
                    "priority": "alta",
                    "type": "possível duplicidade recorrente",
                    "title": "Há cobranças recorrentes repetidas que merecem conferência",
                    "evidence": {"merchant_groups": recurring["possible_duplicates"]},
                }
            )
        spikes = [item for item in trends if item.get("is_spike")]
        if spikes:
            spike = max(spikes, key=lambda item: _as_float(item.get("change_pct") or 0))
            insights.append(
                {
                    "priority": "alta",
                    "type": "tendência",
                    "title": f"{spike['categoria']} cresceu {spike['tendencia']} na janela recente",
                    "evidence": {"change_pct": spike["change_pct"]},
                }
            )
        latest_total = Decimal(str(overview.get("total_latest", 0)))
        installment_monthly = Decimal(str(overview.get("installment_total", 0)))
        if latest_total and installment_monthly / latest_total >= Decimal("0.30"):
            insights.append(
                {
                    "priority": "média",
                    "type": "comprometimento",
                    "title": "Parcelamentos representam pelo menos 30% do período mais recente",
                    "evidence": {
                        "monthly_installments": float(installment_monthly),
                        "future_commitment": installments.get("total_comprometido_futuro", 0),
                    },
                }
            )
        if _as_float(quality.get("uncategorized_expense_pct", 0)) > 10:
            insights.append(
                {
                    "priority": "média",
                    "type": "qualidade dos dados",
                    "title": "Mais de 10% das despesas precisam de revisão de categoria",
                    "evidence": {"pct": quality["uncategorized_expense_pct"]},
                }
            )
        return insights

    def _write_categorized_csv(self) -> None:
        path = self.output_dir / "consolidado_categorizado.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ANALYSIS_OUTPUT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(transaction.to_analysis_csv_row() for transaction in self.transactions)


def load_transactions_csv(path: Path) -> tuple[list[Transaction], int]:
    """Load, validate and deduplicate a consolidated transaction file."""
    path = Path(path)
    if not path.is_file():
        raise AnalysisError(f"consolidado não encontrado: {path}")

    loaded: list[Transaction] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"banco", "periodo_referencia", "descricao", "valor"}
        if not required.issubset(set(reader.fieldnames or [])):
            missing = ", ".join(sorted(required - set(reader.fieldnames or [])))
            raise AnalysisError(f"colunas obrigatórias ausentes: {missing}")
        for line_number, row in enumerate(reader, start=2):
            if not any(row.values()):
                continue
            try:
                loaded.append(Transaction.from_mapping(row, source=path.name))
            except (ValidationError, ValueError) as exc:
                errors.append(f"linha {line_number}: {exc}")
    if errors:
        preview = "; ".join(errors[:5])
        suffix = f"; e mais {len(errors) - 5}" if len(errors) > 5 else ""
        raise AnalysisError(f"entrada inválida; nenhuma análise foi gerada: {preview}{suffix}")
    if not loaded:
        raise AnalysisError("consolidado sem transações")

    unique: list[Transaction] = []
    seen: set[tuple[str, ...]] = set()
    for transaction in loaded:
        if transaction.deduplication_key in seen:
            continue
        seen.add(transaction.deduplication_key)
        unique.append(transaction)
    return unique, len(loaded) - len(unique)


def _sum(values) -> Decimal:
    return sum(values, Decimal("0.00"))


def _number(value: Decimal) -> float:
    return float(format_money(value))


def _pct(value: Decimal, total: Decimal) -> float:
    return round(float(value / total * 100), 1) if total else 0.0


def _as_float(value: object) -> float:
    return float(str(value))


def _as_int(value: object) -> int:
    return int(str(value))


def _empty_installments() -> dict[str, object]:
    empty_bucket = {"count": 0, "total_monthly": 0.0}
    return {
        "total_comprometido_futuro": 0.0,
        "count": 0,
        "items": [],
        "ending_soon": empty_bucket,
        "ending_medium": empty_bucket,
        "ending_late": empty_bucket,
    }
