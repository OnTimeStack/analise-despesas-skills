"""Human-reviewed merchant enrichment and portable knowledge-base persistence."""

from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .categorization import Categorizer
from .models import Transaction
from .parsing import normalize_text

UNKNOWN_MERCHANT = "Desconhecido"
UNKNOWN_CATEGORY = "Desconhecida"

KNOWLEDGE_FIELDS = (
    "merchant_key",
    "nome_original",
    "nome_amigavel",
    "categoria",
    "confidence_percent",
    "aprovado_em",
)
REVIEW_FIELDS = (
    "merchant_key",
    "nome_original",
    "variantes_originais",
    "nome_amigavel",
    "confidence_percent",
    "categoria",
    "origem_classificacao",
    "contexto_classificacao",
    "ocorrencias",
    "aprovado",
)
REQUIRED_REVIEW_FIELDS = tuple(
    field for field in REVIEW_FIELDS if field != "contexto_classificacao"
)

LEGACY_UNKNOWN_CATEGORIES = {"", "Desconhecida", "Despesas Diversas"}
LEGACY_NON_MERCHANT_CATEGORIES = {"Pagamentos e Créditos", "Tributos e Encargos"}

FRIENDLY_ALIASES = {
    "amazon prime": "Amazon Prime",
    "amazonprimebr": "Amazon Prime",
    "amazon marketplace": "Amazon Marketplace",
    "amazonmktplc": "Amazon Marketplace",
    "ebn*adobe": "Adobe",
    "adobe": "Adobe",
    "claude.ai": "Claude",
    "openai": "OpenAI",
    "manus ai": "Manus AI",
    "uber *one": "Uber One",
    "uber eats": "Uber Eats",
    "uber *eats": "Uber Eats",
    "ifd*47.903": "iFood",
    "ifood": "iFood",
    "dl *google youtubeprem": "YouTube Premium",
    "google youtubepremium": "YouTube Premium",
    "mercadolivre": "Mercado Livre",
    "linkedin": "LinkedIn",
    "netflix": "Netflix",
    "spotify": "Spotify",
    "figma": "Figma",
    "openrouter": "OpenRouter",
    "cloudflare": "Cloudflare",
    "shopify": "Shopify",
}

GENERIC_KEYWORDS = {
    "academia",
    "aplicacao",
    "aporte",
    "assinatura",
    "atacadao",
    "barbearia",
    "beleza",
    "celular",
    "cinema",
    "clinica",
    "combustivel",
    "consulta",
    "curso",
    "delivery",
    "dizimo",
    "doacao",
    "drogaria",
    "escola",
    "estacionamento",
    "exame",
    "farmacia",
    "feira",
    "gasolina",
    "hospital",
    "hotel",
    "internet",
    "investimento",
    "juros",
    "laboratorio",
    "lanchonete",
    "lavanderia",
    "livraria",
    "livro",
    "medico",
    "mercado",
    "multa",
    "pagamento",
    "padaria",
    "parque",
    "parking",
    "passagem",
    "pet shop",
    "petshop",
    "pizzaria",
    "presente",
    "restaurante",
    "roupa",
    "salao",
    "seguro",
    "seguradora",
    "supermercado",
    "tarifa",
    "taxa",
    "taxi",
    "telefone",
    "universidade",
    "veterinario",
    "viagem",
}


@dataclass(frozen=True, slots=True)
class MerchantKnowledge:
    merchant_key: str
    original_name: str
    friendly_name: str
    category: str
    confidence_percent: int
    approved_at: str


