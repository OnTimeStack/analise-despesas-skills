"""Domain models and invariants for financial transactions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from .parsing import (
    format_money,
    normalize_date,
    normalize_text,
    normalized_installment,
    parse_money,
    parse_period,
)

OUTPUT_FIELDS = (
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
)
ANALYSIS_OUTPUT_FIELDS = (
    *OUTPUT_FIELDS,
    "merchant_nome_amigavel",
    "merchant_confidence",
    "merchant_revisado",
    "merchant_origem",
)
NON_EXPENSE_TYPES = {"pagamento", "credito", "saldo anterior"}


class ValidationError(ValueError):
    """Raised when a transaction violates a domain invariant."""


def classify_transaction(description: str, amount: Decimal) -> str:
    normalized = normalize_text(description)
    if "saldo anterior" in normalized:
        return "Saldo Anterior"
    if amount < 0:
        payment_terms = ("pagamento", "inclusao", "antecipacao")
        return "Pagamento" if any(term in normalized for term in payment_terms) else "Crédito"
    return "Despesa/Parcelamento"


@dataclass(frozen=True, slots=True)
class Transaction:
    banco: str
    periodo_referencia: str
    data_transacao: str
    cartao: str
    descricao: str
    parcela: str
    valor: Decimal
    tipo: str
    categoria: str = ""
    categoria_nativa: str = ""
    origem: str = ""
    merchant_nome_amigavel: str = ""
    merchant_confidence: int = 0
    merchant_revisado: bool = False
    merchant_origem: str = ""

    @classmethod
    def from_mapping(cls, row: Mapping[str, object], *, source: str = "") -> Transaction:
        banco = str(row.get("banco") or "").strip()
        periodo = str(row.get("periodo_referencia") or "").strip()
        descricao = str(row.get("descricao") or "").strip()
        if not banco:
            raise ValidationError("campo obrigatório 'banco' vazio")
        if not periodo:
            raise ValidationError("campo obrigatório 'periodo_referencia' vazio")
        parse_period(periodo)
        if not descricao:
            raise ValidationError("campo obrigatório 'descricao' vazio")
        if len(descricao) > 200:
            raise ValidationError("'descricao' excede 200 caracteres")

        amount = parse_money(row.get("valor"))
        tipo = str(row.get("tipo") or "").strip() or classify_transaction(descricao, amount)
        return cls(
            banco=banco,
            periodo_referencia=periodo,
            data_transacao=normalize_date(row.get("data_transacao")),
            cartao=str(row.get("cartao") or "").strip(),
            descricao=descricao,
            parcela=normalized_installment(row.get("parcela")),
            valor=amount,
            tipo=tipo,
            categoria=str(row.get("categoria") or "").strip(),
            categoria_nativa=str(row.get("categoria_nativa") or "").strip(),
            origem=source,
            merchant_nome_amigavel=str(row.get("merchant_nome_amigavel") or "").strip(),
            merchant_confidence=_parse_percent(row.get("merchant_confidence")),
            merchant_revisado=_parse_boolean(row.get("merchant_revisado")),
            merchant_origem=str(row.get("merchant_origem") or "").strip(),
        )

    @property
    def is_expense(self) -> bool:
        return self.valor > 0 and normalize_text(self.tipo) not in NON_EXPENSE_TYPES

    @property
    def deduplication_key(self) -> tuple[str, ...]:
        return (
            normalize_text(self.banco),
            self.periodo_referencia,
            self.data_transacao,
            normalize_text(self.descricao),
            format_money(self.valor),
            self.cartao,
            self.parcela,
        )

    def with_category(self, category: str) -> Transaction:
        return replace(self, categoria=category)

    def with_merchant(
        self,
        *,
        friendly_name: str,
        category: str,
        confidence_percent: int,
        reviewed: bool,
        source: str,
    ) -> Transaction:
        return replace(
            self,
            categoria=category,
            merchant_nome_amigavel=friendly_name,
            merchant_confidence=min(100, max(0, confidence_percent)),
            merchant_revisado=reviewed,
            merchant_origem=source,
        )

    @property
    def display_name(self) -> str:
        return self.merchant_nome_amigavel or self.descricao

    def to_csv_row(self) -> dict[str, str]:
        return {
            "banco": self.banco,
            "periodo_referencia": self.periodo_referencia,
            "data_transacao": self.data_transacao,
            "cartao": self.cartao,
            "descricao": self.descricao,
            "parcela": self.parcela,
            "valor": format_money(self.valor),
            "tipo": self.tipo,
            "categoria": self.categoria,
            "categoria_nativa": self.categoria_nativa,
        }

    def to_analysis_csv_row(self) -> dict[str, str]:
        row = self.to_csv_row()
        row.update(
            {
                "merchant_nome_amigavel": self.merchant_nome_amigavel,
                "merchant_confidence": str(self.merchant_confidence),
                "merchant_revisado": "sim" if self.merchant_revisado else "nao",
                "merchant_origem": self.merchant_origem,
            }
        )
        return row


def _parse_percent(value: object) -> int:
    try:
        return min(100, max(0, int(float(str(value or 0)))))
    except (TypeError, ValueError):
        return 0


def _parse_boolean(value: object) -> bool:
    return normalize_text(value) in {"1", "sim", "s", "true", "yes", "x", "aprovado"}
