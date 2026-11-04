# Analysis Framework

## Effort-vs-Impact Matrix

Every potential expense reduction action is classified along two axes:

### Effort Levels
- **Trivial (5 min)**: Cancel a subscription online, unsubscribe from a service
- **Low (15-30 min)**: Audit a category, compare prices, call to negotiate
- **Medium (requires change)**: Negotiate a contract, restructure a spending habit, switch providers
- **High (lifestyle change)**: Alter commuting patterns, change diet/cooking habits, move housing

### Impact Levels
- **High (> R$ 500/mês)**: Priority 1 — do this week
- **Medium (R$ 150-500/mês)**: Priority 2 — do this month
- **Low (< R$ 150/mês)**: Priority 3 — do when convenient

The best recommendations are **Trivial effort + High impact**. Always present these first.

## The 4-Phase Action System

### Phase 1: Immediate Cuts — Subscriptions & Recurring Services
**Why first**: Canceling a subscription takes minutes and saves every month forever. No other action has this ROI.

What to look for:
- **Duplicate services**: Multiple charges from the same provider (e.g., 2-3 LinkedIn plans, multiple streaming services from same family)
- **Possibly unused subscriptions**: Ask the user to confirm usage; an unfamiliar or small charge is not proof of waste
- **Overlapping tools**: Multiple AI tools, multiple cloud storage services, multiple fitness apps
- **Loyalty/rewards programs**: Monthly fees for points programs that may not justify the cost (Smiles, Livelo, airline clubs) — these are especially insidious because the "value" is deferred and psychological
- **Premium tiers**: Could a cheaper plan suffice? (e.g., LinkedIn Premium vs. Basic)

Detection heuristic for recurring charges:
1. Same approved friendly merchant name appears monthly across multiple `periodo_referencia` values
2. Fixed amount (no variation or very small variation)
3. Categorized as "Serviços Recorrentes" or similar
4. Known subscription keywords: "SUBSCRIPTION", "ASSINATURA", "MENSAL", "PLANO", "CLUBE", "PRIME", ".AI", "SaaS names"

### Phase 2: Containment — Large One-Off & Installment Discipline
**Why second**: Can't undo past installments, but can prevent future ones.

What to look for:
- **Mega-purchases**: Any single transaction > R$ 1.000 deserves a callout and context
- **Long installments (8-12x)**: These "mortgage" the credit card for a full year
- **Installment accumulation**: Sum all `parcela` fields to show total future commitment
- **Installment moratorium**: If total committed > 1 month's income equivalent, recommend a freeze on new installments
- **Negotiable expenses**: Education, health plans — these often have discounts for boleto/annual payment

Installment analysis algorithm:
```
For each transaction where parcela matches "N/M":
  current = N
  total = M
  remaining = M - N
  monthly_cost = valor
  future_commitment = valor * remaining
  expiry_months = remaining
```

Group by expiry timeline:
- Ending in 1-2 months (good news — automatic relief)
- Ending in 3-6 months (medium horizon)
- Ending in 7-12+ months (long commitment)

### Phase 3: Optimization — Daily Spending Habits
**Why third**: Harder to change, smaller per-action impact, but compounds over time.

What to look for:
- **Transaction frequency**: > 30 transactions in a category suggests fragmented/impulsive buying
- **Grocery fragmentation**: Many small supermarket visits vs. planned weekly shops. Count distinct supermarket transactions — if > 10/month, recommend consolidation
- **Fuel costs**: Sum all gas station charges. If high, suggest price comparison apps or route optimization
- **Eating out frequency**: Count restaurant/bakery/delivery transactions. Calculate average ticket and frequency
- **Delivery vs. cooking**: Look for iFood, Rappi, UberEats patterns

Recommendation approach:
- Never say "stop eating out" — say "reduce from 16 to 8 times/month by [specific substitution]"
- Always frame as a choice, not deprivation
- Provide the math: "each skipped R$ 50 restaurant meal that becomes a R$ 15 home meal saves R$ 35 × 8 = R$ 280/mês"

### Phase 4: Review — Lower Priority Items
**Why last**: These are smaller items, personal choices, or things that may have legitimate reasons.

What to look for:
- **Hobbies with declining use**: Expensive hobby charges (shooting range, sports clubs) — note but don't judge; ask if usage justifies cost
- **Clothing trends**: If vestuário is growing month-over-month, suggest a monthly cap
- **Duplicate fitness**: Multiple gym/academy charges — is the user actually using all of them?
- **Pet expenses**: Usually non-negotiable but worth noting the total
- **Insurance**: Review for competitive rates but don't suggest canceling protection

## Trend Interpretation Rules

From the `trends` section of `analysis_results.json`:

| Trend | Signal | Action |
|-------|--------|--------|
| > +50% | Alarm — something changed dramatically | Investigate and call out prominently |
| +20% to +50% | Growing concern — not sustainable | Recommend containment |
| +5% to +20% | Mild growth — monitor | Mention in context |
| -5% to +5% | Stable | No action needed |
| -5% to -20% | Improving | Acknowledge positive trend |
| < -20% | Strong reduction | Celebrate but verify it's real (not just timing) |

Special cases:
- A category showing "—" trend means insufficient data (only 1 month) — skip trend analysis
- Categories with R$ 0 in early months that suddenly appear are "new spending" — ask for context before treating them as a concern
- "Pagamentos e Créditos" should be excluded from trend analysis — it's a settlement category, not spending

## Multi-Card / Multi-Bank Analysis

Always check for:
1. **All banks present in data** — even if a bank has no transactions in the latest period, it may have active installments
2. **Card count per bank** — some banks have multiple cards (additional cards for family members)
3. **Cross-bank patterns** — same approved friendly merchant appearing on different cards (possible duplicate charges or split spending)
4. **Bank-level totals** — show the user which card/bank concentrates the most spending

If a bank is missing from the latest period:
- Note it explicitly: "Santander não aparece na fatura de Abril — verifique se a fatura ainda não fechou ou se não foi incluída nos dados"
- Still analyze its historical data for installments and trends

## Savings Calculation

For projected savings, always provide a range (conservative to optimistic):
- **Conservative**: Only count Phase 1 (subscriptions) + confirmed duplicates
- **Optimistic**: Include all 4 phases with estimated behavioral changes

Never overstate savings — it's better to say "R$ 3.000-5.000/mês" than "R$ 8.000/mês" if the higher number depends on major lifestyle changes.

For the summary, calculate:
- `savings_pct = estimated_savings / total_expenses × 100`
- If savings_pct > 30%, that's a strong plan
- If savings_pct > 50%, double-check — some of that is likely aspirational

## Data Integrity Rule

**All aggregate numbers in the dashboard (totals, installment commitments, savings ranges, category breakdowns) MUST be sourced from `analysis_results.json`**, not recomputed from the raw CSV. The script handles deduplication of installments across periods, correct exclusion of payments/saldo anterior from expense totals, and proper trend calculation. Recomputing these values when generating the HTML will produce incorrect results (most commonly: installment double-counting across periods, and inclusion of saldo anterior in expense totals).