@dataclass(frozen=True, slots=True)
class MerchantDecision:
    merchant_key: str
    original_name: str
    original_variants: tuple[str, ...]
    friendly_name: str
    confidence_percent: int
    category: str
    source: str
    occurrences: int
    approved: bool
    classification_context: str = ""

    def to_review_row(self) -> dict[str, str]:
        return {
            "merchant_key": self.merchant_key,
            "nome_original": self.original_name,
            "variantes_originais": " | ".join(self.original_variants),
            "nome_amigavel": self.friendly_name,
            "confidence_percent": str(self.confidence_percent),
            "categoria": self.category,
            "origem_classificacao": self.source,
            "contexto_classificacao": self.classification_context,
            "ocorrencias": str(self.occurrences),
            "aprovado": "sim" if self.approved else "nao",
        }


class MerchantKnowledgeBase:
    def __init__(self, path: Path, entries: dict[str, MerchantKnowledge] | None = None):
        self.path = Path(path)
        self.entries = entries or {}

    @classmethod
    def load(cls, path: Path) -> MerchantKnowledgeBase:
        path = Path(path)
        if not path.exists():
            return cls(path)
        entries: dict[str, MerchantKnowledge] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(KNOWLEDGE_FIELDS) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"base de merchants inválida; colunas ausentes: {', '.join(sorted(missing))}"
                )
            for line_number, row in enumerate(reader, start=2):
                key = str(row.get("merchant_key") or "").strip()
                original = str(row.get("nome_original") or "").strip()
                friendly = str(row.get("nome_amigavel") or "").strip()
                category = str(row.get("categoria") or "").strip()
                if not key or not original or not friendly or not category:
                    raise ValueError(f"base de merchants inválida na linha {line_number}")
                if key != merchant_key(original):
                    raise ValueError(
                        f"base de merchants inválida na linha {line_number}: "
                        "merchant_key não corresponde ao nome original"
                    )
                entries[key] = MerchantKnowledge(
                    merchant_key=key,
                    original_name=original,
                    friendly_name=friendly,
                    category=category,
                    confidence_percent=_bounded_percent(row.get("confidence_percent"), default=100),
                    approved_at=str(row.get("aprovado_em") or "").strip(),
                )
        return cls(path, entries)

    def get(self, original_name: str) -> MerchantKnowledge | None:
        return self.entries.get(merchant_key(original_name))

    def merge_review(self, review_path: Path) -> tuple[int, int]:
        approved_count = 0
        pending_count = 0
        with Path(review_path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(REQUIRED_REVIEW_FIELDS) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"revisão inválida; colunas ausentes: {', '.join(sorted(missing))}"
                )
            for line_number, row in enumerate(reader, start=2):
                if not _is_approved(row.get("aprovado")):
                    pending_count += 1
                    continue
                key = str(row.get("merchant_key") or "").strip()
                original = str(row.get("nome_original") or "").strip()
                friendly = str(row.get("nome_amigavel") or "").strip()
                category = str(row.get("categoria") or "").strip()
                if not key or not original or not friendly or not category:
                    raise ValueError(f"revisão aprovada incompleta na linha {line_number}")
                if key != merchant_key(original):
                    raise ValueError(
                        f"revisão inválida na linha {line_number}: "
                        "merchant_key não corresponde ao nome original"
                    )
                self.entries[key] = MerchantKnowledge(
                    merchant_key=key,
                    original_name=original,
                    friendly_name=friendly,
                    category=category,
                    confidence_percent=100,
                    approved_at=datetime.now(UTC).isoformat(timespec="seconds"),
                )
                approved_count += 1
        self.save()
        return approved_count, pending_count

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=KNOWLEDGE_FIELDS, lineterminator="\n")
            writer.writeheader()
            for entry in sorted(
                self.entries.values(), key=lambda item: normalize_text(item.original_name)
            ):
                writer.writerow(
                    {
                        "merchant_key": entry.merchant_key,
                        "nome_original": entry.original_name,
                        "nome_amigavel": entry.friendly_name,
                        "categoria": entry.category,
                        "confidence_percent": entry.confidence_percent,
                        "aprovado_em": entry.approved_at,
                    }
                )
        temporary.replace(self.path)


