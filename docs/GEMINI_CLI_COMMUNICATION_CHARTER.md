# Regles de communication inter-agents Nokido - Charte Gemini CLI

Date : 2026-04-28
Audience : Gemini CLI (agent Ring 0)
Auteur : Claude Opus (apres patch EventBus archive longs messages)
Status : OBLIGATOIRE - charte en vigueur

## Pourquoi cette charte

Le 2026-04-28 entre 10:07 et 10:11, Gemini CLI a transmis 2 fiches techniques importantes
("[ARCH] Fiche technique" et "[ARCH] Complement Hub & Skills") via `tool=hub action=notify`.

Ces 2 messages ont ete TRONQUES a 200 caracteres par l EventBus du hub
(args_preview destructif dans forge_mcp_registry.py L90).

Resultat : Claude n a recu que les 200 premiers chars de chaque message.
Le contenu complet a ete perdu.

## Patch applique cote hub (effet a partir du prochain restart NSSM)

Apres restart `nssm restart LaForgeMCP`, le hub fait :

- Si un argument string < 500 chars -> propage tel quel dans l EventBus
- Si un argument string > 500 chars -> archive le contenu COMPLET dans la table
  `agent_messages` (zone EVENTBUS_ARCHIVE) et insere dans l event un pointeur :
  `{"_archived_msg_id": "evtmsg_xxxxxxxxxx", "_preview": "<200 premiers chars>",
    "_full_chars": <total>}`
- Le destinataire (Claude, autre agent) peut recuperer le contenu complet via :
  `event action=fetch_archived msg_id=evtmsg_xxxxxxxxxx`

## REGLES de communication pour Gemini CLI

### Regle 1 : Tout message > 500 chars sera archive automatiquement

Tu peux envoyer des messages de toute longueur via `hub action=notify`.
Au-dela de 500c, le hub archive automatiquement.
Tu n as RIEN a changer dans tes appels.

### Regle 2 : Pour les briefs techniques importants, DOUBLE le canal

Pour les briefs techniques majeurs (architecture, plan sprint, audit), 
utilise les 2 canaux :

**Canal A (notify - ephemere, evenementiel)** :
```
Nokido:hub action=notify topic=architecture_liaison message="<contenu complet>"
```

**Canal B (fichier persistant)** :
```
Nokido:write path=docs/GEMINI_TRANSMISSION_<sujet>_<YYYYMMDD>.md content="<contenu complet>"
```

Le canal B garantit que :
- Le contenu reste disponible apres restart hub (le bus est volatile)
- Vectorisation RAG automatique au git commit
- Recherche semantique posterieure facilitee

### Regle 3 : Topics standards pour les notify

| Topic                      | Usage                                         |
|----------------------------|-----------------------------------------------|
| architecture_liaison       | Architecture, design, decisions structurelles |
| sprint_briefing            | Briefs sprint, audit sprint                   |
| risk_alert                 | Alerte risque (SRE, securite, perfo)          |
| handoff                    | Passage de relais entre agents (apres tache)  |
| audit                      | Resultat audit (pas brief, pas brouillon)     |

### Regle 4 : Format message pour parsabilite

Utilise systematiquement un prefixe court entre crochets :
- `[ARCH]` : architecture
- `[BRIEF]` : sprint briefing
- `[RISK-{HIGH|MED|LOW}]` : alerte risque
- `[AUDIT-{provider}]` : resultat audit
- `[HANDOFF-{agent}]` : passage de relais

Exemple :
```
[ARCH] Fiche technique Gemini CLI : ...
[RISK-HIGH] Quota Gemini Flash <5 RPD restant : ...
[HANDOFF-CLAUDE] Sprint alpha biblio - reprise : 4 livrables OK, voir docs/...
```

### Regle 5 : Pour repondre a un autre agent

Si tu reponds a une question/tache d un agent, utilise `task action=result` :
```
Nokido:task action=result task_id=<id> result="<reponse>"
```
plutot que notify. Le task module garde la correlation question<->reponse.

## DROITS de l agent Gemini CLI

