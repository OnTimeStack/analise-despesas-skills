"""Command-line adapters for the shared application services."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import AnalysisError, ExpenseAnalyzer, load_transactions_csv
from .categorization import Categorizer
from .consolidation import ConsolidationError, ExpectedTotals, InvoiceConsolidator
from .merchants import (
    MerchantKnowledgeBase,
    default_knowledge_base_path,
    prepare_legacy_merchant_review,
    prepare_merchant_review,
)


def process_expenses_main(argv: list[str] | None = None) -> int:
    """Consolidate, reconcile, analyze, and start the human-review workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Processa faturas de ponta a ponta: consolida, concilia, analisa e abre "
            "a revisão humana de merchants."
        )
    )
    parser.add_argument("input", type=Path, help="Arquivo, ZIP ou diretório de entrada")
    parser.add_argument("output", type=Path, help="Diretório único de saída")
    parser.add_argument(
        "--expected-totals",
        type=Path,
        help="CSV: banco,periodo_referencia,total_esperado",
    )
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        help="Base de merchants; padrão: armazenamento local persistente da skill",
    )
    parser.add_argument("--categories", type=Path, help="CSV opcional de regras customizadas")
    parser.add_argument("--port", type=int, default=8765, help="Porta local; padrão 8765")
    parser.add_argument("--open", action="store_true", help="Abre a aplicação no navegador")
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Gera todos os artefatos sem manter o servidor local (útil para automação)",
    )
    args = parser.parse_args(argv)
    knowledge_base = args.knowledge_base or default_knowledge_base_path()
    try:
        expected = ExpectedTotals.from_csv(args.expected_totals) if args.expected_totals else None
        report = InvoiceConsolidator(
            args.input,
            args.output,
            expected_totals=expected,
        ).run()
        if report.requires_confirmation:
            reconciliation_result: dict[str, object] = {
                "status": "aguardando_conciliacao",
                "message": (
                    "A análise foi interrompida: informe ou confirme o total de cada fatura "
                    "e execute novamente."
                ),
                "consolidation": report.to_dict(),
            }
            print(json.dumps(reconciliation_result, ensure_ascii=False, indent=2))
            return 2

        from .webapp import ExpenseReviewApplication, serve_expense_review_app

        if args.no_serve:
            application = ExpenseReviewApplication(
                args.output / "consolidado.csv",
                args.output,
                knowledge_base,
                categories_path=args.categories,
            )
            enrichment = application.results.get("merchant_enrichment", {})
            process_result: dict[str, object] = {
                "status": "pronto_para_revisao",
                "consolidation": report.to_dict(),
                "merchant_enrichment": enrichment,
                "outputs": [
                    str(args.output / "consolidado.csv"),
                    str(args.output / "merchant_review.html"),
                    str(args.output / "analise_estrategica_despesas.html"),
                    str(args.output / "analysis_results.json"),
                ],
            }
            print(json.dumps(process_result, ensure_ascii=False, indent=2))
            return 0

        serve_expense_review_app(
            args.output / "consolidado.csv",
            args.output,
            knowledge_base,
            categories_path=args.categories,
            port=args.port,
            open_browser=args.open,
        )
        return 0
    except (AnalysisError, ConsolidationError, OSError, ValueError) as exc:
        parser.exit(2, f"erro: {exc}\n")


def consolidate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolida CSV/OFX com validação, deduplicação e reconciliação."
    )
    parser.add_argument("input", type=Path, help="Arquivo, ZIP ou diretório de entrada")
    parser.add_argument("output", type=Path, help="Diretório de saída")
    parser.add_argument(
        "--expected-totals",
        type=Path,
        help="CSV opcional: banco,periodo_referencia,total_esperado",
    )
    args = parser.parse_args(argv)
    expected = ExpectedTotals.from_csv(args.expected_totals) if args.expected_totals else None
    try:
        report = InvoiceConsolidator(args.input, args.output, expected_totals=expected).run()
    except ConsolidationError as exc:
        parser.exit(2, f"erro: {exc}\n")
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 2 if report.requires_confirmation else 0