class MerchantEnricher:
    def __init__(
        self,
        categorizer: Categorizer | None = None,
        knowledge_base: MerchantKnowledgeBase | None = None,
    ):
        self.categorizer = categorizer or Categorizer()
        self.knowledge_base = knowledge_base

    def build_decisions(self, transactions: list[Transaction]) -> list[MerchantDecision]:
        grouped: dict[str, list[Transaction]] = defaultdict(list)
        variants: dict[str, set[str]] = defaultdict(set)
        for transaction in transactions:
            if not transaction.is_expense:
                continue
            key = merchant_key(transaction.descricao)
            grouped[key].append(transaction)
            variants[key].add(transaction.descricao.strip())

        decisions = [
            self._decide(
                key,
                items,
                tuple(sorted(variants[key], key=lambda value: (normalize_text(value), value))),
            )
            for key, items in grouped.items()
        ]
        return sorted(decisions, key=lambda item: normalize_text(item.original_name))

    def _decide(
        self,
        key: str,
        transactions: list[Transaction],
        variants: tuple[str, ...],
    ) -> MerchantDecision:
        original = variants[0]
        known = self.knowledge_base.entries.get(key) if self.knowledge_base else None
        if known:
            return MerchantDecision(
                merchant_key=key,
                original_name=original,
                original_variants=variants,
                friendly_name=known.friendly_name,
                confidence_percent=100,
                category=known.category,
                source="base_conhecimento",
                occurrences=len(transactions),
                approved=True,
            )

        match = self.categorizer.categorize(transactions[0])
        friendly = _friendly_name(match.matched_keyword)
        if friendly == UNKNOWN_MERCHANT:
            category = UNKNOWN_CATEGORY
            confidence = 0
        else:
            category = match.category
            confidence = round(match.confidence * 100)
        return MerchantDecision(
            merchant_key=key,
            original_name=original,
            original_variants=variants,
            friendly_name=friendly,
            confidence_percent=confidence,
            category=category,
            source="regras_deterministicas" if confidence else "sem_evidencia_suficiente",
            occurrences=len(transactions),
            approved=False,
        )


def prepare_merchant_review(
    transactions: list[Transaction],
    output_dir: Path,
    *,
    categorizer: Categorizer | None = None,
    knowledge_base: MerchantKnowledgeBase | None = None,
) -> list[MerchantDecision]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions = MerchantEnricher(categorizer, knowledge_base).build_decisions(transactions)
    _write_review_csv(output_dir / "merchant_review.csv", decisions)
    (output_dir / "merchant_review.html").write_text(
        render_review_html(decisions), encoding="utf-8"
    )
    return decisions


