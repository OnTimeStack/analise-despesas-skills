"""Local two-page application for merchant review and refreshed insights."""

from __future__ import annotations

import csv
import html
import json
import secrets
import webbrowser
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .analysis import ExpenseAnalyzer, load_transactions_csv
from .categorization import Categorizer
from .merchants import (
    REQUIRED_REVIEW_FIELDS,
    REVIEW_FIELDS,
    MerchantDecision,
    MerchantEnricher,
    MerchantKnowledgeBase,
    render_review_html,
)
from .parsing import normalize_text

MAX_REQUEST_BYTES = 5 * 1024 * 1024


class ExpenseReviewApplication:
    """Owns local review state and deterministic insight regeneration."""

    def __init__(
        self,
        input_path: Path,
        output_dir: Path,
        knowledge_base_path: Path,
        *,
        categories_path: Path | None = None,
    ):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.knowledge_base_path = Path(knowledge_base_path)
        self.categories_path = Path(categories_path) if categories_path else None
        self.review_token = secrets.token_urlsafe(32)
        self.draft_path = self.output_dir / "merchant_review_draft.csv"
        self.decisions: list[MerchantDecision] = []
        self.results: dict[str, object] = {}
        self.review_html = ""
        self.insights_html = ""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.refresh()

    def refresh(self) -> None:
        knowledge_base = MerchantKnowledgeBase.load(self.knowledge_base_path)
        categorizer = (
            Categorizer.from_csv(self.categories_path) if self.categories_path else Categorizer()
        )
        transactions, _ = load_transactions_csv(self.input_path)
        decisions = MerchantEnricher(categorizer, knowledge_base).build_decisions(transactions)
        self.decisions = self._apply_draft(decisions)
        self.results = ExpenseAnalyzer(
            self.input_path,
            categories_path=self.categories_path,
            output_dir=self.output_dir,
            merchant_kb_path=self.knowledge_base_path,
            require_reviewed=False,
        ).run()
        self.review_html = render_review_html(
            self.decisions,
            app_mode=True,
            review_token=self.review_token,
        )
        self.insights_html = render_insights_html(self.results)

    def save_review(self, submitted_rows: object) -> dict[str, object]:
        if not isinstance(submitted_rows, list):
            raise ValueError("payload de revisão inválido")
        submitted: dict[str, dict[str, object]] = {}
        for row in submitted_rows:
            if not isinstance(row, dict):
                raise ValueError("linha de revisão inválida")
            key = str(row.get("merchant_key") or "").strip()
            if not key or key in submitted:
                raise ValueError("merchant_key ausente ou duplicado")
            submitted[key] = row

        expected_keys = {decision.merchant_key for decision in self.decisions}
        if set(submitted) != expected_keys:
            raise ValueError("a revisão não corresponde ao conjunto atual de merchants")

        safe_rows: list[dict[str, str]] = []
        for decision in self.decisions:
            incoming = submitted[decision.merchant_key]
            friendly = str(incoming.get("nome_amigavel") or "").strip()
            category = str(incoming.get("categoria") or "").strip()
            approved = _approved(incoming.get("aprovado"))
            if len(friendly) > 160 or len(category) > 120:
                raise ValueError("nome amigável ou categoria excede o limite permitido")
            if approved and (not friendly or not category):
                raise ValueError("linhas aprovadas exigem nome amigável e categoria")
            row = decision.to_review_row()
            row.update(
                {
                    "nome_amigavel": friendly,
                    "categoria": category,
                    "aprovado": "sim" if approved else "nao",
                }
            )
            safe_rows.append(row)

        _write_rows_atomic(self.draft_path, safe_rows)
        knowledge_base = MerchantKnowledgeBase.load(self.knowledge_base_path)
        approved_count, pending_count = knowledge_base.merge_review(self.draft_path)
        self.refresh()
        enrichment = _mapping(self.results.get("merchant_enrichment"))
        return {
            "approved_imported": approved_count,
            "pending_review": enrichment.get("pending_review", pending_count),
            "insights_updated_locally": True,
            "ai_reprocessing_required": False,
            "insights_url": "/insights",
        }

    def _apply_draft(self, decisions: list[MerchantDecision]) -> list[MerchantDecision]:
        if not self.draft_path.is_file():
            return decisions
        with self.draft_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if set(REQUIRED_REVIEW_FIELDS) - set(reader.fieldnames or []):
                return decisions
            draft = {str(row.get("merchant_key") or ""): row for row in reader}
        enriched: list[MerchantDecision] = []
        for decision in decisions:
            row = draft.get(decision.merchant_key)
            if decision.approved or not row:
                enriched.append(decision)
                continue
            friendly = str(row.get("nome_amigavel") or "").strip()
            category = str(row.get("categoria") or "").strip()
            enriched.append(
                replace(
                    decision,
                    friendly_name=friendly or decision.friendly_name,
                    category=category or decision.category,
                )
            )
        return enriched


