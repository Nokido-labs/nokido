# Audit analogie corps — 2026-10-27 (partiel)

Perimetre : MANIFESTO.md et docs/ARCHITECTURE.md contre le code de ce worktree.
Limites : l'executeur n'autorise ni grep generique ni lecture de %NOKIDO_DATA%\embeddings.db. Le census `sandbox/workspace/organ_map_full.json` a ete lu sur ses 60 premieres lignes seulement (organe « Memoire (hippocampe/RAG) »). Les logs d'organes n'ont pas ete lus sauf un. Tout ce qui n'a pas ete lu est ILLISIBLE, pas NON. Les chiffres RAG du manifeste (2 179 864 fragments, etc.) n'ont pas ete remesures.

| organe | affirmation | module | preuve | verdict |
|---|---|---|---|---|
| Memoire / autopoiese | Le drain d'embedding s'abstient au-dessus de 85 % de RAM et reprend sous 75 % (MANIFESTO 2.1) | tools/forge_embed_auto_trigger.py (census : Memoire hippocampe/RAG) | tools/forge_embed_auto_trigger.py:43-51 (RAM_PAUSE, RAM_REPRISE = 85.0, 75.0, valeurs de forge_physiology, repli 85/75) | PROUVE (code) |
| Memoire / autopoiese | Le drain tourne et regenere les vecteurs | idem | logs/embed_auto_trigger.out.log : 1 seule ligne, « started — ZMQ tcp://localhost:5557 ». docs/ARCHITECTURE.md:6-8 dit que brain_worker :5557 est DESACTIVE. Le drain pointe donc vers un port declare desactive. | ILLISIBLE (log sans activite ; non conclusif en l'etat, a recouper avec le port reel et la date du log) |
| Systeme immunitaire | SemanticFirewall : pre_flight puis post_flight (MANIFESTO 3.1) | app/forge_semantic_firewall.py | :667 pre_flight, :845 post_flight | PROUVE (existence) ; execution ILLISIBLE |
| Systeme immunitaire | SovereignMembrane : alias HMAC par mission | app/forge_sovereign_membrane.py | fichier present ; contenu non lu | ILLISIBLE |
| Cyber-defense / energie libre | forge_active_inference_agent calcule la KL prior->posterior via pymdp (2.2) | app/forge_active_inference_agent.py | :3 et :27 (import pymdp, garde _PYMDP_OK), :84-95 KL calculee a la main avec numpy | PROUVE (la KL existe) ; ECART mineur : pymdp est optionnel (_PYMDP_OK), la formule est numpy |
| Jugement neuro-symbolique | forge_scorecard a 6 axes deterministes, zero LLM (2.3, 3.4) | app/forge_scorecard.py | :327 _mccabe_complexity ; :437 ponderation pylint E/F ; :354 reference a "forge_llm_router" (contexte non lu) | PROUVE pour AST/pylint/McCabe ; absence totale de LLM ILLISIBLE (ligne 354 a lire) |
| Planification AMI | forge_ami_strategist + 16 modules AMI (2.4) | tools/forge_ami_strategist.py | fichier present ; le compte de 16 modules n'a pas ete verifie | PROUVE (existence) ; reste ILLISIBLE |
| Boucles daemon | forge_auto_evolution_loop et forge_auto_compact tournent 24/24 (3.5) | tools/forge_auto_evolution_loop.py, tools/forge_auto_compact.py | fichiers presents. Aucun log lu. Le manifeste dit « NSSM/systemd » alors que le superviseur :8765 a remplace NSSM le 24/05 (description de l'outil manage_forge_lifecycle) | ECART (vocabulaire NSSM obsolete) ; « 24/24 » ILLISIBLE |
| Politique de tier | forge_tier_guard ecarte 628 375 fragments (3.3) | introuvable sous ce nom : seuls tools/forge_tier_guard_install.py et tools/forge_tier_policy.py existent (census : forge_tier_policy dans Memoire) | Get-ChildItem -Recurse sur forge_tier* | ECART (le nom cite n'existe pas) ; chiffre ILLISIBLE |
| Routeur LLM | forge_llm_router : cascade qui retombe sur le local (3.2) | app/forge_llm_router.py | fichier present ; cascade non lue | ILLISIBLE |
| Hub / orchestration | ARCHITECTURE.md : hub :8766, bus Deno :7401, llama.cpp :8099 | n/a | ports non verifies | ILLISIBLE |
| Hippocampe | ARCHITECTURE.md:19 : « 535k chunks » | RAG | MANIFESTO 3.3 annonce 2 179 864 fragments. ARCHITECTURE.md:6-8 se declare « INDICATIF ». | ECART interne entre les deux documents (aucun des deux n'est remesure) |
| Coagulation | Le cycle de coagulation ne se relance pas sur un signal qu'il a lui-meme provoque (cas d'ecole 20/10) | tools/forge_coagulation.py ; app/forge_remediation.py ; app/forge_coagulation_cascade.py | forge_remediation.py:81 emet embed_consolidation_debt, :201 oauth_cli_atrophy ; forge_coagulation.py:67 _REMEDIABLE = ("embed", ... ) et :87 test `any(s in blob for s in _REMEDIABLE)` | ECART PROUVE par le code : « embed » est remediable, et un signal embed_consolidation_debt le contient. Aucun inhibiteur ni periode refractaire n'a ete vu sur ces lignes. Le cycle de 260 s et la periodicite de ~5 min ne sont pas remesures ici. Le triage complet n'a pas ete lu. |

## Ecarts priorises (propositions, a valider par l'owner)

1. Boucle signal -> remede -> signal sur la coagulation (forge_coagulation.py:67/:87 contre forge_remediation.py:81/:201). Absence de retroaction negative. Priorite haute.
2. Drain d'embedding : log quasi vide et port ZMQ :5557 declare desactive. A tirer au clair avant de soutenir « regeneration reelle ».
3. Manifeste : forge_tier_guard n'existe pas sous ce nom, NSSM est obsolete, les comptes RAG divergent entre les deux documents.

## Non fait

Le reste du census n'a pas ete mis en regard. Le manifeste a ete lu jusqu'a la ligne 150 seulement. docs/i18n et la skill forge-anatomy n'ont pas ete lus. Le corpus de physiologie (OpenStax) n'a pas ete traite. Un second passage est necessaire pour couvrir ces points.
