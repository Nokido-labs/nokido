# Audit & Proposition RED — Identité prouvée du CLI pilote pour demandes admin
**Référence Blackboard :** `P1_demandes_admin_par_le_cli_pilote_20261017`  
**Date :** 2026-10-19  
**Statut :** Lecture seule (aucun code modifié, aucun outil d'exécution lancé)

---

## 1. Vérification du jeton porteur & identité prouvée (Q1)

### 1.1 Code vérifiant le jeton porteur à l'arrivée MCP (:8766)
- **CapabilityToken (AppRole / TPM)** :
  - `tools/nokido_hub.py:1160-1184` (`_resolve_ring`) : Décode et valide cryptographiquement le jeton via `forge_integrity.CapabilityToken.decode(token, mgr._secret)`. Le champ `cap_token.sub` porte l'identité prouvée de l'agent.
- **Jeton porteur agent (Bearer `FORGE_TOKEN_<agent>`)** :
  - `tools/nokido_hub.py:885-921` (`_load_agent_tokens`) : Charge les jetons valides depuis DPAPI / variables d'environnement (`_AGENT_TOKENS`).
  - `tools/nokido_hub.py:1206-1212` (`_resolve_ring`) : Compare en temps constant (`hmac.compare_digest`) le jeton porteur contre les jetons agents ou `HUB_TOKEN`.
- **Moteur de résolution d'identité (Videur)** :
  - `app/forge_videur.py:354-570` (`resolve_identity`) :
    - `app/forge_videur.py:369-379` : Résolution directe par jeton d'agent (`via="token"`).
    - `app/forge_videur.py:381-390` : Résolution inverse par table de hachage de jeton (`via="reverse_token"`).
    - `app/forge_videur.py:534` : Calcule `sujet_prouve = via in _VIA_PROUVES`, où `_VIA_PROUVES = frozenset({"token", "reverse_token", "capability_token"})` (`app/forge_videur.py:253`).

### 1.2 Ce que le hub sait de l'identité prouvée
`resolve_identity` produit un dictionnaire d'audit complet contenant :
- `agent` : Nom canonique de l'identité résolue.
- `ring` : Niveau de privilège (0 à 4).
- `via` : Vecteur d'authentification (`"token"`, `"reverse_token"`, `"capability_token"`).
- `sujet_prouve` : `True` si l'identité est garantie par signature/secret, `False` si déclarative.
- `token_h` : Empreinte SHA-256 tronquée du jeton.

### 1.3 Accessibilité au handler de `hub action=demander_ordre` / `redemarrer_stack`
**NON ACCESSIBLE** (Rupture complète de la chaîne de confiance) :
1. `tools/nokido_hub.py:1243` : `_resolve_ring` ne retourne qu'un tuple `(ring, agent)`.
2. `tools/nokido_hub.py:3144-3145` (`mcp_post`) : Lit `agent_hdr = self.headers.get("X-Agent-Name", "").strip()` (en-tête client arbitraire et falsifiable).
3. `tools/nokido_hub.py:3371, 3413` : Transmet `agent=agent_hdr` à `_tool_call`.
4. `tools/nokido_hub.py:1434` : Transmet `agent` non vérifié à `get_registry().dispatch`.
5. `app/forge_mcp_registry.py:6678, 6680` (`handle_hub`) : Propage `agent` comme argument `demandeur` vers `_ob.redemarrer_stack(demandeur=agent)` et `_ob.demander_ordre(demandeur=agent, ...)`.
6. `app/forge_ordres_bureau.py:260` et `app/forge_ordres_bureau.py:341` : Les fonctions ne reçoivent qu'une chaîne `demandeur: str` sans aucun booléen ni objet de preuve (`demandeur_prouve` est absent).

---

## 2. Identités CLI session humaine vs exécuteurs autonomes (Q2)

Dans `config/agent_identities.json`, la distinction est explicitement portée par les champs suivants :

### 2.1 Champ `surface`
- `"interactive"` : Session humaine / CLI interactif piloté par un opérateur :
  - `CLAUDE` (`config/agent_identities.json:47`)
  - `AGY` (`config/agent_identities.json:112`)
  - `ANTIGRAVITY` (`config/agent_identities.json:257`)
  - `CODEX` (`config/agent_identities.json:375`)
  - `COPILOT` (`config/agent_identities.json:317`)
  - `LAFORGE_CLI` (`config/agent_identities.json:13`)
- `"autonomous"` : Exécuteurs sans session humaine interactive directe :
  - `AGY_HEADLESS` (`config/agent_identities.json:135`)
  - `AGY_DAEMON` (`config/agent_identities.json:157`)
- `"internal"` : Services d'infrastructure / hooks :
  - `CLAUDE_HOOK` (`config/agent_identities.json:62`)
  - `TRAY` (`config/agent_identities.json:411`)
  - `SERVICES` (`config/agent_identities.json:426`)

### 2.2 Champs complémentaires `kind` et `mode`
- `kind` : `"cli_agent"` (`config/agent_identities.json:45, 110, 255, 373`) vs `"daemon"` (`:133, 155`), `"service"`, `"hook"`.
- `mode` : `"interactive"` (`config/agent_identities.json:3, 86, 183, 213`) vs `"autonomous"` (`:117, 140`).

### 2.3 Fonction SSoT existante
- `app/forge_videur.py:205-217` (`cli_agents()`) : Retourne la liste des agents dont `kind == "cli_agent"`. Pour qualifier le CLI interactif, la condition SSoT est `surface == "interactive"`.

---

## 3. Proposition minimale & Spécification du RED (Q3)

### 3.1 Point d'insertion de la décision
1. **Passage de la preuve au handler** :
   - Dans `tools/nokido_hub.py:3144` : Si `sujet_prouve` est vrai (résolu depuis le jeton porteur), l'identité transmise doit être l'identité prouvée, accompagnée d'un attribut de contexte ou paramètre `demandeur_prouve: bool = True`.
   - Dans `app/forge_mcp_registry.py:6678, 6680` : Transmettre `demandeur_prouve=True` à `_ob.demander_ordre` et `_ob.redemarrer_stack`.
2. **Décision dans `app/forge_ordres_bureau.py:341` (`demander_ordre`)** :
   - Ajouter `demandeur_prouve: bool = False` dans la signature de `demander_ordre`.
   - Avant l'appel de dialogue `confirmer(titre, detail)` (`app/forge_ordres_bureau.py:384`), vérifier :
     ```python
     identites = _charger_identites()
     meta = identites.get(demandeur, {})
     est_cli_pilote = demandeur_prouve and meta.get("surface") == "interactive"

     if est_cli_pilote:
         return {
             "etat": "A_DEMANDER",
             "a_demander_dans_la_session": True,
             "commande": _commande_de_repli(ordre, cible, texte, pointeur),
             "question": detail,
         }
     ```

### 3.2 Spécification du test RED (sans hub vivant)
- **Fichier de test** : `tests/nr/test_ordres_bureau_cli_pilote_nr.py`
- **Principe** : Isolation unitaire de `demander_ordre` avec mock de `confirmer`.
- **Cas de test 1 : CLI pilote interactif prouvé (Passage sans élicitation)** :
  - Appel : `demander_ordre(demandeur="CLAUDE", ordre="restart", texte="Reboot admin", cible="", pointeur="", confirmer=mock_confirmer, demandeur_prouve=True)`
  - Assertions :
    1. `assert mock_confirmer.call_count == 0` (aucun dialogue d'élicitation ouvert).
    2. `assert res.get("a_demander_dans_la_session") is True`
    3. `assert res.get("etat") == "A_DEMANDER"`
    4. `assert "nokido_launcher.py --action restart" in res.get("commande", "")`
    5. `assert "Reboot admin" in res.get("question", "")`
- **Cas de test 2 : Exécuteur autonome ou identité non prouvée (Garde active)** :
  - Appel avec `demandeur="AGY_HEADLESS"` (`surface="autonomous"`, `demandeur_prouve=True`) ou avec `demandeur="CLAUDE"` mais `demandeur_prouve=False`.
  - Assertions :
    1. `assert mock_confirmer.call_count == 1` (élicitation standard maintenue pour les entités autonomes ou non vérifiées).