def analyze_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Categoriza e analisa despesas consolidadas com métricas reproduzíveis."
    )
    parser.add_argument("input", type=Path, help="Arquivo consolidado.csv")
    parser.add_argument("output", type=Path, help="Diretório de saída")
    parser.add_argument("--categories", type=Path, help="CSV opcional de regras customizadas")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Recalcula categorias já preenchidas em vez de preservá-las",
    )
    parser.add_argument(
        "--merchant-kb",
        type=Path,
        help="Base CSV de merchants aprovada por revisão humana",
    )
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Interrompe a análise se existir merchant único ainda não aprovado",
    )
    args = parser.parse_args(argv)
    try:
        results = ExpenseAnalyzer(
            args.input,
            categories_path=args.categories,
            output_dir=args.output,
            reclassify=args.reclassify,
            merchant_kb_path=args.merchant_kb,
            require_reviewed=args.require_reviewed,
        ).run()
    except (AnalysisError, ValueError) as exc:
        parser.exit(2, f"erro: {exc}\n")
    summary = {
        "overview": results["overview"],
        "data_quality": results["data_quality"],
        "insights": results["insights"],
        "outputs": ["analysis_results.json", "consolidado_categorizado.csv"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def merchant_review_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepara revisão humana de merchants e mantém a base de conhecimento."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Gera merchant_review.html e CSV")
    prepare.add_argument("input", type=Path, help="Arquivo consolidado.csv")
    prepare.add_argument("output", type=Path, help="Diretório de saída")
    prepare.add_argument(
        "--knowledge-base",
        type=Path,
        default=default_knowledge_base_path(),
        help="Base CSV reutilizável; padrão: armazenamento local persistente da skill",
    )
    prepare.add_argument("--categories", type=Path, help="CSV opcional de regras customizadas")

    legacy = subparsers.add_parser(
        "import-legacy",
        help="Adapta classificações anteriores para a revisão humana atual",
    )
    legacy.add_argument("input", type=Path, help="CSV legado com descrição e categoria")
    legacy.add_argument("output", type=Path, help="Diretório de saída da revisão")
    legacy.add_argument(
        "--knowledge-base",
        type=Path,
        help="Base atual opcional; mappings já aprovados têm precedência",
    )

    serve = subparsers.add_parser(
        "serve",
        help="Abre a aplicação local com páginas de insights e classificação",
    )
    serve.add_argument("input", type=Path, help="Arquivo consolidado.csv")
    serve.add_argument("output", type=Path, help="Diretório de saída da análise")
    serve.add_argument(
        "--knowledge-base",
        type=Path,
        default=default_knowledge_base_path(),
        help="Base CSV reutilizável; padrão: armazenamento local persistente da skill",
    )
    serve.add_argument("--categories", type=Path, help="CSV opcional de regras customizadas")
    serve.add_argument("--port", type=int, default=8765, help="Porta local; padrão 8765")
    serve.add_argument(
        "--open",
        action="store_true",
        help="Abre a aplicação no navegador padrão",
    )

    approve = subparsers.add_parser("approve", help="Importa somente linhas aprovadas")
    approve.add_argument("review", type=Path, help="CSV baixado após a revisão humana")
    approve.add_argument(
        "--knowledge-base",
        type=Path,
        default=default_knowledge_base_path(),
        help="Base CSV reutilizável; padrão: armazenamento local persistente da skill",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            knowledge_base = MerchantKnowledgeBase.load(args.knowledge_base)
            transactions, duplicates_removed = load_transactions_csv(args.input)
            categorizer = (
                Categorizer.from_csv(args.categories) if args.categories else Categorizer()
            )
            decisions = prepare_merchant_review(
                transactions,
                args.output,
                categorizer=categorizer,
                knowledge_base=knowledge_base,
            )
            result = {
                "unique_merchants": len(decisions),
                "already_approved": sum(1 for decision in decisions if decision.approved),
                "pending_review": sum(1 for decision in decisions if not decision.approved),
                "duplicates_removed": duplicates_removed,
                "outputs": [
                    str(args.output / "merchant_review.html"),
                    str(args.output / "merchant_review.csv"),
                ],
            }
        elif args.command == "import-legacy":
            current_knowledge_base = (
                MerchantKnowledgeBase.load(args.knowledge_base) if args.knowledge_base else None
            )
            decisions, summary = prepare_legacy_merchant_review(
                args.input,
                args.output,
                knowledge_base=current_knowledge_base,
            )
            result = {
                **summary,
                "pending_review": sum(1 for decision in decisions if not decision.approved),
                "outputs": [
                    str(args.output / "merchant_review.html"),
                    str(args.output / "merchant_review.csv"),
                    str(args.output / "legacy_import_report.json"),
                ],
            }
        elif args.command == "serve":
            from .webapp import serve_expense_review_app

            serve_expense_review_app(
                args.input,
                args.output,
                args.knowledge_base,
                categories_path=args.categories,
                port=args.port,
                open_browser=args.open,
            )
            return 0
        else:
            knowledge_base = MerchantKnowledgeBase.load(args.knowledge_base)
            approved_count, pending_count = knowledge_base.merge_review(args.review)
            result = {
                "approved_imported": approved_count,
                "pending_ignored": pending_count,
                "knowledge_base": str(knowledge_base.path),
                "knowledge_base_entries": len(knowledge_base.entries),
            }
    except (AnalysisError, OSError, ValueError) as exc:
        parser.exit(2, f"erro: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