def serve_expense_review_app(
    input_path: Path,
    output_dir: Path,
    knowledge_base_path: Path,
    *,
    categories_path: Path | None = None,
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    application = ExpenseReviewApplication(
        input_path,
        output_dir,
        knowledge_base_path,
        categories_path=categories_path,
    )
    handler = _handler_for(application)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/insights"
    print(json.dumps({"url": url, "output_dir": str(output_dir)}, ensure_ascii=False))
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def render_insights_html(results: dict[str, object]) -> str:
    overview = _mapping(results.get("overview"))
    enrichment = _mapping(results.get("merchant_enrichment"))
    installments = _mapping(results.get("installments"))
    categories = _list_of_mappings(results.get("categories"))
    insights = _list_of_mappings(results.get("insights"))
    top_expenses = _list_of_mappings(results.get("top_expenses"))[:15]
    recurring = _mapping(results.get("recurring_services"))
    recurring_items = _list_of_mappings(recurring.get("items"))[:15]
    pending = int(enrichment.get("pending_review") or 0)
    classification_url = "/classification"
    banner = (
        f'<div class="warning">Há {pending} merchant(s) pendente(s). '
        f'<a href="{classification_url}">Revisar classificação</a></div>'
        if pending
        else '<div class="success">Todas as classificações estão aprovadas.</div>'
    )
    categories_rows = "".join(
        f"<tr><td>{_escape(row.get('categoria'))}</td>"
        f"<td>{_money(row.get('total'))}</td><td>{_escape(row.get('pct'))}%</td>"
        f"<td>{_escape(row.get('count'))}</td></tr>"
        for row in categories
    )
    insight_items = (
        "".join(
            f"<li><strong>{_escape(row.get('title'))}</strong>"
            f"<span>{_escape(row.get('priority'))} · {_escape(row.get('type'))}</span></li>"
            for row in insights
        )
        or "<li>Nenhum alerta determinístico para os dados atuais.</li>"
    )
    top_rows = "".join(
        f"<tr><td>{_escape(row.get('descricao'))}</td>"
        f"<td>{_escape(row.get('categoria'))}</td><td>{_money(row.get('valor'))}</td></tr>"
        for row in top_expenses
    )
    recurring_rows = (
        "".join(
            f"<tr><td>{_escape(row.get('descricao'))}</td>"
            f"<td>{_money(row.get('valor'))}</td>"
            f"<td>{_escape(row.get('meses_observados'))}</td></tr>"
            for row in recurring_items
        )
        or '<tr><td colspan="3">Nenhuma recorrência identificada.</td></tr>'
    )
    updated_at = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")
    return INSIGHTS_HTML.format(
        classification_url=html.escape(classification_url, quote=True),
        banner=banner,
        period=_escape(overview.get("latest_period")),
        total=_money(overview.get("total_latest")),
        transaction_count=_escape(overview.get("transaction_count_latest")),
        pending=_escape(pending),
        future_commitment=_money(installments.get("total_comprometido_futuro")),
        categories_rows=categories_rows,
        insight_items=insight_items,
        top_rows=top_rows,
        recurring_rows=recurring_rows,
        updated_at=updated_at,
    )


def _handler_for(application: ExpenseReviewApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self.send_response(303)
                self.send_header("Location", "/insights")
                self.end_headers()
            elif path == "/insights":
                self._send(200, application.insights_html, "text/html; charset=utf-8")
            elif path == "/classification":
                self._send(200, application.review_html, "text/html; charset=utf-8")
            elif path == "/api/state":
                enrichment = _mapping(application.results.get("merchant_enrichment"))
                self._send_json(200, enrichment)
            else:
                self._send_json(404, {"error": "página não encontrada"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/review":
                self._send_json(404, {"error": "endpoint não encontrado"})
                return
            supplied_token = self.headers.get("X-Review-Token", "")
            if not secrets.compare_digest(supplied_token, application.review_token):
                self._send_json(403, {"error": "token de revisão inválido"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("tamanho da revisão inválido")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("payload de revisão inválido")
                result = application.save_review(payload.get("rows"))
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)

        def _send_json(self, status: int, payload: object) -> None:
            self._send(
                status,
                json.dumps(payload, ensure_ascii=False),
                "application/json; charset=utf-8",
            )

        def _send(self, status: int, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
            )
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def _write_rows_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _approved(value: object) -> bool:
    return normalize_text(value) in {"1", "sim", "s", "true", "yes", "x", "aprovado"}


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _money(value: object) -> str:
    try:
        number = float(str(value or 0))
    except ValueError:
        number = 0.0
    formatted = f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


INSIGHTS_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Insights de despesas</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; padding: 1.25rem; background: #0f172a; color: #e2e8f0; }}
    .topnav {{ display: flex; gap: .35rem; margin-bottom: 1.25rem; border-bottom: 1px solid #334155; }}
    .topnav a {{ color: #cbd5e1; padding: .7rem .9rem; text-decoration: none; border-bottom: 3px solid transparent; }}
    .topnav .active {{ color: #fff; border-color: #22c55e; font-weight: 700; }}
    h1, h2 {{ margin-bottom: .45rem; }} .muted {{ color: #94a3b8; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(190px,1fr)); gap: .8rem; margin: 1rem 0; }}
    .card, section {{ background: #111827; border: 1px solid #334155; border-radius: .65rem; padding: 1rem; }}
    .card strong {{ display: block; font-size: 1.45rem; margin-top: .3rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(420px,1fr)); gap: 1rem; margin-top: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; }} th, td {{ padding: .55rem; border-bottom: 1px solid #334155; text-align: left; }}
    th {{ color: #cbd5e1; }} td:nth-child(n+2) {{ font-variant-numeric: tabular-nums; }}
    ul {{ padding-left: 1.2rem; }} li {{ margin: .7rem 0; }} li span {{ display: block; color: #94a3b8; font-size: .9rem; }}
    .warning, .success {{ padding: .8rem 1rem; border-radius: .5rem; margin: .8rem 0; }}
    .warning {{ background: #422006; color: #fde68a; }} .success {{ background: #052e16; color: #bbf7d0; }}
    .warning a {{ color: inherit; font-weight: 700; }}
    @media (prefers-color-scheme: light) {{ body {{ background:#f8fafc;color:#0f172a; }} .card,section {{ background:white; }} }}
  </style>
</head>
<body>
  <nav class="topnav"><a class="active" href="/insights">Insights</a><a href="{classification_url}">Classificação</a></nav>
  <h1>Insights de despesas</h1>
  <p class="muted">Período mais recente: {period}. Atualizado localmente em {updated_at}.</p>
  {banner}
  <div class="cards">
    <div class="card">Despesas do período<strong>{total}</strong></div>
    <div class="card">Transações<strong>{transaction_count}</strong></div>
    <div class="card">Classificações pendentes<strong>{pending}</strong></div>
    <div class="card">Compromisso futuro<strong>{future_commitment}</strong></div>
  </div>
  <div class="grid">
    <section><h2>Insights prioritários</h2><ul>{insight_items}</ul></section>
    <section><h2>Categorias</h2><table><thead><tr><th>Categoria</th><th>Total</th><th>%</th><th>Itens</th></tr></thead><tbody>{categories_rows}</tbody></table></section>
    <section><h2>Maiores despesas</h2><table><thead><tr><th>Merchant</th><th>Categoria</th><th>Valor</th></tr></thead><tbody>{top_rows}</tbody></table></section>
    <section><h2>Serviços recorrentes</h2><table><thead><tr><th>Merchant</th><th>Valor</th><th>Meses</th></tr></thead><tbody>{recurring_rows}</tbody></table></section>
  </div>
</body>
</html>"""