def prepare_legacy_merchant_review(
    source_path: Path,
    output_dir: Path,
    *,
    knowledge_base: MerchantKnowledgeBase | None = None,
) -> tuple[list[MerchantDecision], dict[str, int]]:
    """Adapt prior user classifications into the current human-review workflow."""
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"descricao", "categoria"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"classificação legada inválida; colunas ausentes: {', '.join(sorted(missing))}"
            )
        for line_number, row in enumerate(reader, start=2):
            description = str(row.get("descricao") or "").strip()
            if not description:
                raise ValueError(f"classificação legada sem descrição na linha {line_number}")
            grouped[merchant_key(description)].append(
                {
                    "descricao": description,
                    "categoria": str(row.get("categoria") or "").strip(),
                    "categoria_nativa": str(row.get("categoria_nativa") or "").strip(),
                }
            )

    decisions: list[MerchantDecision] = []
    excluded_non_merchants = 0
    divergent_categories = 0
    unresolved_conflicts = 0
    for key, rows in grouped.items():
        variants = tuple(
            sorted(
                {row["descricao"] for row in rows},
                key=lambda value: (normalize_text(value), value),
            )
        )
        original = variants[0]
        previous_categories = {row["categoria"] for row in rows}
        if previous_categories and previous_categories <= LEGACY_NON_MERCHANT_CATEGORIES:
            excluded_non_merchants += 1
            continue

        known = knowledge_base.entries.get(key) if knowledge_base else None
        if known:
            decisions.append(
                MerchantDecision(
                    merchant_key=key,
                    original_name=original,
                    original_variants=variants,
                    friendly_name=known.friendly_name,
                    confidence_percent=100,
                    category=known.category,
                    source="base_conhecimento",
                    occurrences=len(rows),
                    approved=True,
                    classification_context=_legacy_context(rows),
                )
            )
            continue

        relevant_categories = previous_categories - LEGACY_UNKNOWN_CATEGORIES
        relevant_categories -= LEGACY_NON_MERCHANT_CATEGORIES
        is_divergent = len(previous_categories) > 1
        if is_divergent:
            divergent_categories += 1
        if len(relevant_categories) == 1:
            category = next(iter(relevant_categories))
        else:
            category = UNKNOWN_CATEGORY
            if len(relevant_categories) > 1:
                unresolved_conflicts += 1
        friendly, friendly_confidence, friendly_source = _legacy_friendly_name(original)
        if friendly == UNKNOWN_MERCHANT:
            category = UNKNOWN_CATEGORY
            confidence = 0
            source = "classificacao_legada_sem_nome_confiavel"
        elif category == UNKNOWN_CATEGORY:
            confidence = 0
            source = "classificacao_legada_inconclusiva"
        else:
            confidence = min(friendly_confidence, 50 if is_divergent else 85)
            source = f"classificacao_legada+{friendly_source}"

        decisions.append(
            MerchantDecision(
                merchant_key=key,
                original_name=original,
                original_variants=variants,
                friendly_name=friendly,
                confidence_percent=confidence,
                category=category,
                source=source,
                occurrences=len(rows),
                approved=False,
                classification_context=_legacy_context(rows),
            )
        )

    decisions.sort(key=lambda item: normalize_text(item.original_name))
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_review_csv(output_dir / "merchant_review.csv", decisions)
    (output_dir / "merchant_review.html").write_text(
        render_review_html(decisions), encoding="utf-8"
    )
    summary = {
        "source_rows": sum(len(rows) for rows in grouped.values()),
        "unique_source_merchants": len(grouped),
        "review_rows": len(decisions),
        "duplicates_collapsed": sum(len(rows) - 1 for rows in grouped.values()),
        "excluded_non_merchants": excluded_non_merchants,
        "divergent_category_merchants": divergent_categories,
        "unresolved_category_conflicts": unresolved_conflicts,
        "unknown_category_merchants": sum(
            1 for item in decisions if item.category == UNKNOWN_CATEGORY
        ),
        "knowledge_base_hits": sum(1 for item in decisions if item.approved),
    }
    (output_dir / "legacy_import_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return decisions, summary


def render_review_html(
    decisions: list[MerchantDecision],
    *,
    app_mode: bool = False,
    review_token: str = "",
) -> str:
    payload = json.dumps(
        [decision.to_review_row() for decision in decisions], ensure_ascii=False
    ).replace("<", "\\u003c")
    categories = sorted(
        {decision.category for decision in decisions} | {UNKNOWN_CATEGORY}, key=normalize_text
    )
    category_options = "".join(
        f'<option value="{html.escape(category, quote=True)}"></option>' for category in categories
    )
    navigation = (
        '<nav class="topnav"><a href="/insights">Insights</a>'
        '<a class="active" href="/classification">Classificação</a></nav>'
        if app_mode
        else '<nav class="topnav"><span class="active">Classificação</span></nav>'
    )
    save_button = (
        '<button id="save-draft">Salvar rascunho</button>'
        '<button id="approve-review" class="primary">Aprovar selecionados e atualizar insights</button>'
        if app_mode
        else ""
    )
    return (
        REVIEW_HTML.replace("__MERCHANT_DATA__", payload)
        .replace("__CATEGORY_OPTIONS__", category_options)
        .replace("__NAVIGATION__", navigation)
        .replace("__SAVE_BUTTON__", save_button)
        .replace("__SAVE_ENDPOINT__", json.dumps("/api/review" if app_mode else None))
        .replace("__REVIEW_TOKEN__", json.dumps(review_token))
    )


def merchant_key(original_name: str) -> str:
    return normalize_text(original_name)


def _legacy_context(rows: list[dict[str, str]]) -> str:
    categories = sorted({row["categoria"] for row in rows if row["categoria"]}, key=normalize_text)
    native = sorted(
        {
            row["categoria_nativa"]
            for row in rows
            if row["categoria_nativa"] and row["categoria_nativa"] != "-"
        },
        key=normalize_text,
    )
    parts = []
    if categories:
        parts.append(f"Categorias anteriores: {' | '.join(categories)}")
    if native:
        parts.append(f"Categorias nativas: {' | '.join(native)}")
    return "; ".join(parts)


def _legacy_friendly_name(original_name: str) -> tuple[str, int, str]:
    normalized = normalize_text(original_name)
    for alias, friendly in sorted(
        FRIENDLY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if alias in normalized:
            return friendly, 95, "alias_deterministico"

    cleaned = re.sub(r"^\d{3,}\s*", "", original_name.strip())
    cleaned = re.sub(
        r"^(?:MP|PG|EBN|DL|EC|IFD|PAYU|MERCADOPAGO)(?:\s*\*\s*|\s+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b\d{4,}\b", "", cleaned)
    cleaned = re.sub(r"[*_/]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    normalized_cleaned = normalize_text(cleaned)
    if (
        not cleaned
        or normalized_cleaned in GENERIC_KEYWORDS
        or len(normalized_cleaned) < 3
        or not any(character.isalpha() for character in cleaned)
    ):
        return UNKNOWN_MERCHANT, 0, "sem_nome_confiavel"

    particles = {"a", "da", "das", "de", "do", "dos", "e"}
    acronyms = {
        "AC",
        "AI",
        "BR",
        "BRA",
        "EPP",
        "GBR",
        "IRL",
        "LTD",
        "LTDA",
        "ME",
        "PR",
        "RJ",
        "RS",
        "SA",
        "SC",
        "SP",
        "UK",
        "US",
        "USA",
    }
    words = []
    for index, word in enumerate(cleaned.split()):
        lowered = word.casefold()
        if index and lowered in particles:
            words.append(lowered)
        elif word.upper() in acronyms or (
            word.isupper()
            and len(word) <= 4
            and not any(vowel in normalize_text(word) for vowel in "aeiou")
        ):
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words), 70, "nome_derivado_da_descricao"


def _friendly_name(matched_keyword: str) -> str:
    normalized = normalize_text(matched_keyword)
    if not normalized or normalized in GENERIC_KEYWORDS:
        return UNKNOWN_MERCHANT
    if normalized in FRIENDLY_ALIASES:
        return FRIENDLY_ALIASES[normalized]
    if len(normalized) < 3 or normalized.isdigit():
        return UNKNOWN_MERCHANT
    cleaned = re.sub(r"^[a-z]{2,4}\s*\*\s*", "", normalized).strip()
    if not cleaned or cleaned in GENERIC_KEYWORDS or re.search(r"\d{3,}", cleaned):
        return UNKNOWN_MERCHANT
    return " ".join(
        part.upper() if len(part) <= 2 else part.capitalize() for part in cleaned.split()
    )


def _write_review_csv(path: Path, decisions: list[MerchantDecision]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(decision.to_review_row() for decision in decisions)


def _bounded_percent(value: object, *, default: int) -> int:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return default
    return min(100, max(0, parsed))


def _is_approved(value: object) -> bool:
    return normalize_text(value) in {"1", "sim", "s", "true", "yes", "x", "aprovado"}


REVIEW_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Revisão de merchants</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; padding: 1.25rem; background: #0f172a; color: #e2e8f0; }
    h1 { margin: 0 0 .35rem; }
    p { color: #cbd5e1; max-width: 78rem; }
    .topnav { display: flex; gap: .35rem; margin-bottom: 1.25rem; border-bottom: 1px solid #334155; }
    .topnav a, .topnav span { color: #cbd5e1; padding: .7rem .9rem; text-decoration: none; border-bottom: 3px solid transparent; }
    .topnav .active { color: #fff; border-color: #22c55e; font-weight: 700; }
    .toolbar { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0; }
    button { border: 1px solid #475569; border-radius: .45rem; padding: .55rem .75rem; cursor: pointer; }
    .primary { background: #22c55e; color: #052e16; font-weight: 700; }
    .table-wrap { overflow: auto; max-height: 72vh; border: 1px solid #334155; border-radius: .5rem; }
    table { border-collapse: collapse; width: 100%; min-width: 1800px; background: #111827; }
    th, td { border-bottom: 1px solid #334155; padding: .5rem; text-align: left; vertical-align: top; }
    thead { position: sticky; top: 0; z-index: 2; background: #1e293b; }
    th button { width: 100%; background: transparent; color: inherit; border: 0; text-align: left; }
    .filters input { width: 95%; box-sizing: border-box; }
    td input[type="text"] { width: 100%; min-width: 9rem; box-sizing: border-box; }
    input { padding: .4rem; border: 1px solid #475569; border-radius: .3rem; background: #0f172a; color: inherit; }
    tr.unknown { background: #3f1d1d; }
    .confidence { font-variant-numeric: tabular-nums; text-align: right; }
    th:nth-child(1), td:nth-child(1) { min-width: 240px; }
    th:nth-child(2), td:nth-child(2) { min-width: 210px; }
    th:nth-child(3), td:nth-child(3) { min-width: 115px; }
    th:nth-child(4), td:nth-child(4) { min-width: 230px; }
    th:nth-child(5), td:nth-child(5) { min-width: 245px; overflow-wrap: anywhere; }
    th:nth-child(6), td:nth-child(6) { min-width: 420px; }
    th:nth-child(7), td:nth-child(7), th:nth-child(8), td:nth-child(8) { min-width: 105px; }
    .summary { font-weight: 600; }
    @media (prefers-color-scheme: light) {
      body { background: #f8fafc; color: #0f172a; }
      p { color: #334155; } table { background: white; } thead { background: #e2e8f0; }
      input { background: white; } tr.unknown { background: #fee2e2; }
    }
  </style>
</head>
<body>
  __NAVIGATION__
  <h1>Revisão humana de merchants</h1>
  <p>Revise somente os nomes únicos. As edições são rascunhos até você marcar os itens conferidos como aprovados. Salvar rascunho não altera os insights; aprovar os selecionados incorpora essas linhas à base e recalcula o plano. Itens desconhecidos podem ser aprovados explicitamente como desconhecidos.</p>
  <div class="toolbar">
    <button id="approve-visible">Aprovar visíveis</button>
    <button id="clear-visible">Desmarcar visíveis</button>
    <button id="download" class="primary">Baixar revisão CSV</button>
    __SAVE_BUTTON__
    <span id="summary" class="summary"></span>
    <span id="save-status" role="status"></span>
  </div>
  <datalist id="categories">__CATEGORY_OPTIONS__</datalist>
  <div class="table-wrap">
    <table id="merchant-table">
      <thead>
        <tr>
          <th><button data-sort="variantes_originais">Nomes originais ↕</button></th>
          <th><button data-sort="nome_amigavel">Nome amigável ↕</button></th>
          <th><button data-sort="confidence_percent">Confiança (%) ↕</button></th>
          <th><button data-sort="categoria">Categoria ↕</button></th>
          <th><button data-sort="origem_classificacao">Origem ↕</button></th>
          <th><button data-sort="contexto_classificacao">Contexto anterior ↕</button></th>
          <th><button data-sort="ocorrencias">Ocorrências ↕</button></th>
          <th><button data-sort="aprovado">Aprovado ↕</button></th>
        </tr>
        <tr class="filters">
          <th><input data-filter="variantes_originais" placeholder="Filtrar originais"></th>
          <th><input data-filter="nome_amigavel" placeholder="Filtrar amigável"></th>
          <th><input data-filter="confidence_percent" placeholder="Filtrar confiança"></th>
          <th><input data-filter="categoria" placeholder="Filtrar categoria"></th>
          <th><input data-filter="origem_classificacao" placeholder="Filtrar origem"></th>
          <th><input data-filter="contexto_classificacao" placeholder="Filtrar contexto"></th>
          <th><input data-filter="ocorrencias" placeholder="Filtrar ocorrências"></th>
          <th><input data-filter="aprovado" placeholder="sim/não"></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>
  <script>
    const rows = __MERCHANT_DATA__;
    const saveEndpoint = __SAVE_ENDPOINT__;
    const reviewToken = __REVIEW_TOKEN__;
    const filters = {};
    const sourceLabels = {
      "base_conhecimento": "Base aprovada",
      "regras_deterministicas": "Regras determinísticas",
      "sem_evidencia_suficiente": "Sem evidência suficiente",
      "classificacao_legada+alias_deterministico": "Legado + alias determinístico",
      "classificacao_legada+nome_derivado_da_descricao": "Legado + nome derivado",
      "classificacao_legada_inconclusiva": "Legado inconclusivo",
      "classificacao_legada_sem_nome_confiavel": "Legado sem nome confiável"
    };
    let sortKey = "variantes_originais", sortDirection = 1;
    const storageKey = "merchant-review:" + rows.map(r => r.merchant_key).join("|");
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (Array.isArray(saved)) saved.forEach(item => {
        const target = rows.find(row => row.merchant_key === item.merchant_key);
        if (target) Object.assign(target, item);
      });
    } catch (_) {}

    const value = (row, key) => String(row[key] ?? "");
    const visibleRows = () => rows.filter(row => Object.entries(filters).every(([key, query]) => value(row, key).toLocaleLowerCase("pt-BR").includes(query)));
    const persist = () => localStorage.setItem(storageKey, JSON.stringify(rows));
    function render() {
      const body = document.querySelector("tbody");
      body.textContent = "";
      const current = visibleRows().sort((a, b) => value(a, sortKey).localeCompare(value(b, sortKey), "pt-BR", {numeric: true}) * sortDirection);
      current.forEach(row => {
        const tr = document.createElement("tr");
        if (row.nome_amigavel === "Desconhecido" || row.categoria === "Desconhecida") tr.className = "unknown";
        const original = document.createElement("td"); original.textContent = row.variantes_originais;
        const friendlyCell = document.createElement("td");
        const friendly = document.createElement("input"); friendly.type = "text"; friendly.value = row.nome_amigavel;
        friendly.addEventListener("input", () => { row.nome_amigavel = friendly.value; persist(); updateSummary(); }); friendlyCell.appendChild(friendly);
        const confidence = document.createElement("td"); confidence.className = "confidence"; confidence.textContent = row.confidence_percent + "%";
        const categoryCell = document.createElement("td");
        const category = document.createElement("input"); category.type = "text"; category.value = row.categoria; category.setAttribute("list", "categories");
        category.addEventListener("input", () => { row.categoria = category.value; persist(); updateSummary(); }); categoryCell.appendChild(category);
        const source = document.createElement("td"); source.textContent = sourceLabels[row.origem_classificacao] || row.origem_classificacao;
        const context = document.createElement("td"); context.textContent = row.contexto_classificacao;
        const occurrences = document.createElement("td"); occurrences.textContent = row.ocorrencias;
        const approvedCell = document.createElement("td"); const approved = document.createElement("input"); approved.type = "checkbox"; approved.checked = row.aprovado === "sim";
        approved.addEventListener("change", () => { row.aprovado = approved.checked ? "sim" : "nao"; persist(); updateSummary(); }); approvedCell.appendChild(approved);
        tr.append(original, friendlyCell, confidence, categoryCell, source, context, occurrences, approvedCell); body.appendChild(tr);
      });
      updateSummary();
    }
    function updateSummary() {
      const approved = rows.filter(row => row.aprovado === "sim").length;
      const unknown = rows.filter(row => row.nome_amigavel === "Desconhecido" || row.categoria === "Desconhecida").length;
      document.querySelector("#summary").textContent = `${rows.length} únicos · ${approved} aprovados · ${unknown} desconhecidos · ${visibleRows().length} visíveis`;
    }
    document.querySelectorAll("[data-filter]").forEach(input => input.addEventListener("input", () => { filters[input.dataset.filter] = input.value.toLocaleLowerCase("pt-BR"); render(); }));
    document.querySelectorAll("[data-sort]").forEach(button => button.addEventListener("click", () => { const key = button.dataset.sort; sortDirection = sortKey === key ? -sortDirection : 1; sortKey = key; render(); }));
    document.querySelector("#approve-visible").addEventListener("click", () => { visibleRows().forEach(row => row.aprovado = "sim"); persist(); render(); });
    document.querySelector("#clear-visible").addEventListener("click", () => { visibleRows().forEach(row => row.aprovado = "nao"); persist(); render(); });
    const csvEscape = value => `"${String(value ?? "").replaceAll('"', '""')}"`;
    document.querySelector("#download").addEventListener("click", () => {
      const fields = ["merchant_key", "nome_original", "variantes_originais", "nome_amigavel", "confidence_percent", "categoria", "origem_classificacao", "contexto_classificacao", "ocorrencias", "aprovado"];
      const csv = [fields.join(","), ...rows.sort((a,b) => a.nome_original.localeCompare(b.nome_original, "pt-BR")).map(row => fields.map(field => csvEscape(row[field])).join(","))].join("\n");
      const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], {type: "text/csv;charset=utf-8"})); link.download = "merchant_review_approved.csv"; link.click(); URL.revokeObjectURL(link.href);
    });
    async function submitReview(mode) {
      const saveButton = mode === "approve" ? document.querySelector("#approve-review") : document.querySelector("#save-draft");
      const status = document.querySelector("#save-status");
      const approvedCount = rows.filter(row => row.aprovado === "sim").length;
      if (mode === "approve" && approvedCount === 0) {
        status.textContent = "Marque ao menos um merchant conferido antes de atualizar os insights.";
        return;
      }
      saveButton.disabled = true;
      status.textContent = mode === "approve"
        ? "Aprovando e recalculando insights…"
        : "Salvando rascunho…";
      try {
        const response = await fetch(saveEndpoint, {
          method: "POST",
          headers: {"Content-Type": "application/json", "X-Review-Token": reviewToken},
          body: JSON.stringify({rows, mode})
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Não foi possível salvar a revisão");
        status.textContent = result.message || "Revisão salva.";
        if (mode === "approve") {
          localStorage.removeItem(storageKey);
          window.location.assign(result.next_url || "/insights");
        } else {
          saveButton.disabled = false;
        }
      } catch (error) {
        status.textContent = error.message; saveButton.disabled = false;
      }
    }
    const draftButton = document.querySelector("#save-draft");
    const approveButton = document.querySelector("#approve-review");
    if (draftButton) draftButton.addEventListener("click", () => submitReview("draft"));
    if (approveButton) approveButton.addEventListener("click", () => submitReview("approve"));
    render();
  </script>
</body>
</html>
"""
