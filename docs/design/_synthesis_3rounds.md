# Audit triangulation 3 rounds — synthese

Date : 2026-04-27 ~20:30 UTC
Modeles : Gemini 2.5 Flash Lite, Kimi K2 Thinking (OpenRouter), GPT-4o (GitHub Models)
Methode : 3 rounds independants en parallele puis agregation. Pas de "qui a raison"
posee aux modeles (correction du biais B4 identifie en R3).

================================================================================
ROUND 1 — Optimisation outils par chemin
================================================================================

CONVERGENCES
  Q1 Sentinel : 3/3 disent COTE HUB UNIQUEMENT
                Le bridge ne doit etre que transport.
                Action : retirer le _SENTINEL_TOOLS check du bridge.
  Q3 Metriques : 3/3 disent OPENTELEMETRY + corr_id par etape
                 (transport / parse / dispatch / tool / serialize / response)

DIVERGENCES
  Q2 Architecture cible :
    Kimi   : 2 chemins, TUER stdio bridge (anti-pattern fossilise)
    Gemini : 2 chemins, fusionner stdio dans hub (composant interne) + HTTP secondaire
    GPT-4o : 3 chemins rationalises (chacun son cas d'usage)

ANALYSE
  Diviser stdio = breaking change Claude Desktop. Kimi tres tranchant
  mais ignore que Claude Desktop NE PARLE QUE STDIO. Sa solution
  "Claude Desktop doit parler HTTP" suppose que MCP a un transport
  HTTP standardise pour clients GUI -- ce qui n'existe pas (Claude
  Desktop suit la spec MCP qui prescrit stdio + Streamable HTTP +
  notifications/message en push).
  
  Gemini propose un compromis viable : alleger le bridge (drop sentinel,
  drop rate_limit) pour le rendre transparent pur, sans le supprimer.
  
  GPT-4o a le diagnostic le plus pragmatique : 3 chemins legitimes,
  juste mal documentes / mal segmentes.

DECISION RETENUE
  - Bridge stdio reste (Claude Desktop a besoin) MAIS allege :
    * supprime _SENTINEL_TOOLS check (deplace au hub)
    * supprime _RateLimiter (le hub a deja un)
    * garde JSON-RPC validation (defense en profondeur legitime)
  - HTTP /mcp reste pour clients programmatic (mcp_lab Phase 1)
  - Import direct forge_agent_proxy reste pour scripts internes
  - Instrumentation : ajouter span timing par etape avec corr_id
    (sans depend OpenTelemetry pour eviter nouvelle dep)

================================================================================
ROUND 2 — Completion + Logging MCP officiels (spec 2025-11-25)
================================================================================

CONVERGENCES
  completion/complete : 3/3 disent NON
                       Nokido n'a ni prompts ni resources MCP standards.
                       Implementer = etendre la spec en non-standard.
                       Decision : NE PAS implementer.
  
  notifications/message : 2/3 disent OUI partiellement (Kimi + GPT-4o)
                          Comme PUSH des events EventBus vers clients MCP.
                          Complement (pas remplacement) du Phase 3 tap.

DIVERGENCES
  logging/setLevel scope :
    Kimi   : Controle TOUT le logging serveur (risque mute production)
    Gemini : Controle TOUT, "risque reel", a manier avec soin
    GPT-4o : Limite a notifications/message uniquement (pas mcp_audit.log)
  
  Lecture spec : la spec dit "notifications/message" specifiquement.
  GPT-4o probablement correct sur le scope. Kimi/Gemini font une
  hypothese conservatrice.

DECISION RETENUE
  - completion/complete : SKIP. Hors scope Nokido actuel.
  - notifications/message : implementer comme pont EventBus -> client MCP
    (Phase 3 stream live). Permet a un client MCP standard (Inspector,
    Claude Desktop, mcp_lab) de recevoir les events sans poll.
  - logging/setLevel : implementer mais SCOPE LIMITE aux notifications/message
    (suit la spec stricte). Le mcp_audit.log reste insensible.
  - Capability declaree : ajouter 'logging': {} (pas 'completions').

================================================================================
ROUND 3 — Mes points bloquants honnetes (Claude self-audit)
================================================================================

