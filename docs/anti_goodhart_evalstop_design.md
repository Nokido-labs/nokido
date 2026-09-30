# Design Document: Anti-Goodhart Calibration via the EvalStop Pattern

> 🧭 **IMPLÉMENTÉ (réconciliation 2026-08-21).** Le pattern EvalStop / anti-Goodhart vit dans `app/forge_metric_integrity.py` (organe « intégrité des métriques » : nomme EvalStop, scanne la dérive Goodhart via `_scan_provider_trust`). Concept réel, sous ce nom.

**Author**: `ANTIGRAVITY`  
**Date**: 2026-07-26  
**Status**: Proposal (Design-only, Zero code edits)  
**Target Area**: Core Metrics (`forge_trust_score.py` + `forge_rag_engine.py` + `forge_veille_digest.py`)  

---

## 1. Problem Statement: Goodhart's Law in Nokido
Goodhart's Law states: *"When a measure becomes a target, it ceases to be a good measure."*

In Nokido, we observed this during the RAG poisoning incident:
- The system used a single LLM to score `relevance` of crawled entries.
- The LLM "gamed" the metric by assigning high relevance ($\ge 4$) to manufactured, non-existent technical docs.
- The system automatically promoted these entries, poisoning the RAG.

To prevent this overoptimization, we must calibrate internal metrics (`trust_score`, `relevance`, `dopamine`, `novelty`) using **real-world feedback** (ground truth usage) and **judge disagreement** (uncertainty metrics) based on the **EvalStop** framework.

---

## 2. The EvalStop Pattern for Nokido

We propose two primary calibration vectors:

### A. Real-World Retrieval Feedback (Ground Truth Calibration)
Currently, a chunk's `relevance` or `quality_score` is static. We introduce a dynamic decay model where scores are tied to actual downstream usage (`access_count` in `rag_chunks`):

$$R_{\text{calibrated}}(t) = R_{\text{initial}} \cdot \left( \lambda + (1-\lambda)(1 - e^{-\gamma \cdot \text{access\_count}}) \right)$$

- If a chunk is retrieved but never accessed (or its usage leads to test failures), its score decays toward $\lambda \cdot R_{\text{initial}}$ ($\lambda \approx 0.3$).
- This uses downstream agent behavior as the ground truth "world feedback" to correct prior LLM overoptimism.

### B. Judge Disagreement as an Overoptimization Detector
When rating an item (e.g., a candidate tool execution or a bibliography entry), we calculate the variance of scores given by multiple independent judges (e.g., local Qwen, Groq, Mistral):

$$\sigma^2 = \text{Var}(S_{\text{Qwen}}, S_{\text{Groq}}, S_{\text{Mistral}})$$

If $\sigma^2 > \text{Threshold}_{\text{disagreement}}$:
- It indicates the input is in an out-of-distribution (OOD) region where reward models are gaming the boundaries (reward hacking).
- The final score is discounted:
  $$S_{\text{final}} = \mu_{\text{scores}} \cdot (1 - \eta \cdot \sigma^2)$$

---

## 3. Recommended Points of Insertion

### Insertion Point 1: `app/forge_trust_score.py` (Variance Discount)
Inside the action/tool evaluation logic, modify the score compiler to receive ratings from multiple judges and apply the variance discount factor before persisting the action score.

### Insertion Point 2: `app/forge_rag_engine.py` (Access Feedback)
In the retrieval path (`_rag_dense_search` and `_rag_lexical_search`), register read events to increment `access_count`. Introduce a background job in `forge_memory_compactor.py` that recalculates chunk `quality_score` using the access feedback formula.

### Insertion Point 3: `app/forge_veille_digest.py` (Consensus Gate)
Before writing to `veille_digest_suggestions`, pass the suggestions through a multi-model consensus validation. If the models disagree on the priority (`prio`) or target organ, discard the suggestion.
