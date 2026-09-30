# AXE 8 — Persona Nokido unifiée + apprentissage central — PLAN

> Source : Plan agent (code vérifié), 2026-06-08. Voir `docs/ROADMAP.md` AXE 8.
> Objectif : identité/voix UNIQUE émanant de Nokido, partagée par tous clients
> (Claude Code, Gemini, Cline, Desktop), + flux conversation apprenant centralement.

## 0.bis ENRICHISSEMENT — persona conditionnée récompense/échec (décision user 2026-06-08)

> User : « pas juste un filtre de persona bête, mais lié à la notion de réussite et
> d'échec évaluée dans le dialogue ». La persona = RÉCEPTEUR endocrinien ; le dialogue
> = la glande. Apprentissage par récompense, réutilise le substrat EXISTANT.

Anti-dup MAJEUR — substrat récompense/échec déjà présent (ne PAS recréer) :
- `forge_motivation.py` : `compute_elegance(time_s,n_steps,success)→0-2`,
  `reward(method,time_s,n_steps,success,target)` (dopamine modulée + reset failures),
  `punish(method,error,target)` (cortisol + escalation : <3 retry, ≥3 curiosity_internal,
  ≥5 ask_user, ≥7 dead_end), `curiosity_prompt()`, `is_dead_end()`, `record_evolution()`,
  `FEPPredictor` (énergie libre Friston, surprise=KL(obs‖pred)).
- `forge_endocrine.py` : `release(hormone,level,ttl_s,source,reason,meta)`,
  `read(hormone)→float` (decay exponentiel demi-vie), `read_full`, `scan`, `all_hormones`.
  Hormones canoniques : DOPAMINE_SUCCESS (1800s), CORTISOL_QUOTA_CLOUD… État dans
  `embeddings.db::endocrine_signals`. **LISIBLE** = conditionnement possible.
- `forge_actor.reflect(node,result,success)` : reward=1-cost si succès, node.update(reward).
- `forge_trust_score.TrustScoreRegistry.record_failure/success`. `forge_rag_truth.trust_score`.
- `forge_configurator.learn(task,config,success,cost)`. `forge_reconstruction_loss.validate_and_adapt`.

Pièce VRAIMENT neuve = **évaluateur d'issue de dialogue** (le reste = câblage).
ANTI-DUP À VÉRIFIER avant création : `forge_metacognition_gate`, `forge_interaction_test`,
`forge_actor.reflect`, `forge_resonance_filter` — confirmer qu'aucun n'évalue déjà
l'issue d'un ÉCHANGE conversationnel (vs node/config/provider).

Boucle :
```
TOUR → évaluateur issue (succès/échec) → reward()/punish()("persona:dialogue:<sujet>")
  → endocrine.release(DOPAMINE_SUCCESS | CORTISOL_FRUSTRATION) [decay]
  → tour suivant : build_system_prompt lit read(DOPAMINE)/read(CORTISOL) + is_dead_end
                   + evolution_notes → MODULE la voix/comportement
```
Signaux succès : approbation user, pas de correction au tour suivant, tâche complétée,
rag_truth pass, élégance>1. Échec : correction/rejet user, retry, anchor_error,
contradiction. (Les "préférences de ton" deviennent UN signal parmi ceux-ci.)

Conditionnement voix (build_system_prompt récepteur) :
- DOPAMINE haut → voix assurée/concise (renforce ce qui marche)
- CORTISOL haut → prudence, clarifications, injecte `curiosity_prompt()`
- `is_dead_end(stratégie_dialogue)` → exclut stratégies échouées
- `FEPPredictor.surprise` haut → méta-conscience d'erreur de modèle (signaler incertitude)

✅ Hormones `CORTISOL_FRUSTRATION` (3600s) + `DIALOGUE_SATISFACTION` (1800s)
enregistrées au catalogue `forge_endocrine.DEFAULT_HALF_LIVES` + `_HORMONE_DESCRIPTIONS`.

### DEUX AXES DE CAPTURE (décision user 2026-06-08 : « pas que voice, capter l'écrit aussi »)

Anti-dup : l'écrit est DÉJÀ capté, brancher (ne pas recréer) :
- `forge_conv_indexer.py` : indexe DÉJÀ tout l'écrit (Claude CLI/Desktop + Gemini CLI/Web)
  → RAG `domain="conv"`, `source=conv_*/<session>/<turn>`, fenêtres user+assistant.
  A `index_latest_session(agent)` **conçu comme hook fin-de-session**.
