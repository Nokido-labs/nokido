# FAQ & Glossaire Nokido

> Questions courantes et lexique. Pour l'architecture, voir [ARCHITECTURE.md](ARCHITECTURE.md).

## FAQ

### 1. C'est quoi la différence entre Nokido et ChatGPT ?

ChatGPT est un médecin généraliste cloud qui oublie tout entre deux consultations.
Nokido est **ton propre hôpital local** : il garde une mémoire permanente de tout ce qu'il apprend (535k fragments), fait appel aux spécialistes cloud seulement si nécessaire (et anonymise tes données avant), et tourne 24h/24 sur ta machine sans abonnement.

### 2. Pourquoi `LAFORGE_PYTHON` et pas juste `python` ?

```bash
# ❌ JAMAIS ça — risque de charger le mauvais environnement
python tools/nokido_hub.py

# ✅ TOUJOURS ça
C:/Users/<toi>/miniforge3/python.exe tools/nokido_hub.py
```

Nokido a des dépendances précises (ONNX Runtime, FAISS, ZMQ...) installées dans miniforge3. Si tu lances avec `python` brut, tu risques de charger un autre environnement avec des versions incompatibles. Incident vécu : les tests passaient mais starlette venait du mauvais site-packages — en production ça crashait.

### 3. Comment Nokido évite d'envoyer mes données privées dans le cloud ?

Deux niveaux de protection automatiques :

```python
# Niveau 1 — SemanticFirewall redacte avant envoi
pf = firewall.pre_flight(prompt, ring=2, provider="mistral")
# "mon serveur localhost est down" → "mon serveur <IP_0> est down"

# Niveau 2 — SovereignMembrane pour données structurées
membrane = SovereignMembrane(mission_id="audit_20260507")
wrapped = membrane.wrap(config_dict)
# Tous les IPs, hostnames, usernames → alias HMAC persistants par mission
```

Si la tâche est sensible (sécurité, CTF, données perso), Nokido route vers Ollama local — rien ne sort de ta machine.

### 4. Je veux ajouter un nouveau module. Par où commencer ?

**Règle d'or : vérifie d'abord si ça existe.**

```python
# Étape 1 — Cherche dans la mémoire RAG
from forge_self_correction import preflight_check_verbose
v = preflight_check_verbose("mon domaine ici", "")

# Étape 2 — Lis les modules qui matchent
# Si score > 50% → étends l'existant, ne crée pas un doublon

# Étape 3 — Si création justifiée, ancre ta décision
from forge_self_correction import anchor_solution
anchor_solution(
    problem="Pourquoi créer ce module malgré les existants",
    solution="Ce que les existants ne couvrent pas",
    domain="systeme"
)
```

### 5. Comment relancer Nokido si le Hub ne répond plus ?

```powershell
# ❌ Ne JAMAIS faire ça — conflit de port garanti
# nssm restart LaForgeMCP

# ✅ Méthode préférée — endpoint supervisor (pas besoin d'admin)
curl -X POST http://127.0.0.1:8765/supervisor/restart/LaForgeMCP

# ✅ Alternative — service NSSM (nom EXACT : LaForge-Master, avec tiret ;
#    requiert un terminal administrateur, sinon "Accès refusé")
nssm restart LaForge-Master

# Vérifier que tout est UP
curl http://localhost:8766/health
curl http://localhost:8765/supervisor/status
```

---

## Glossaire

| Terme | Définition simple |
|-------|-------------------|
| **RAG** | Retrieval-Augmented Generation — le LLM répond en s'appuyant sur des documents récupérés, pas juste sur sa mémoire d'entraînement |
| **Embedding** | Transformation d'un texte en vecteur de 1024 nombres — permet la recherche par "ressemblance" |
| **FAISS** | Bibliothèque de recherche vectorielle ultra-rapide de Meta (Facebook AI Similarity Search) |
| **BM25** | Algorithme de recherche par mots-clés (comme un moteur de recherche classique amélioré) |
| **RRF** | Reciprocal Rank Fusion — combine plusieurs résultats de recherche en un seul classement optimal |
| **ZMQ** | ZeroMQ — système de messagerie inter-processus ultra-rapide |
| **MCP** | Model Context Protocol — standard Anthropic pour connecter des outils à un LLM |
| **NSSM** | Non-Sucking Service Manager — lance des scripts Python comme des services Windows |
| **ONNX** | Format universel pour les modèles de ML — permet de faire tourner BGE-M3 sur le NPU AMD |
| **NPU** | Neural Processing Unit — puce dédiée à l'IA sur le Ryzen 7840HS (Radeon 780M) |
| **PPR** | Personalized PageRank — variante de l'algorithme Google PageRank pour graphes de connaissances |
| **GOAP** | Goal-Oriented Action Planning — planification autonome par objectifs |
| **FTS5** | Full-Text Search 5 — moteur de recherche plein texte intégré à SQLite |
| **BGE-M3** | Modèle d'embedding multilingue de BAAI — produit des vecteurs 1024D, tourne sur le NPU local |
| **Canary token** | Marqueur invisible inséré dans les prompts — si le LLM le répète, c'est qu'il y a une fuite |
| **AMI** | Autonomous Machine Intelligence — vision de Yann LeCun : agent à modèle du monde, pas LLM réactif |
| **JEPA** | Joint Embedding Predictive Architecture — prédire l'état futur dans l'espace latent, pas en pixels/tokens |
| **MPC** | Model Predictive Control — planifier sur un horizon court, agir, replanifier |
| **MCTS** | Monte Carlo Tree Search — recherche arborescente guidée (pilier d'AlphaZero) |