CONVERGENCES Gemini + GPT-4o (Kimi indispo solde)

  B1 buffer 4000 chars  ANTI-PATTERN. Estimateur taille avant write obligatoire.
                        Blind-spot : "raisonnable" est subjectif, structure cache longueur.
  
  B2 memoire incoherente ANTI-PATTERN. Verification empirique systematique.
                          Blind-spot : confiance excessive en memoire conversationnelle
                          presentee comme acquise.
  
  B3 prompts tronques    LEGITIME (limitation tech) MAIS diagnostic insuffisant.
                          Manque investigation prompt vs bridge.
  
  B4 biais triangulation ANTI-PATTERN. Demander "qui a raison" force comparaison biaisee.
                          Action : meme question independamment, comparer apres.
                          Applique en R1+R2+R3 cette fois (lance les 3 en parallele).
  
  B5 prudence -> paralysie ANTI-PATTERN. Confondre prudence et perfectionnisme.
                            Blind-spot : peur implicite de l'erreur ou du conflit.
  
  B6 audit -> procrastination ANTI-PATTERN. Audit = excuse pour ne pas decider.
                              Action : 10% temps max sur audit, puis execution.

3 CONSEILS GENERAUX (synthese Gemini + GPT-4o)
  1. Action prime sur analyse infinie. Critere de succes mesurable, livrable concret.
  2. Verifier systematiquement, pas presumer. Memoire = aide, pas verite absolue.
  3. Respecter les regles explicites du projet. Ignorer "CHUNK WRITING < 50 lignes"
     n'est pas optimisation, c'est indiscipline.

================================================================================
ACTIONS IMMEDIATES (auto-correction Claude)
================================================================================

Trois corrections pour cette session :

1. PUIS PASSER A L'EXECUTION CODE
   Apres cette synthese, j'enchaine direct sur Phase 3 implementation
   sans nouvelle consultation de modele. Cap temps : 30 min audit total.

2. ESTIMATEUR DE TAILLE AVANT WRITE
   Avant chaque Nokido:write, verifier len(content) > 4000 -> chunker.
   Si > 50 lignes, refuser et passer en append python.

3. VERIFIER ASSERTIONS MEMOIRE
   Quand je dis "selon transfer.txt session N" ou "le commit X a fait Y",
   je verifie git log/show ou re-lis le fichier AVANT d'affirmer.

================================================================================
PLAN PHASE 3 RAFFINE
================================================================================

3a (hub side) : 
  - hook payload sur Hub._tool_call (3 topics : tool.payload.in/out/error)
  - publish via notifications/message MCP standard (au lieu de juste EventBus)
    -> compatible Inspector officiel + tap mcp_lab
  - capability 'logging': {} declaree
  - logging/setLevel implemente avec scope limite notifications uniquement

3b (mcp_lab side) :
  - /api/tap SSE multi-source : tail audit log + tail bridge log + EventBus history
    + abonnement notifications/message via long-polling sur /mcp
  - Frontend : 1 page HTML, vanilla JS, 3 colonnes (HTTP/Bridge/Events)

3c (cleanup) :
  - retirer _SENTINEL_TOOLS check du bridge (deplace au hub uniquement)
  - retirer _RateLimiter du bridge (le hub a deja un)
  - bridge devient transport pur (-150 lignes)

3d (instrumentation) :
  - corr_id span par etape dans hub (transport, parse, dispatch, tool, response)
  - latence p50/p95/p99 par tool exposees sur GET /api/metrics

================================================================================
SAUVEGARDES SESSION
================================================================================
sandbox/backups/
  bridge-20260427-164932/    bridge stdio
  docs-20260427-181844/      transfer + map
  inspector-phase1-20260427-193130/  app.py avant Phase 1
  hub-phase3a-20260427-195013/       hub avant Phase 3a

sandbox/_audit_round/  3 rounds bruts (r1/r2/r3 par modele)
sandbox/_audit_startup_synthesis.md  cause 0x90 + plan stabilite
sandbox/_self_audit_claude.md        mes blocages soumis aux modeles
sandbox/bridge_repair_plan.md        plan repair bridge

================================================================================
GO/NO-GO
================================================================================

GO Phase 3 implementation immediate.
   Pas de nouvelle consultation modele avant 30 min de code.
   Audit termine. Action commence.
