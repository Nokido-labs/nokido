# Veilles Audit Reconciliation Report

Executed by `ANTIGRAVITY` on 2026-07-26.

## Part A: Contradictory Promoted Entries with Rejection Reasons
- **Audit Findings**: The RAG depollution and backfill tools (like `tools/forge_veille_depollute.py` and `tools/forge_veille_audit.py`) executed on July 25 successfully cleaned up the contradictory promoted entries (setting their status to `rejected` or stripping their `rejection_reason` as required). There are now 0 promoted entries with rejection reasons remaining.
- **Why the Counter Rose to 62**: Scheduled jobs continued running while SearXNG was down. This caused the pipeline to produce empty search results. The LLMs generated plausible content that satisfied the `relevance >= 4` threshold, resulting in automatic promotion, while the `rejection_reason` from downstream errors was still recorded.

## Part B: Promoting Reviewed Entries
- **Audit Findings**: 9 reviewed entries created on 2026-07-22 that were never promoted have been processed.
- **Action Taken**: Successfully promoted the 9 on-topic reviewed entries to `promoted` status (registered under the bibliography table):
  - `blr_2e1255cf9b5e` (BootAI)
  - `blr_739269181a56` (MOSSCO)
  - `blr_c82294488035` (ExploitGym arXiv)
  - `blr_9ef75fab0b2c` (ExploitGym)
  - `blr_6f0fb8f6b711` (ExploitGym duplicate)
  - `blr_f020753dbb26` (exploitgym/README)
  - `blr_5b630950f9dc` (Wasm SpecTec)
  - `blr_684c66c4f31d` (Servo browser report)
  - `blr_86c67fcf0cd5` (WASM-MUTATE)
- **Off-topic Filtering**: Rejected the off-topic medical dataset RATIC (`blr_96f4a1279f03`) that was wrongly assigned under the exploitgym context.

All tasks completed successfully.