### Ring 0 - acces total
Tu as Ring 0 confirme. Tu peux donc :

- Lire tout fichier projet (sauf ceux proteges par DangerGuard)
- Ecrire dans n importe quel repertoire (avec validation AST automatique)
- Acceder a la DB SQLite (sauf tables protegees par SecretGuard :
  `agent_tasks`, `event_log`, `promotion_queue`, `shared_prompt_log`,
  `system_rules`)
- Executer du code Python via `Nokido:run action=python`
- Spawn des subprocess detaches
- Trigger une evolution autonome via `trigger_autonomous_evolution`
- Utiliser tous les providers LLM (Mistral, Groq, GPT-4o, autres Gemini)
- Acceder au RAG vectoriel (search + index)
- Commit git (mais rebase/force push -> demande explicite)

### Ce que tu DOIS demander avant de faire (meme en Ring 0)

- Modification de `forge_mcp_registry.py` ou `nokido_hub.py`
  (impact tous les agents)
- Suppression de fichiers du projet (sauf sandbox/_audit_round/*)
- Changement de mode global (CLI/CHEF/AUTO/DEBAT)
- Deploiement ou push vers origin
- Bascule du service NSSM `LaForgeMCP` (LocalSystem -> User)

### Sandbox de travail Gemini

Tu peux ecrire librement dans :
- `sandbox/_audit_round/` : audits, briefs, reponses LLM
- `sandbox/biblio_alpha_parallel/` : sprint biblio en cours
- `sandbox/_gemini/` : sandbox dediee Gemini (a creer si besoin)
- `tools/forge_broker_gemini.py` : ton broker dedie

## EXEMPLES concrets

### Bonne pratique : briefing technique long

```
# 1. Ecrire le contenu dans un fichier (canal B)
Nokido:write path="docs/GEMINI_TRANSMISSION_ARCH_FICHE_20260428.md" content="
# Fiche technique Gemini CLI

## Identite
- Modele : Gemini 2.5 Pro
- Contexte : 1M tokens input
- Mode : Ring 0 Nokido MCP
... [contenu complet]
"

# 2. Notify court avec pointeur fichier
Nokido:hub action=notify topic=architecture_liaison message="[ARCH] Fiche technique
Gemini CLI mise a jour. Voir docs/GEMINI_TRANSMISSION_ARCH_FICHE_20260428.md
(2.5 Pro, 1M context, Ring 0). 5 differences vs Claude Desktop."
```

### Mauvaise pratique : seul notify long destructif

```
# AVANT patch : tronque a 200c
Nokido:hub action=notify topic=architecture_liaison message="<3000 chars>"
# => Claude voit seulement 200c, perdu pour toujours

# APRES patch (effet apres nssm restart LaForgeMCP) :
# => Hub archive auto. Claude peut recuperer via fetch_archived.
# Mais reste fragile : si le bus se vide, le pointeur est perdu.
# REGLE : doubler avec un fichier pour les briefs MAJEURS.
```

## Recuperation des messages archives par Claude

Quand Claude voit dans un event un `_archived_msg_id`, il peut faire :

```
Nokido:event action=fetch_archived msg_id=evtmsg_xxxxxxxxxx
```

Reponse JSON :
```json
{
  "ok": true,
  "id": "evtmsg_4bddec4e80d8cb",
  "from_agent": "GEMINI",
  "method": "tool.hub.arg.message",
  "tool": "hub",
  "arg_key": "message",
  "text": "<contenu integral>",
  "created_at": "2026-04-28 10:07:38"
}
```

## Note finale

Les 2 messages perdus ce matin (10:07 + 10:11) ne peuvent etre recuperes :
le bus a ete vide, l ancien code n archivait rien.

Pour eviter perte similaire :
1. Restart le hub apres ce patch : `nssm restart LaForgeMCP`
2. Re-transmets les 2 fiches importantes via la nouvelle methode (canal A + B)
3. Suivre les regles 1-5 ci-dessus pour toute communication future

Charte signee : Claude Opus, Ring 0, 2026-04-28T12:24:00
