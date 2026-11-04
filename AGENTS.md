# AGENTS.md

Instruções de trabalho para Codex e outros agentes que modificam este repositório.

## Objetivo do projeto

Este projeto consolida faturas e extratos, reconcilia os valores informados pelo usuário, enriquece merchants com revisão humana e gera análises de despesas reproduzíveis. O mesmo núcleo deve atender Claude, ChatGPT, Codex e execução direta por CLI.

## Fontes canônicas

- `src/expense_skills/`: regras, modelos e casos de uso compartilhados. Não replique lógica de negócio nos wrappers.
- `skills/`: skills canônicas para Agent Skills e o plugin descrito por `plugin.json`.
- `consolidar-faturas/` e `analise-estrategica-despesas/`: entradas compatíveis com instalações Claude anteriores. Mantenha seus scripts como adaptadores finos.
- `tests/`: testes locais com dados sintéticos. Nunca adicione faturas, extratos ou bases reais.

Ao alterar um comportamento de agente, atualize tanto a skill canônica em `skills/` quanto a entrada legada correspondente. Ao alterar uma regra financeira, implemente-a no núcleo compartilhado e cubra-a com teste.

## Invariantes funcionais

- Antes de processar, faça a triagem descrita nas skills. Solicite arquivos e o total de cada fatura; não suponha que o usuário conheça os requisitos.
- Não invente transações nem valores para fechar uma reconciliação. Total indisponível significa fatura não verificada.
- Valores positivos representam despesas; pagamentos, créditos e estornos permanecem negativos e não entram no total de despesas.
- Preserve origem, período, cartão, descrição original e categoria nativa para auditoria.
- Use `Decimal` para dinheiro. Um valor inválido deve falhar de forma explícita, nunca virar zero.
- A base de merchants aprovada tem precedência. Classificações históricas são sugestões, não aprovações.
- Sem evidência razoável, use `Desconhecido`, `Desconhecida` e confidence 0%.
- Relatórios e insights usam o nome amigável; o nome original continua disponível para auditoria.
- A revisão humana fica separada dos insights. Salvar aprovações deve atualizar a base e recalcular localmente os resultados.

## Arquitetura e limites

- Preserve as camadas existentes: parsing/modelos, categorização, casos de uso, CLI/web e adaptadores de skill.
- Prefira biblioteca padrão e funções determinísticas. Não introduza framework, banco de dados ou serviço remoto sem necessidade demonstrada.
- A aplicação de revisão deve permanecer em `127.0.0.1`, sem CORS aberto, com token por processo, limite de corpo e escrita atômica.
- Não faça chamadas externas de IA durante consolidação, classificação ou atualização dos insights. Uma narrativa opcional por IA é uma operação separada e explícita.
- Não derive números do dashboard lendo novamente o CSV. Use exclusivamente os agregados de `analysis_results.json`.

## Serviços pagos e dados financeiros

Trabalho local e dependências públicas sem cobrança são permitidos. Antes de qualquer API ou serviço pago, medido, com quota ou potencialmente faturável:

1. estime e declare um teto cumulativo em USD;
2. obtenha duas confirmações humanas separadas para o mesmo teto;
3. pare antes de ultrapassá-lo e repita as duas confirmações para um novo bloco, normalmente de no máximo USD 50.

Uma autorização ampla ou anterior não vale como confirmação. Nunca envie dados financeiros a um serviço externo sem informar claramente o destino e obter autorização específica. Não registre em logs descrições sensíveis quando contagens e totais agregados forem suficientes.

## Alterações e validação

Use `apply_patch` para edições manuais e preserve mudanças do usuário que não pertençam à tarefa. Antes de concluir uma mudança de código, execute:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
uvx ruff format --check .
uvx ruff check .
uvx mypy src tests
uv build
```

Quando uma skill mudar, valide as quatro entradas:

```bash
uv run --with pyyaml python "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" skills/consolidar-faturas
uv run --with pyyaml python "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" skills/analise-estrategica-despesas
uv run --with pyyaml python "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" consolidar-faturas
uv run --with pyyaml python "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" analise-estrategica-despesas
```

Se o validador não estiver instalado nesse caminho, use o validador equivalente disponível no harness; não pule a validação silenciosamente. Para mudanças na interface, teste ao menos o fluxo de salvar a classificação e confirmar a atualização dos insights.

## Entrega

- Não versione `output/`, `outputs/`, `padronizado/`, bases de merchants locais ou artefatos com dados financeiros.
- Descreva no PR as mudanças funcionais, os limites de privacidade e todos os comandos de validação executados.
- Não faça merge, release, publicação ou deploy apenas porque o PR foi solicitado; cada ação exige autorização própria.
