# Dashboard Template Specification

## CRITICAL: Data Source Rule

**All numerical values in the dashboard MUST come exclusively from `analysis_results.json`.** The LLM generating the HTML must NOT recompute totals, installment futures, savings estimates, or any other metric by re-reading the consolidado.csv. The script `analyze_expenses.py` already performs all calculations with proper deduplication and edge-case handling. Recomputing leads to double-counting errors (e.g., installments counted once per period instead of once per unique parcela).

Display the approved friendly merchant name from the JSON in rankings, recurring charges and installment tables. Keep the original statement description only as secondary audit context when needed.

Specifically:
- **Total expenses** → `results.overview.total_latest` (latest period) or compute average from `results.overview.all_periods`
- **Installment future commitment** → `results.installments.total_comprometido_futuro` (already deduplicated)
- **Installment count** → `results.installments.count`
- **Installment timeline groups** → `results.installments.ending_soon/ending_medium/ending_late`
- **Savings potential** → `results.savings_potential.conservative/moderate/optimistic`
- **Category totals** → `results.categories` (latest period) or `results.trends` (all periods)
- **Recurring services total** → `results.recurring_services.total`
- **Top expenses** → `results.top_expenses`

If a value is not available in the JSON, ask for it to be added to the script — do NOT derive it manually from raw transaction data.

## Design Direction

Dark theme, data-dense, professional. Think Bloomberg terminal meets modern fintech app. The tone should feel serious but not cold — the user is dealing with real financial stress and the dashboard should feel like a calm, competent advisor.

## Typography

- **Headings & Numbers**: Use a local monospace stack for financial data (`ui-monospace`, `SFMono-Regular`, `Consolas`, monospace)
- **Body text**: `DM Sans` — clean, readable, warm
- **Fonts**: use system font stacks only; the dashboard must not make network requests

## Color Palette (CSS Variables)

```css
:root {
  --bg: #0a0c10;
  --surface: #12151c;
  --surface2: #1a1e28;
  --border: #252a36;
  --text: #e8eaf0;
  --text-dim: #8891a5;
  --accent: #22c55e;       /* green — positive actions, savings */
  --accent-dim: rgba(34,197,94,0.12);
  --red: #ef4444;           /* alerts, danger, high expense */
  --red-dim: rgba(239,68,68,0.12);
  --orange: #f59e0b;        /* warnings, medium priority */
  --orange-dim: rgba(245,158,11,0.12);
  --blue: #3b82f6;          /* informational, neutral emphasis */
  --blue-dim: rgba(59,130,246,0.12);
  --purple: #a78bfa;        /* secondary data, variety */
}
```

## Layout

- Max width: 1100px, centered
- Padding: 32px horizontal, 32px top, 60px bottom
- Responsive: stack on mobile (< 700px)
- All content in a single scrollable column

## Component Specifications

### 1. Header
- Centered, monospace h1 in uppercase
- Subtitle with period and transaction count
- Green accent bar (60px wide, 3px tall) below

### 2. Scorecards Row
- 3 cards in a grid (auto-fit, min 220px)
- Each card: surface background, 1px border, 12px radius, 3px colored top stripe
- Contains: uppercase label (12px, dimmed), large monospace value (26px), small subtitle
- Color-code: danger (red) for total expenses, warn (orange) for commitments, good (green) for savings potential
- **Card 1 — Total Fatura Atual**: Use `results.overview.total_latest` for the latest period total. Subtitle: transaction count and period name from `results.overview.latest_period`
- **Card 2 — Compromisso Futuro**: Use `results.installments.total_comprometido_futuro`. Subtitle: `results.installments.count` parcelas ativas. Do NOT recompute this value — it is already deduplicated in the script
- **Card 3 — Potencial de Economia**: Use `results.savings_potential.conservative` to `results.savings_potential.optimistic` as a range. Subtitle: percentage range from `conservative_pct` to `optimistic_pct`

### 3. Category Bar Chart
- Horizontal bars with labels (200px width), proportional fill bars, monospace values
- Color each bar differently (red for top, orange for second, blue, purple, gray for rest)
- Bars animate width on load (CSS transition: width 1s ease)

### 4. Alert Boxes
- Red-tinted background with red border and red title
- Use for categories with >50% growth or anomalous spikes
- Include specific numbers and context

### 5. Insight Boxes
- Surface background, orange left border (3px), 8px border-radius on right side
- Use for key analytical observations that connect data points
- Bold key terms within dimmed text

### 6. Action Cards (the core content)
- Grouped by Phase (1-4), each phase has a numbered section title
- Each action card: surface background, border, 12px radius
- Grid layout: main content left (title + description), savings right (large green number + "por mês" label)
- Tags below description: colored pills showing effort level and impact level
- Effort tags: easy (green), medium (orange), hard (red)
- Impact tags: high (green), medium (blue)

### 7. Summary Box
- Green-tinted gradient background with green border
- Large monospace number for total projected savings
- Numbered priority sequence (①②③④)
- Footnote about installments (smaller, dimmed)

## HTML Structure Template

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Plano Estratégico de Redução de Despesas</title>
  <link href="[google fonts url]" rel="stylesheet">
  <style>
    /* CSS variables, reset, all component styles */
    /* Everything self-contained — no external CSS files */
  </style>
</head>
<body>
  <div class="container">
    <!-- 1. Header -->
    <div class="header">
      <h1>PLANO ESTRATÉGICO DE REDUÇÃO</h1>
      <p>Fatura [Period] — Análise de [N] transações em [M] cartões</p>
    </div>

    <!-- 2. Scorecards -->
    <div class="score-row">
      <!-- 3 score-cards: total, committed, savings potential -->
    </div>

    <!-- 3. Diagnosis section with bar chart -->
    <div class="section">
      <!-- Category bars, alert boxes, insight boxes -->
    </div>

    <!-- 4. Phase 1: Immediate Cuts -->
    <div class="section">
      <!-- Action cards for subscriptions -->
    </div>

    <!-- 5. Phase 2: Containment -->
    <div class="section">
      <!-- Action cards for large/installment expenses -->
    </div>

    <!-- 6. Phase 3: Optimization -->
    <div class="section">
      <!-- Action cards for daily spending -->
    </div>

    <!-- 7. Phase 4: Review -->
    <div class="section">
      <!-- Action cards for lower-priority items -->
    </div>

    <!-- 8. Summary -->
    <div class="summary-box">
      <!-- Total savings, priority sequence, footnotes -->
    </div>
  </div>
</body>
</html>
```

## Responsive Breakpoints

At `max-width: 700px`:
- Action cards stack (single column)
- Savings amounts move to left-aligned
- Bar chart labels narrow to 120px
- Scorecard values shrink to 22px
- Header h1 shrinks to 22px

## Accessibility Notes

- All text meets WCAG AA contrast against dark backgrounds
- Don't rely solely on color — always pair color with text labels
- Use semantic HTML (h1-h3, sections)
- No JavaScript required — pure HTML/CSS
