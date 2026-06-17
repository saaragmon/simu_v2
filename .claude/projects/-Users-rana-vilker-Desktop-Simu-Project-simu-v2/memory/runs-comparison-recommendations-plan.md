---
name: runs-comparison-recommendations-plan
description: Planned (not yet built) work for required-replications, alternative comparison, recommendations, summary — with two open statistical decisions
metadata:
  type: project
---

Deferred deliverable (paused 2026-06-14): the report sections "חישוב מספר הרצות, השוואה בין חלופות, המלצות והסברים, וסיכום" under overall confidence 0.9 / relative precision 0.1. User wants to build this later together with the teammate who built the stats code — do NOT build until then.

**Current state vs gaps:**
- Required replications: formula `MultiRunStatistics.required_replications()` exists in sim_stats.py (~L287, n* = ⌈(t·s/(δ·x̄))²⌉) but is NEVER called — main.py uses fixed `DEFAULT_RUNS=20`. Gap: no pilot-study step.
- Comparison: `print_comparison()` in main.py (~L115) uses Welch t-test. `paired_t_test` exists in sim_stats but unused.
- Recommendations: "FINAL RECOMMENDATIONS" block (main.py ~L309) picks best per KPI by mean only.
- Summary: does not exist.

**Planned placement (all in main.py, small helpers in sim_stats.py):** new "[2] Pilot study" step (run ~10 pilot reps, compute n* per KPI, take max → drives full run count); upgrade `print_comparison()`; rewrite FINAL RECOMMENDATIONS to weigh significance+logic+budget; add closing summary block.

**Two OPEN decisions the user couldn't answer alone (waiting for teammate):**
1. Test type: code runs CRN (all scenarios use base_seed=1000) but applies Welch (assumes independence) — mismatch. Options: paired t-test + keep CRN (recommended, more powerful) vs Welch + independent seeds per scenario.
2. "Overall confidence 0.9 for all comparisons" with 9 tests (3 combos × 3 KPIs): Bonferroni correction (α split, recommended) vs per-test 0.9.

Related: [[simu-festival-architecture-polymorphic-events]] if created.
