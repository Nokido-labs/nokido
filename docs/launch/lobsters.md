# 🌳 Lobste.rs submission

Lobste.rs = invite-only tech forum, ultra-qualifié (1500 upvotes
peer-reviewed valent autant que 10k upvotes Reddit). Tonalité : technique,
direct, scepticisme bienveillant.

## URL field

```
https://github.com/user/Nokido
```

(Lobsters préfère URLs canoniques. Pas de short-link.)

## Title (Lobsters auto-fetch depuis page, mais override possible)

```
Nokido — autonomous local-first AI OS with neuro-symbolic governance
```

## Tags (max 3 — important)

- `ai`
- `python`
- `practices`

**Évite** `release` (réservé aux releases majeures) et `show` (différent de Show HN).

## Story text (optionnel mais bonne pratique)

Lobsters limite le commentaire de soumission à ~500 chars. Bref + direct :

```
Solo dev, alpha branch. Built around three inversions of the current
agent ecosystem: hub-as-orchestrator (not LLM-as-orchestrator), RAG-as-
memory (not stateless sessions), symbolic verdicts (no LLM-judging-LLM).
Tested on a consumer APU (Ryzen 7 8700G + iGPU); HumanEval 87.8%,
BFCL v4 90-96%. Docker compose with five profiles, 25 MCP tools,
vault-backed key management. AGPLv3. Curious about feedback on the
cascade routing and symbolic scorecard.
```

## ⏱️ Timing

Lobsters audience = mainly US techy crowd. Post **15:00 Paris** (= 09:00
EST) — same as HN peak.

## 💬 Réponses Lobsters typiques

Lobsters commentators sont précis et patient. Format : tu peux développer
longuement (Lobsters n'a pas de limite commentaire).

### "How is this different from $existing_tool?"

> Donne la comparaison technique précise, pas marketing. Liste 3-5
> deltas concrets.

### "The scoring axes seem arbitrary"

> "Fair critique. The 6 axes (AST + pylint E/F + McCabe + dep-graph
> centrality + LOC + token budget) were chosen because (1) all 6 are
> deterministic AST-or-numerical, no LLM in the loop ; (2) they
> correlate with what humans actually red-flag in PR review (per
> Marcus 2020 + my own experience). The thresholds are tunable in
> forge_scorecard.py. Open to better axis proposals."

### "Why neuro-symbolic in 2026?"

> "Same reason as in 2010 : LLMs hallucinate. The only way to keep
> agent verdicts trustworthy is to put deterministic logic in the
> judge path. The generation can be neural, but the verdict shouldn't
> be."

### "AGPLv3 is going to hurt adoption"

> "Yes. Deliberate trade-off. A SaaS Nokido would be self-contradictory
> — the whole point is sovereignty. AGPLv3 forces hosted variants to
> open-source their modifications. The cost is some commercial adopters
> won't touch it. The benefit is the community stays in control. I'll
> reconsider if/when the project ever has a real ecosystem."

## ⚠️ Pièges Lobsters

- Pas de marketing-speak ("solution", "platform", "ecosystem"). Préfère
  "implementation", "library", "tool".
- Pas d'emojis dans body. Le titre peut en avoir un, mais sobriété
  recommandée.
- Si tu poses une question (style "feedback wanted"), elle doit être
  spécifique — pas un "what do you think?" générique.
- Lobsters n'aime pas les self-promo trop fréquentes : 1 post / 2 mois
  max sur le même projet, sinon flag spam.
- **Pas de cross-post HN dans le body**. Lobsters et HN sont voisins
  mais distincts. Si quelqu'un pointe une discussion HN existante, OK
  pour link, mais tu ne le poses pas toi.