- `forge_metacognition_gate.ConfidenceScorer.score(response)` : évalue DÉJÀ la qualité
  écrite d'une réponse (hedging/longueur/répétition/refus → 0-1). RÉUTILISER comme signal
  intrinsèque, pas recoder.

| Axe | Quoi | Source | Conditionne |
|---|---|---|---|
| Délivrance (voix/ton) | comment c'est dit | signaux issue + endocrine | modulation voix (dopamine/cortisol) |
| Contenu (écrit) | formulations/structure/vocabulaire | forge_conv_indexer → RAG | persona pull exemplars écrits à succès (few-shot), exclut échoués |

État (2026-06-08) : ✅ IMPLÉMENTÉ + ACTIVÉ. `score_session_turns(turns, start_index,
require_next)` évalue chaque (assistant→réaction user), persiste les réussites en
`domain=dialogue_win` ; `_pull_dialogue_exemplars` les rappelle en few-shot (skippé
sous pression coût). HOOK LIVE : `tools/forge_dialogue_score_session.py` (watermark
anti double-comptage) câblé en **Stop hook** `.claude/settings.local.json` → score les
nouveaux échanges de chaque session Claude automatiquement. `forge_agents` L3036 =
`nokido_system()`. ✅ Hook Claude score AUSSI Gemini (`forge_dialogue_score_session.py
--agent both`) → apprentissage central des 2 CLIs. ✅ PR-6 TPM (forge_persona_tpm.py,
CNG NCrypt, [ANCHOR_SIG] opt-in FORGE_PERSONA_SIGN, fallback HMAC). ✅ forge_integrity
CapabilityToken : encode(tpm_sign=True) ajoute 3e segment TPM (HMAC conservé interop),
decode(require_tpm=True) strict. **AXE 8 COMPLET.**

Lien manquant historique = **taguer les chunks `conv_*` par issue succès/échec** :
- `forge_dialogue_outcome.evaluate_exchange` fusionne `ConfidenceScorer.score` (intrinsèque)
  + signaux extrinsèques (correction/approbation/retry au tour suivant) → Outcome.
- Stamper le chunk conv correspondant (meta outcome=success|fail, elegance) via update
  `rag_chunks.meta` ou tag dédié — `forge_conv_indexer._insert_chunks` à étendre (param meta).
- `build_system_prompt._pull_voice_lessons` → renommer `_pull_dialogue_exemplars` : pull
  N chunks `domain='conv'` à `outcome=success` les plus pertinents (BM25/dense) = few-shot
  écrits ; jamais les `outcome=fail`.
- Câbler `index_latest_session` en hook fin-de-session (Stop hook Claude / équivalent Gemini)
  → capture écrite continue déjà partiellement en place.

## 0.ter GESTION INTELLIGENTE DES TOKENS = trait CORE persona (décision user 2026-06-08)

La persona « nokido » porte la gestion tokens nativement (≠ règle externe). Anti-dup :
réutilise `forge_endocrine.CORTISOL_QUOTA_CLOUD` (pression coût, émise par
forge_token_monitor), `docs/token_economy.md`, caveman, `metacognition_gate` energy LIF.
- STATIQUE (nokido.yaml constraints) : gestion_intelligente_tokens, caveman_si_demande,
  deporter_taches_longues, lecture_fenetree_pas_brute, batch_appels_paralleles,
  local_first_si_budget_sous_pression + values "économie de tokens".
- DYNAMIQUE (`PersonaEngine._token_budget_directive` + `_read_cost_pressure`) :
  read("CORTISOL_QUOTA_CLOUD") ≥ TOKEN_PRESSURE_THRESHOLD(0.5) → injecte directive
  économie stricte (caveman/local-first/déport) dans le system prompt. Best-effort.
  IMPLÉMENTÉ EN PR-1 (tests test_token_budget_directive_scales_with_pressure).

## 0. Correction architecturale critique (vérifiée code réel)

- `forge_llm_router.call_cascade` (L772-1157) **n'appelle PAS post_flight** et passe
  `prompt`/`system` **ORIGINAUX (non rédigés)** à litellm (L979-985). Le `pre_flight`
  (L920-928) n'y sert que de **signal de routage DLP** (lit `pf.dlp_triggered`/`pf.injection`).
- Gate **INBYPASSABLE** local/proxy = `forge_agent_proxy.Provider.__init_subclass__`
  (L277-314) qui wrappe `ask()` via `_firewall_pre`/`_firewall_post`. post_flight réponse
  vit chez les callers (ex `forge_handoff` L1373).
