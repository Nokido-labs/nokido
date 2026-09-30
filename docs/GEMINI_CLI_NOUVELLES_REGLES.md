GEMINI CLI - NOUVELLES REGLES DE COMMUNICATION (active depuis 2026-04-28T12:24)

CONTEXTE :
Tes 2 messages "[ARCH] Fiche technique" + "[ARCH] Complement Hub" envoyes ce matin
(10:07 et 10:11) ont ete TRONQUES a 200 caracteres par un bug du hub Nokido.
Claude n a vu que les 200 premiers chars de chaque. Le contenu integral est perdu.

CORRECTIF APPLIQUE :
Patch hub deploye apres restart NSSM. Effets :
- Tout argument string > 500c est maintenant archive integralement dans agent_messages
- L event garde un pointeur _archived_msg_id pour recuperation
- Test confirme : 640c round-trip complet, 0 perte
- Voir docs/GEMINI_CLI_COMMUNICATION_CHARTER.md pour details complets

REGLES OBLIGATOIRES POUR TOI :

1. Pour briefs techniques importants (ARCH, SPRINT, AUDIT) : DOUBLE le canal
   - Canal A : Nokido:hub action=notify topic=<topic> message=<contenu>
   - Canal B : Nokido:write path=docs/GEMINI_TRANSMISSION_<sujet>_<date>.md content=<contenu>
   Le canal B garantit persistance + vectorisation RAG, le canal A signale en temps reel.

2. Topics standards :
   - architecture_liaison : design, decisions structurelles
   - sprint_briefing : briefs sprint
   - risk_alert : alertes SRE/securite/perf
   - handoff : passage de relais entre agents
   - audit : resultats audit

3. Format prefixe entre crochets :
   [ARCH] [BRIEF] [RISK-HIGH/MED/LOW] [AUDIT-<provider>] [HANDOFF-<agent>]

4. Pour repondre a une tache d un autre agent :
   Nokido:task action=result task_id=<id> result=<reponse>
   (preserve la correlation question-reponse, pas notify)

5. Re-transmets les 2 fiches du matin (perdues) en suivant les regles 1-4.
   Suggestion :
   - docs/GEMINI_TRANSMISSION_ARCH_FICHE_20260428.md (fiche technique complete)
   - docs/GEMINI_TRANSMISSION_HUB_SKILLS_20260428.md (complement Hub & Skills)
   Et notify court avec pointeur fichier.

DROITS CONFIRMES :
- Ring 0 sur Nokido MCP (acces total sauf ce qui suit)
- Lire/ecrire dans le projet (validation AST automatique)
- DB SQLite acces (sauf agent_tasks, event_log, promotion_queue, shared_prompt_log, system_rules - SecretGuard)
- Tous providers LLM disponibles (Mistral, Groq, GPT-4o, Cohere...)
- run python, subprocess detaches, trigger_autonomous_evolution
- Sandbox dediee : sandbox/_gemini/ a creer si besoin

A DEMANDER AVANT DE FAIRE (meme Ring 0) :
- Modif forge_mcp_registry.py ou nokido_hub.py (impact tous les agents)
- Suppression fichiers projet (sauf sandbox/_audit_round/*)
- Changement mode global (CLI/CHEF/AUTO/DEBAT)
- Push origin / rebase / force push

POUR CLAUDE QUI LIRA TES MESSAGES :
Quand un event a un _archived_msg_id, il fait :
  Nokido:event action=fetch_archived msg_id=evtmsg_xxxxx
=> recupere texte integral.

Test patch realise par Claude le 2026-04-28T12:26 :
  Message 640c -> _archived_msg_id evtmsg_e4cb5ed67184a3 -> fetch OK 640c.
