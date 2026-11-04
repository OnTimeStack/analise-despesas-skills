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
        if not self.knowledge_base_path.exists():
            MerchantKnowledgeBase.load(self.knowledge_base_path).save()
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
        (self.output_dir / "merchant_review.html").write_text(self.review_html, encoding="utf-8")
        (self.output_dir / "analise_estrategica_despesas.html").write_text(
            render_insights_html(self.results, classification_url="merchant_review.html"),
            encoding="utf-8",
        )

    def save_review(self, submitted_rows: object, *, mode: str = "approve") -> dict[str, object]:
        if mode not in {"draft", "approve"}:
            raise ValueError("modo de salvamento inválido")
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
        selected_count = sum(1 for row in safe_rows if _approved(row.get("aprovado")))
        if mode == "approve" and selected_count == 0:
            raise ValueError(
                "nenhum merchant foi aprovado; marque os itens conferidos ou salve como rascunho"
            )
        if mode == "approve":
            approved_count, pending_count = knowledge_base.merge_review(self.draft_path)
        else:
            approved_count = 0
            pending_count = sum(1 for row in safe_rows if not _approved(row.get("aprovado")))
        self.refresh()
        enrichment = _mapping(self.results.get("merchant_enrichment"))
        return {
            "approved_imported": approved_count,
            "pending_review": enrichment.get("pending_review", pending_count),
            "draft_saved": True,
            "insights_updated_locally": mode == "approve",
            "ai_reprocessing_required": False,
            "next_url": "/insights" if mode == "approve" else "/classification",
            "message": (
                f"{approved_count} merchant(s) incorporado(s); insights recalculados."
                if mode == "approve"
                else "Rascunho salvo; nenhuma classificação foi incorporada aos insights."
            ),
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


def render_insights_html(
    results: dict[str, object], *, classification_url: str = "/classification"
) -> str:
    overview = _mapping(results.get("overview"))
    enrichment = _mapping(results.get("merchant_enrichment"))
    installments = _mapping(results.get("installments"))
    savings = _mapping(results.get("savings_potential"))
    quality = _mapping(results.get("data_quality"))
    recurring = _mapping(results.get("recurring_services"))
    categories = _list_of_mappings(results.get("categories"))
    insights = _list_of_mappings(results.get("insights"))
    action_plan = _list_of_mappings(results.get("action_plan"))
    recurring_items = _list_of_mappings(recurring.get("items"))[:10]
    installment_items = _list_of_mappings(installments.get("items"))[:10]
    pending = int(enrichment.get("pending_review") or 0)
    escaped_classification_url = html.escape(classification_url, quote=True)
    banner = (
        f'<div class="warning"><strong>Qualidade limitada:</strong> há {pending} merchant(s) '
        f'pendente(s). Rascunhos não alteram este plano. <a href="{escaped_classification_url}">'
        "Aprovar classificações conferidas</a></div>"
        if pending
        else '<div class="success">Todas as classificações estão aprovadas e o plano usa a base revisada.</div>'
    )

    maximum_category = max((_as_float(row.get("total")) for row in categories), default=0.0)
    categories_bars = "".join(
        '<div class="bar-row">'
        f'<div class="bar-label">{_escape(row.get("categoria"))}</div>'
        '<div class="bar-track"><div class="bar-fill" '
        f'style="width:{(_as_float(row.get("total")) / maximum_category * 100) if maximum_category else 0:.1f}%"></div></div>'
        f'<div class="bar-value">{_money(row.get("total"))} · {_escape(row.get("pct"))}%</div>'
        "</div>"
        for row in categories[:10]
    )
    insight_cards = (
        "".join(
            f'<article class="alert {"danger" if row.get("priority") == "alta" else "warn"}">'
            f'<div class="eyebrow">{_escape(row.get("priority"))} · {_escape(row.get("type"))}</div>'
            f"<strong>{_escape(row.get('title'))}</strong>"
            f"<p>{_evidence_text(_mapping(row.get('evidence')))}</p></article>"
            for row in insights
        )
        or '<article class="alert"><strong>Nenhum alerta determinístico para os dados atuais.</strong></article>'
    )
    recurring_rows = "".join(_recurring_row_html(row) for row in recurring_items)
    if not recurring_rows:
        recurring_rows = '<tr><td colspan="4">Nenhuma recorrência identificada.</td></tr>'
    installment_rows = "".join(
        f"<tr><td>{_escape(row.get('descricao'))}</td>"
        f"<td>{_money(row.get('valor_mensal'))}</td>"
        f"<td>{_escape(row.get('restantes'))}</td>"
        f"<td>{_money(row.get('comprometido_futuro'))}</td></tr>"
        for row in installment_items
    )
    if not installment_rows:
        installment_rows = '<tr><td colspan="4">Nenhum parcelamento futuro identificado.</td></tr>'

    phases_html = "".join(_phase_html(phase) for phase in action_plan)
    summary_items = []
    for phase in action_plan:
        actions = _list_of_mappings(phase.get("actions"))
        if actions:
            summary_items.append(
                f"<li><strong>{_escape(actions[0].get('title'))}</strong> — "
                f"{_escape(actions[0].get('description'))}</li>"
            )
    ending_soon = _mapping(installments.get("ending_soon"))
    ending_medium = _mapping(installments.get("ending_medium"))
    ending_late = _mapping(installments.get("ending_late"))
    trend_note = (
        "Tendências confiáveis: três ou mais períodos disponíveis."
        if quality.get("reliable_for_trends")
        else "Tendências não avaliadas: são necessários pelo menos três períodos."
    )
    updated_at = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")
    return INSIGHTS_HTML.format(
        classification_url=escaped_classification_url,
        banner=banner,
        period=_escape(overview.get("latest_period")),
        gross_total=_money(overview.get("gross_expenses", overview.get("total_latest"))),
        credits_total=_money(overview.get("credits_total")),
        net_total=_money(overview.get("net_statement_total", overview.get("total_latest"))),
        transaction_count=_escape(overview.get("transaction_count_latest")),
        card_count=_escape(overview.get("card_count")),
        pending=_escape(pending),
        future_commitment=_money(installments.get("total_comprometido_futuro")),
        savings_low=_money(savings.get("conservative")),
        savings_high=_money(savings.get("optimistic")),
        savings_low_pct=_escape(savings.get("conservative_pct")),
        savings_high_pct=_escape(savings.get("optimistic_pct")),
        categories_bars=categories_bars,
        insight_cards=insight_cards,
        recurring_rows=recurring_rows,
        recurring_total=_money(recurring.get("total")),
        recurring_annualized=_money(recurring.get("annualized")),
        installment_rows=installment_rows,
        soon_count=_escape(ending_soon.get("count")),
        soon_total=_money(ending_soon.get("total_monthly")),
        medium_count=_escape(ending_medium.get("count")),
        medium_total=_money(ending_medium.get("total_monthly")),
        late_count=_escape(ending_late.get("count")),
        late_total=_money(ending_late.get("total_monthly")),
        phases_html=phases_html,
        summary_items="".join(summary_items),
        trend_note=_escape(trend_note),
        quality_pct=_escape(quality.get("uncategorized_expense_pct")),
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
                result = application.save_review(
                    payload.get("rows"), mode=str(payload.get("mode") or "approve")
                )
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


def _as_float(value: object) -> float:
    try:
        return float(str(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _evidence_text(evidence: dict[str, Any]) -> str:
    parts = []
    for key, value in evidence.items():
        label = {
            "amount": "valor",
            "period": "período",
            "merchant_groups": "grupos",
            "change_pct": "variação",
            "monthly_installments": "parcelas mensais",
            "future_commitment": "compromisso futuro",
            "pct": "percentual",
        }.get(key, key.replace("_", " "))
        if key in {"amount", "monthly_installments", "future_commitment"}:
            rendered = _money(value)
        elif key in {"change_pct", "pct"}:
            rendered = f"{_escape(value)}%"
        else:
            rendered = _escape(value)
        parts.append(f"{_escape(label)}: {rendered}")
    return " · ".join(parts) or "Evidência disponível no relatório estruturado."


def _recurring_row_html(row: dict[str, Any]) -> str:
    duplicate_badge = (
        ' <span class="pill danger">possível duplicidade</span>'
        if row.get("possivel_duplicidade")
        else ""
    )
    return (
        f"<tr><td>{_escape(row.get('descricao'))}{duplicate_badge}</td>"
        f"<td>{_money(row.get('valor'))}</td>"
        f"<td>{_money(_as_float(row.get('valor')) * 12)}</td>"
        f"<td>{_escape(row.get('meses_observados'))}</td></tr>"
    )


def _phase_html(phase: dict[str, Any]) -> str:
    actions = _list_of_mappings(phase.get("actions"))
    cards = "".join(
        '<article class="action-card">'
        '<div class="action-copy">'
        f"<h3>{_escape(action.get('title'))}</h3>"
        f"<p>{_escape(action.get('description'))}</p>"
        f'<span class="pill effort">{_escape(action.get("effort"))}</span>'
        f'<span class="pill impact">impacto {_escape(action.get("impact"))}</span>'
        "</div>"
        '<div class="action-value">'
        f"<strong>{_action_value(action)}</strong>"
        f"<span>{_escape(action.get('opportunity_label'))}</span>"
        "</div></article>"
        for action in actions
    )
    return (
        '<section class="phase">'
        f'<div class="phase-title"><span>{_escape(phase.get("phase"))}</span><div>'
        f"<h2>{_escape(phase.get('title'))}</h2>"
        f"<p>{_escape(phase.get('subtitle'))}</p></div></div>"
        f"{cards}</section>"
    )


def _action_value(action: dict[str, Any]) -> str:
    value = _as_float(action.get("monthly_opportunity"))
    return _money(value) if value > 0 else "—"


INSIGHTS_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Plano estratégico de redução de despesas</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#090c12; --surface:#121722; --surface2:#171e2b; --border:#283244; --text:#edf2f7; --muted:#94a3b8; --green:#34d399; --red:#fb7185; --orange:#fbbf24; --blue:#60a5fa; --purple:#a78bfa; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:radial-gradient(circle at 50% 0,#172036 0,var(--bg) 34rem); color:var(--text); }}
    .container {{ width:min(1180px,calc(100% - 2rem)); margin:auto; padding:1.2rem 0 4rem; }}
    .topnav {{ display:flex; gap:.4rem; margin-bottom:2.2rem; border-bottom:1px solid var(--border); }}
    .topnav a {{ color:#cbd5e1; padding:.8rem 1rem; text-decoration:none; border-bottom:3px solid transparent; }}
    .topnav .active {{ color:#fff; border-color:var(--green); font-weight:800; }}
    header {{ text-align:center; margin-bottom:1.7rem; }}
    h1 {{ margin:.2rem 0 .6rem; font:800 clamp(1.55rem,4vw,2.45rem)/1.1 ui-monospace,SFMono-Regular,Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; }}
    h2,h3,p {{ margin-top:0; }} h2 {{ font-size:1.15rem; }}
    .muted,.section-note {{ color:var(--muted); }} .accent {{ width:64px; height:3px; background:var(--green); margin:1rem auto; }}
    .warning,.success {{ padding:.85rem 1rem; border-radius:.65rem; margin:1rem 0; border:1px solid; }}
    .warning {{ background:#3a2609; color:#fde68a; border-color:#92400e; }} .success {{ background:#052e16; color:#bbf7d0; border-color:#166534; }}
    .warning a {{ color:inherit; font-weight:800; }}
    .score-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(195px,1fr)); gap:.8rem; margin:1.2rem 0 2rem; }}
    .score {{ position:relative; overflow:hidden; background:linear-gradient(145deg,var(--surface2),var(--surface)); border:1px solid var(--border); border-radius:.8rem; padding:1rem; }}
    .score::before {{ content:""; position:absolute; inset:0 0 auto; height:3px; background:var(--blue); }}
    .score.danger::before {{ background:var(--red); }} .score.warn::before {{ background:var(--orange); }} .score.good::before {{ background:var(--green); }}
    .score span,.eyebrow {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; }}
    .score strong {{ display:block; margin:.45rem 0 .2rem; font:800 1.35rem ui-monospace,SFMono-Regular,Consolas,monospace; }}
    section {{ margin:1rem 0 1.4rem; background:rgba(18,23,34,.94); border:1px solid var(--border); border-radius:.85rem; padding:1.15rem; }}
    .diagnosis {{ display:grid; grid-template-columns:minmax(0,1.3fr) minmax(300px,.7fr); gap:1rem; }}
    .bar-row {{ display:grid; grid-template-columns:minmax(150px,210px) 1fr minmax(145px,auto); gap:.7rem; align-items:center; margin:.7rem 0; font-size:.88rem; }}
    .bar-track {{ height:.72rem; background:#252e3e; border-radius:99px; overflow:hidden; }} .bar-fill {{ height:100%; background:linear-gradient(90deg,var(--red),var(--orange)); border-radius:inherit; }}
    .bar-value {{ text-align:right; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
    .alert {{ border:1px solid var(--border); border-left:3px solid var(--blue); border-radius:.6rem; padding:.85rem; margin:.65rem 0; background:var(--surface2); }}
    .alert.danger {{ border-left-color:var(--red); background:#27141b; }} .alert.warn {{ border-left-color:var(--orange); }} .alert p {{ color:var(--muted); margin:.45rem 0 0; font-size:.88rem; }}
    .phase {{ padding:1.2rem; }} .phase-title {{ display:flex; gap:.85rem; align-items:flex-start; margin-bottom:1rem; }}
    .phase-title>span {{ display:grid; place-items:center; min-width:2rem; height:2rem; border-radius:50%; background:#064e3b; color:#a7f3d0; font:800 1rem ui-monospace,monospace; }}
    .phase-title p {{ color:var(--muted); margin:0; }}
    .action-card {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(145px,auto); gap:1rem; align-items:center; background:var(--surface2); border:1px solid var(--border); border-radius:.72rem; padding:1rem; margin:.75rem 0; }}
    .action-card h3 {{ margin:0 0 .4rem; font-size:1rem; }} .action-card p {{ margin:0 0 .7rem; color:#cbd5e1; line-height:1.45; }}
    .action-value {{ text-align:right; }} .action-value strong {{ display:block; color:var(--green); font:800 1.2rem ui-monospace,monospace; }} .action-value span {{ color:var(--muted); font-size:.75rem; }}
    .pill {{ display:inline-block; border-radius:99px; padding:.24rem .48rem; margin:.1rem .25rem .1rem 0; font-size:.7rem; background:#1e293b; color:#cbd5e1; }}
    .pill.effort {{ background:#13362c; color:#a7f3d0; }} .pill.impact {{ background:#172554; color:#bfdbfe; }} .pill.danger {{ background:#4c0519; color:#fecdd3; }}
    .timeline {{ display:grid; grid-template-columns:repeat(3,1fr); gap:.7rem; margin:1rem 0; }} .timeline div {{ background:var(--surface2); border:1px solid var(--border); border-radius:.6rem; padding:.85rem; }} .timeline strong {{ display:block; color:var(--green); font:800 1.2rem ui-monospace,monospace; }}
    .table-wrap {{ overflow:auto; }} table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:.65rem; border-bottom:1px solid var(--border); text-align:left; }} th {{ color:#cbd5e1; font-size:.78rem; text-transform:uppercase; }} td:nth-child(n+2) {{ font-variant-numeric:tabular-nums; }}
    .summary {{ background:linear-gradient(145deg,#06291e,#0c1e1b); border-color:#166534; padding:1.35rem; }} .summary .range {{ color:var(--green); font:800 clamp(1.45rem,4vw,2.2rem) ui-monospace,monospace; }} .summary li {{ margin:.65rem 0; line-height:1.45; }}
    .footnote {{ color:var(--muted); font-size:.78rem; border-top:1px solid var(--border); padding-top:.85rem; margin-top:1rem; }}
    @media (max-width:850px) {{ .diagnosis {{ grid-template-columns:1fr; }} .action-card {{ grid-template-columns:1fr; }} .action-value {{ text-align:left; }} }}
    @media (max-width:620px) {{ .container {{ width:min(100% - 1rem,1180px); }} .bar-row {{ grid-template-columns:1fr; gap:.3rem; }} .bar-value {{ text-align:left; }} .timeline {{ grid-template-columns:1fr; }} section {{ padding:.8rem; }} }}
  </style>
</head>
<body><div class="container">
  <nav class="topnav"><a class="active" href="/insights">Insights</a><a href="{classification_url}">Classificação</a></nav>
  <header><h1>Plano estratégico de redução</h1><p class="muted">Fatura {period} · {transaction_count} despesas · {card_count} cartões · atualizado em {updated_at}</p><div class="accent"></div></header>
  {banner}
  <div class="score-grid">
    <div class="score danger"><span>Despesas brutas</span><strong>{gross_total}</strong><small>antes de créditos</small></div>
    <div class="score good"><span>Créditos e estornos</span><strong>{credits_total}</strong><small>reduzem o total líquido</small></div>
    <div class="score"><span>Total líquido da fatura</span><strong>{net_total}</strong><small>despesas menos créditos</small></div>
    <div class="score warn"><span>Compromisso futuro</span><strong>{future_commitment}</strong><small>parcelas já contratadas</small></div>
    <div class="score good"><span>Potencial de economia</span><strong>{savings_low}&ndash;{savings_high}</strong><small>{savings_low_pct}%&ndash;{savings_high_pct}% · cenário, não garantia</small></div>
  </div>

  <section class="diagnosis">
    <div><h2>Diagnóstico por categoria</h2><p class="section-note">Distribuição das despesas brutas do período.</p>{categories_bars}</div>
    <div><h2>Alertas prioritários</h2>{insight_cards}<p class="footnote">{trend_note} · {quality_pct}% das despesas estão sem categoria confiável.</p></div>
  </section>

  {phases_html}

  <section><h2>Previsão de encerramento das parcelas</h2><p class="section-note">Sunk costs: acompanhe a liberação de caixa; não trate parcelas contratadas como corte imediato.</p>
    <div class="timeline">
      <div><span>1&ndash;2 meses</span><strong>{soon_count} parcelas</strong><small>{soon_total}/mês liberados</small></div>
      <div><span>3&ndash;6 meses</span><strong>{medium_count} parcelas</strong><small>{medium_total}/mês comprometidos</small></div>
      <div><span>7+ meses</span><strong>{late_count} parcelas</strong><small>{late_total}/mês comprometidos</small></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Merchant</th><th>Parcela mensal</th><th>Restantes</th><th>Compromisso futuro</th></tr></thead><tbody>{installment_rows}</tbody></table></div>
  </section>

  <section><h2>Auditoria de serviços recorrentes</h2><p class="section-note">Atual: {recurring_total}/mês · {recurring_annualized}/ano. Confirme utilidade e duplicidade antes de cancelar.</p>
    <div class="table-wrap"><table><thead><tr><th>Merchant</th><th>Mensal</th><th>Anualizado</th><th>Meses observados</th></tr></thead><tbody>{recurring_rows}</tbody></table></div>
  </section>

  <section class="summary"><span class="eyebrow">Resumo estratégico</span><div class="range">{savings_low}&ndash;{savings_high} / mês</div><p>Potencial calculado por cenários explícitos, sujeito à confirmação de cada ação.</p><ol>{summary_items}</ol><p class="footnote">Não cancele parcelas já contratadas. Valores de economia são estimativas para controle financeiro, não garantia nem recomendação de investimento.</p></section>
</div></body></html>"""