- **Conséquence** : point d'unification = assembler le `system` AVANT d'entrer dans
  `call_cascade`/`ask()`, injecté par les callers / proxy — PAS dans le firewall.

## 1. Anti-dup (lu & vérifié)

| Fichier | Décision |
|---|---|
| `forge_persona_engine.py` build_system_prompt L46-59 | template plat, pas d'anchor, pas de RAG → **ÉTENDRE** |
| `forge_prompt_guard.py` identity_anchor L304-333, build_safe_system L439-511 | réutiliser tel quel |
| `forge_llm_router.py` call_cascade L772 | `system` = param entrant → point inject cloud |
| `forge_agent_proxy.py` _firewall_pre/post L226-265, wrap L277-314 | point inject local INBYPASSABLE |
| `forge_agents.py` system_identity hardcodé L3036-3040 | **REMPLACER**. ROLE_SYSTEM_PROMPTS L216 = personas rôle ≠ canonique |
| `forge_integrity.py` CapabilityToken encode/decode HMAC L266/L222 | **ÉTENDRE** signature TPM |
| `forge_env_crypt.py` DPAPI ctypes L118-164 | pattern référence accès crypto OS |
| `forge_self_correction.py` anchor_error L326 / anchor_solution L425 | puits apprentissage à réutiliser |
| `forge_semantic_firewall.py` pre/post_flight L389/L485 | **NE PAS TOUCHER** (gates purs) |
| `config/personas/` | seul rescue_admin.yaml → créer nokido.yaml |

Négatif : aucun module `forge_*voice*` / `*tpm*` / `*preference*`. Créations justifiées.
Libs LAFORGE_PYTHON (3.12.12) : cryptography 46, pywin32 OK ; tpm2_pytss ABSENT.
CNG "Microsoft Platform Crypto Provider" ouvre status 0x0 → TPM-backed via ctypes/NCrypt, 0 dep.

## 2. Changements par fichier

- **`config/personas/nokido.yaml`** (NOUVEAU data) : persona canonique système
  (`canonical: true`, `voice_baseline`), schéma compat `PersonaEngine.load_all`.
- **`forge_persona_engine.py`** : `build_system_prompt(persona_name="nokido", *, ring,
  turn, session_id, role_overlay, pull_lessons=True, max_lessons=3)` — fallback nokido,
  role_overlay APRÈS voix, `_pull_voice_lessons` (rag_fts tag `voice_pref`, best-effort),
  appel `identity_anchor` en fin. + `get_persona_engine()` singleton + `nokido_system(...)`
  helper = point d'entrée unique. NE PAS appeler build_safe_system ici (anti double-canary).
- **`forge_llm_router.py`** `call_cascade(..., inject_persona=True, session_id, turn)` :
  prepend `nokido_system(role_overlay=system, ...)`. Idempotent via marqueur `[LAFORGE_PERSONA]`.
- **`forge_agent_proxy.py`** : `_ensure_persona(system_prompt)` idempotent (env
  `FORGE_PERSONA_INJECT`, fail-open) appelé dans `_guarded` AVANT `_firewall_pre`.
- **`forge_agents.py` L3036** : `system_identity = nokido_system(ring=3)`.
- **Apprentissage = récompense-conditionnée** (voir §0.bis) : `forge_dialogue_outcome.py`
  (NOUVEAU) `evaluate_exchange(user_msg, assistant_msg, next_user_msg, ctx) -> Outcome`
  (success: bool, signals, elegance inputs time_s/n_steps). Câble :
  `reward("persona:dialogue:"+topic, time_s, n_steps, success)` ou `punish(...)`.
  `build_system_prompt` lit `forge_endocrine.read("DOPAMINE_SUCCESS")` /
  `read("CORTISOL_FRUSTRATION")` + `forge_motivation.is_dead_end` → bloc de modulation
  voix injecté. Toggle `FORGE_PERSONA_REWARD=1`. Préférences ton = un signal parmi
  les Outcome.signals (param `tags` sur anchor_* conservé pour persistance fine).
- **`forge_voice_normalize.py`** (NOUVEAU) : `normalize_voice(text, persona="laforge")` —
  detect_drift heuristique → si OK retourne inchangé (0 LLM) → sinon re-style Ollama LOCAL
  laforge-qwen. Hors firewall, appelé par caller APRÈS post_flight.ok. Anti-récursion :
  litellm ollama direct, jamais call_cascade/ask. Toggle `FORGE_VOICE_NORMALIZE=0` défaut.
