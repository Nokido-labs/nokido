# 🧭 GUIDE DE SURVIE — Nokido Agent

Ce guide est l'index central pour la maintenance, l'auto-réparation et la continuité cognitive de l'agent.

## 🗂️ Index des Ressources Critiques

- **Dernières Leçons Apprises** : `~/Script python IA/Nokido/logs/lessons_learned.md`
- **Protocole de Session (LLM)** : `~/Script python IA/CLAUDE.md`
- **État du Système** : `~/Script python IA/SITUATION.md`
- **Mémoire Privée** : `~/.gemini/tmp/script-python-ia/memory/memory.md`
- **Skill de Sauvetage** : `laforge-rescue` (dans `.gemini/skills/`)

## 🛠️ Auto-Réparation Rapide (First Aid)

### 1. Erreur de Permissions (`PermissionError: [Errno 13]`)
Si un script ne peut pas écrire ses logs ou accéder à un dossier :
```powershell
icacls "~\Script python IA\logs" /grant "${env:USERNAME}:(OI)(CI)M" /T
```

### 2. Services HS ou Bloqués (NSSM)
Vérifier et redémarrer les coeurs de Nokido :
- `nssm restart LaForgeMCP` (Hub MCP :8766)
- `nssm restart NokidoWebHub` (Interface Web :7400)
- `nssm restart NokidoLlamaNative` (Llama local :8091)
- `nssm restart NokidoOrchestrator` (Homéostasie/MAPE-K)

### 3. Libérer un Port Bloqué
```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8766).OwningProcess -Force
```

## 🚫 Directives Anti-Bug (Règles d'Or)

1.  **PAS DE NUMÉROTATION** : Ne jamais livrer un script ou un bloc de code avec des numéros de ligne au début. PowerShell/Python ne les interprètent pas.
2.  **PYTHON ABSOLU** : Toujours utiliser `~/miniforge3/python.exe`. Ne jamais taper juste `python`.
3.  **RAG FIRST** : Avant de créer un fichier dans `app/`, faire : `RAGEngine.search(keywords)` ou `SELECT source FROM rag_chunks WHERE text LIKE '%keywords%'`. **Ne pas réinventer la roue.**
4.  **PRIMARY KEYS** : Pour `rag_chunks`, l'ID est un `TEXT`. Utiliser `forge_self_correction._make_id(text, source)`.
5.  **CHEMINS WINDOWS** : Utiliser des `r"raw strings"` pour les chemins avec des backslashes 
ou privilégier les forward slashes `/`. Attention aux espaces dans les chemins.

## 🛡️ RÈGLES DE RECHERCHE SÉCURISÉE (ANTI-BLOCAGE UI)

**Crucial pour éviter de figer le CLI (Event Loop Block) :**

1.  **FILTRAGE** : Jamais de `Get-ChildItem -Recurse` sans filtre. Exclure : `.git`, `node_modules`, `.venv`, `*.db`.
2.  **LIMITE** : Toujours piper vers `Select-Object -First 30`.
3.  **DÉPORT** : Rediriger les gros flux vers un fichier temporaire (`> tmp.txt`) au lieu de stdout.
4.  **RAG PREFERENCE** : Utiliser `rag query=` ou `query sql=` (FTS) en priorité.

## 🧬 Systèmes Biomimétiques & Orchestration


### 1. Symbiotic Core (L'Hypothalamus)
Gère l'allumage des ressources et le suivi des processus.
- **Script** : `app/forge_symbiotic_core.py`
- **Registre PIDs** : `LaForge/sandbox/pids/registry.json`
- **Action JIT** : Déclenche Ollama/Docker uniquement si nécessaire.

### 2. Symbiose Gemma/Gemini (Le Cortex)
Chaînage cognitif entre modèles locaux (Gemma) et cloud (Gemini).
- **Script** : `app/forge_symbiosis_bridge.py`
- **Flux** : Évaluation locale (Gemma) -> Escalade si complexe -> Exécution Cloud (Gemini) -> Validation locale.

### 3. Homéostasie (La Maintenance)
Daemon de surveillance en arrière-plan.
- **Script** : `tools/nokido_homeostasis.py`
- **Rôle** : Nettoie les processus orphelins (cleanup_orphans) et surveille la santé des services.

## 🛠️ Auto-Réparation Rapide (First Aid)
