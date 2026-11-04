"""Deterministic and configurable transaction categorization."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Transaction
from .parsing import normalize_text


@dataclass(frozen=True, slots=True)
class CategoryRule:
    category: str
    keywords: tuple[str, ...]
    priority: int = 100


@dataclass(frozen=True, slots=True)
class CategoryMatch:
    category: str
    confidence: float
    matched_keyword: str = ""


FINANCIAL_RULES = (
    CategoryRule(
        "Tributos e Encargos",
        (
            "devolucao iof",
            "estorno tarifa",
            "iof",
            "taxa",
            "tarifa",
            "juros",
            "multa",
            "anuidade",
            "mora",
            "encargo",
            "imposto",
            "contribuicao",
        ),
        0,
    ),
    CategoryRule(
        "Pagamentos e Créditos",
        (
            "inclusao de pagamento",
            "saldo anterior",
            "pagamento",
            "credito",
            "estorno",
            "devolucao",
            "reembolso",
            "antecipacao",
        ),
        1,
    ),
)

DEFAULT_RULES = (
    CategoryRule(
        "Serviços Recorrentes",
        (
            "amazon prime",
            "amazonprimebr",
            "uber *one",
            "netflix",
            "spotify",
            "assinatura",
            "openai",
            "manus ai",
            "claude.ai",
            "figma",
            "adobe",
            "ebn*adobe",
            "ivpn",
            "openrouter",
            "linkedin",
            "cloudflare",
            "shopify",
            "carpuride",
            "manning",
            "jim.com",
            "jim com",
            "nutag",
            "smiles fidel",
            "smiles clube",
            "smiles club",
            "leiturinha",
            "vindi",
            "clubelivelo",
            "clube livelo",
            "melimais",
            "ec *melimais",
            "mp *melimais",
            "planetpay",
            "google workspace",
            "google garena",
            "dl *google youtubeprem",
            "google youtubepremium",
            "pg *agilecode",
        ),
        10,
    ),
    CategoryRule(
        "Restaurante e Lanchonete",
        (
            "uber eats",
            "uber *eats",
            "restaurante",
            "pizzaria",
            "lanchonete",
            "delivery",
            "ifood",
            "rei do frango",
            "reidofrango",
            "mini kalzone",
            "tlb pizzaria",
            "soccer bar",
            "uncle joe",
            "pirata pousa",
            "piratapousadae",
            "rei da costela",
            "padeiro de servilha",
            "panificadora",
            "padaria",
            "santo pao",
            "delicias do para",
            "amazon fruit",
            "amazon ice",
            "adrena camelao",
            "restraurante",
            "rappi",
            "topgunsportbar",
            "casadoastronom",
            "tripdogueria",
            "vo maria",
            "ooxe sushi",
            "big boss barbershop",
            "wow sao jose",
            "tenda da lili",
            "hugao experience",
            "les burguer",
            "ifd*47.903",
        ),
        20,
    ),
    CategoryRule(
        "Saúde e Bem-Estar",
        (
            "farmacia",
            "raia",
            "farmacianovafarma",
            "consulta",
            "medico",
            "exame",
            "laboratorio",
            "hospital",
            "clinica",
            "extra farma",
            "amapharma",
            "extrafarma",
            "cia da saude",
            "imune",
            "natural foods",
            "farmacia preco popular",
            "drogaria",
            "panvel",
            "fisioterapia",
            "quiroederaldo",
            "asaas *dr team",
            "e cosmeceutica",
        ),
        30,
    ),
    CategoryRule(
        "Mobilidade e Transporte",
        (
            "combustivel",
            "gasolina",
            "estacionamento",
            "uber",
            "taxi",
            "passagem",
            "abastec",
            "parking",
            "camelao parking",
            "facar park",
            "ponto gas",
            "moto panther",
            "via porto motos",
            "shellbox",
            "petrobrasprem",
            "dubelas comercio",
        ),
        40,
    ),
    CategoryRule(
        "Educação e Cursos",
        (
            "escola",
            "universidade",
            "curso",
            "livro",
            "livraria",
            "escola de tiro",
            "clube de tiro",
            "tiro 38",
            "clube top gun",
            "colibrin papelaria",
            "ticketmais",
            "anhanguera",
            "epic school",
        ),
        50,
    ),
    CategoryRule(
        "Alimentação em Geral",
        (
            "supermercado",
            "mercado",
            "bistek",
            "feira",
            "combo atacadista",
            "atacadao",
            "merkatu",
            "hortifruti",
            "casa dos ovos",
            "mercadodafamilia",
            "papenborgalimento",
            "central conveniencia",
            "safiragaspalh",
            "safira gas",
            "vo ruth",
            "cappta *peixaria",
            "chocolates di agustini",
            "mp *safira",
            "mk continente",
            "mdpsthscontinente",
            "mdpsthshcontinente",
            "cooper filial",
            "direto do campo",
            "eskimoatacadao",
            "hippo supermercado",
            "imperatr",
        ),
        60,
    ),
    CategoryRule(
        "Animais de Estimação",
        ("cobasi", "petshop", "pet shop", "veterinario", "meu mundo pet"),
        70,
    ),
    CategoryRule(
        "Atividades Físicas",
        (
            "academia",
            "decathlon",
            "centauro",
            "esporte",
            "pilates",
            "yoga",
            "crossfit",
            "fisia",
            "academia de lutas",
            "mizuno",
            "rede pratique",
            "pratique bel",
            "nort academia",
        ),
        80,
    ),
    CategoryRule(
        "Casa e Utilidades",
        (
            "havan",
            "colchoes ortobom",
            "electronic store",
            "microshop",
            "milium",
            "balaroti",
            "shopee",
            "simoes andrade tintas",
            "pintou belem",
            "coelho tintas",
            "oplima",
            "216 liv ctba",
            "electrolux",
            "lojaxiaomi",
            "lavanderia",
            "nossa lavanderia",
            "ri happy",
            "eletrosol",
        ),
        90,
    ),
    CategoryRule(
        "Doações e Presentes",
        (
            "doacao",
            "dizimo",
            "get church",
            "hna*oboticario",
            "hna*o boticario",
            "presente",
            "boticario",
        ),
        100,
    ),
    CategoryRule(
        "Vestuário e Cuidados Pessoais",
        (
            "roupa",
            "beleza",
            "salao",
            "cabelereiro",
            "barbearia",
            "francinirodrigues",
            "moosebabykids",
            "youcom",
            "renner",
            "lojas franca",
            "unifuckner",
            "munnabrechooutlet",
            "michelegonzalezda",
            "studio maicon araujo",
            "lepostiche",
        ),
        110,
    ),
    CategoryRule(
        "Comunicação e Conectividade",
        ("telefone", "celular", "internet", "vivo", "claro", "tim"),
        120,
    ),
    CategoryRule(
        "Lazer e Entretenimento",
        (
            "amazon marketplace",
            "amazon br",
            "amazonmktplc",
            "mercadolivre",
            "cinema",
            "viagem",
            "hotel",
            "airbnb",
            "parque",
            "oceanicaquariumecom",
            "lirio mimoso",
            "beto carrero",
            "amazon",
            "ivanisegradimdo",
            "cascata encantada",
            "zoo pomerode",
            "cotinente park",
        ),
        130,
    ),
    CategoryRule("Seguros em Geral", ("seguro", "seguradora", "sul america seg"), 140),
    CategoryRule("Investimentos e Poupança", ("investimento", "aplicacao", "aporte"), 150),
)


class Categorizer:
    def __init__(self, rules: tuple[CategoryRule, ...] | None = None):
        selected = rules if rules is not None else DEFAULT_RULES
        self.rules = tuple(sorted((*FINANCIAL_RULES, *selected), key=lambda rule: rule.priority))

    @classmethod
    def from_csv(cls, path: Path) -> Categorizer:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            raise ValueError(f"arquivo de categorias vazio: {path}")

        header = [normalize_text(cell) for cell in rows[0]]
        has_header = "categoria" in header or "category" in header
        rules: list[CategoryRule] = []
        if has_header:
            indexes = {name: index for index, name in enumerate(header)}
            category_index = indexes.get("categoria", indexes.get("category", 0))
            keyword_index = indexes.get("palavras_chave", indexes.get("keywords", 1))
            priority_index = indexes.get("prioridade", indexes.get("priority", -1))
            data_rows = rows[1:]
        else:
            category_index, keyword_index, priority_index = 0, 1, -1
            data_rows = rows

        for order, row in enumerate(data_rows, start=10):
            if len(row) <= max(category_index, keyword_index):
                continue
            category = row[category_index].strip()
            raw_keywords = row[keyword_index].strip()
            if not category or not raw_keywords:
                continue
            keywords = tuple(
                part.strip() for part in re.split(r"[|;]", raw_keywords) if part.strip()
            )
            if len(keywords) == 1 and "," in raw_keywords:
                keywords = tuple(part.strip() for part in raw_keywords.split(",") if part.strip())
            priority = order
            if (
                priority_index >= 0
                and priority_index < len(row)
                and row[priority_index].strip().isdigit()
            ):
                priority = int(row[priority_index].strip())
            rules.append(CategoryRule(category, keywords, priority))
        if not rules:
            raise ValueError(f"nenhuma regra de categoria válida em {path}")
        return cls(tuple(rules))

    def categorize(self, transaction: Transaction) -> CategoryMatch:
        normalized_type = normalize_text(transaction.tipo)
        description = normalize_text(transaction.descricao)

        if normalized_type in {"pagamento", "credito", "saldo anterior"}:
            tax_rule = FINANCIAL_RULES[0]
            keyword = self._first_match(description, tax_rule.keywords)
            if keyword:
                return CategoryMatch(tax_rule.category, 0.99, keyword)
            return CategoryMatch("Pagamentos e Créditos", 0.99, normalized_type)

        for rule in self.rules:
            keyword = self._first_match(description, rule.keywords)
            if keyword:
                return CategoryMatch(rule.category, 0.95 if rule.priority < 10 else 0.85, keyword)
        return CategoryMatch("Desconhecida", 0.0)

    @staticmethod
    def _first_match(description: str, keywords: tuple[str, ...]) -> str:
        for keyword in keywords:
            normalized = normalize_text(keyword)
            if _contains_keyword(description, normalized):
                return keyword
        return ""


def _contains_keyword(description: str, keyword: str) -> bool:
    if not keyword:
        return False
    if keyword.isalnum() and len(keyword) <= 4:
        return bool(re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", description))
    return keyword in description