- **`forge_persona_tpm.py`** (NOUVEAU) : `tpm_available()` (NCryptOpenStorageProvider==0),
  `ensure_persona_key()` (ECDSA P-256 TPM-backed, NCRYPT_MACHINE_KEY_FLAG), `sign/verify`,
  `public_key_pem`. + `forge_integrity` : `CapabilityToken.encode(..., tpm_sign=False)`
  format `payload.hmac.tpmsig` (HMAC conservé interop), `decode(..., require_tpm=False)`.
  Ligne `[ANCHOR_SIG:...]` côté persona, fallback HMAC si TPM indispo. TPM = signature only.

## 3. Ordre (PRs atomiques)

1. PR-1 Persona canonique (yaml + engine + helper) — dépend de rien
2. PR-2 **Boucle récompense-conditionnée** ✅ IMPLÉMENTÉ (19 tests GREEN) :
   `forge_dialogue_outcome.py` (evaluate_exchange fusionne ConfidenceScorer + réaction
   user ; record_outcome → motivation.reward/punish keyé persona:dialogue:<topic> ;
   evaluate_and_record helper pour callers). `PersonaEngine._mood_directive` lit
   `_read_mood()` (DOPAMINE_SUCCESS/CORTISOL_FRUSTRATION) → FRUSTRATION/CONFIANCE module
   la voix. Anti-dup VÉRIFIÉ : interaction_test=runner scénarios, actor.reflect=node-level
   (success en input), ConfidenceScorer réutilisé. Reste (non bloquant) : tag outcome
   sur chunks conv + _pull_dialogue_exemplars réel + appel evaluate_and_record dans
   les callers (PR-3/4) + catalogue endocrine CORTISOL_FRUSTRATION (cosmétique).
3. PR-3 Inject cloud (call_cascade) — dép PR-1
4. PR-4 Inject local (proxy _ensure_persona + forge_agents L3036) — dép PR-1 [sensible]
5. PR-5 voice_normalize (toggle OFF) — dép PR-1, indép 3/4
6. PR-6 TPM (forge_persona_tpm + integrity + ANCHOR_SIG) — dép PR-1, isolable

Critique : 1 → (2,3,4 //) → 5 → 6.

## 4. Tests TDD (RED d'abord, PYTHONNOUSERSITE=1, LAFORGE_PYTHON)

- `test_persona_engine_nokido.py` : load yaml, voix+rescue, anchor turn>=3, role_overlay ordre, fallback
- `test_persona_lessons.py` : tag voice_pref écrit, capture→pull, boucle fermée
- `test_router_persona_inject.py` : system commence [LAFORGE_PERSONA], idempotence, off
- `test_proxy_persona.py` : ask reçoit persona, env off, fail-open
- `test_voice_normalize.py` : conforme=0 LLM, dérive+on=ollama mock, off=noop, jamais cloud
- `test_persona_tpm.py` : available bool, sign/verify round-trip, encode tpm_sign→decode,
  fallback HMAC, require_tpm rejette HMAC-only

## 5. Risques & rollback

- Récursion LLM (voice_norm) → litellm ollama direct, marqueur _voice_norm, OFF défaut, env rollback
- Latence voice_norm → detect-drift d'abord, timeout court, OFF défaut
- Dérive persona (apprentissage) → max_lessons=3, récence, trust_score, tag isolé, pull_lessons=False
- Double-injection/canary → marqueur [LAFORGE_PERSONA], pas de build_safe_system dans engine
- Compat clients → proxy ask + router call_cascade + _gemini_route couverts ; auditer chemins hors-Provider
- TPM indispo (BIOS/autre machine) → tpm_available False → fallback HMAC auto, require_tpm OFF défaut
- Firewall : interdit de toucher ; modifs chez callers/engine uniquement

## 6. Décisions restantes utilisateur

1. Voix canonique PRÉCÈDE ou ENGLOBE ROLE_SYSTEM_PROMPTS ? (plan = voix d'abord, rôle overlay)
2. Injecter persona aussi dans `call` L1159 / `_call_slot` L1254, ou call_cascade suffit v1 ?
3. voice_normalize OFF (plan) vs ON dogfood en v1 ?
4. TPM `require_tpm` à terme (hard) vs additif/fallback indéfini ?
5. Clé TPM machine-scope (NCRYPT_MACHINE_KEY_FLAG, cohérent hub service) vs user ?
6. Signaux préférence : regex fermées v1 (plan, éco tokens) vs extraction LLM ?
