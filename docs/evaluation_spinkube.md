# 🔍 Évaluation Technique : SpinKube pour Nokido

- **Date** : 2026-06-23
- **Auteur** : `agt_antigravity`
- **Sujet** : Évaluation de SpinKube (Orchestrateur Kubernetes pour composants WASM Spin)
- **Réf. Veille** : Job `wj_675239ad6d` (Source RAG : `spinkube-docs`)
- **Verdict** : **WATCH** 👁️

---

## 1. Description & Architecture de SpinKube
SpinKube est un projet CNCF visant à exécuter des applications WebAssembly (`SpinApp`) nativement dans un cluster Kubernetes. Son architecture repose sur :
1. **Spin Operator** : Gère les ressources personnalisées (CRD) `SpinApp` et `SpinAppExecutor`.
2. **Runtime Class Manager** (KWasm) : Automatise le provisionnement et la configuration des shims WASM sur les nœuds Kubernetes.
3. **containerd-shim-spin** : Permet à `containerd` d'exécuter des modules WASM Spin directement comme des sous-processus isolés (sandboxing léger), offrant des démarrages quasi instantanés (<1ms cold start) sans surcharge d'image de conteneur complète.

---

## 2. Analyse de Pertinence pour Nokido
Nokido est actuellement conçu sous une doctrine **local-first et mono-machine** (APU grand public / machine de développement unique).

* **Avantages potentiels de SpinKube** :
  - Isolation sandbox WASI rigoureuse.
  - Vitesse de démarrage (µs/ms) et empreinte mémoire minuscule des agents/routes WASM.
  - Standardisation de l'intégration avec Kubernetes si la flotte d'agents doit être distribuée.

* **Inconvénients / Surcharge actuelle** :
  - **Overkill d'infrastructure** : Introduire Kubernetes, un Control Plane, containerd et un Operator pour exécuter des micro-services sur une machine locale est contre-productif.
  - **Alternative native** : Sur un nœud unique, Nokido bénéficie déjà du chargement WASM natif ultra-rapide via V8/Deno (ex: notre route `/health` dans `web_hub/main.ts`) ou via des appels directs `wasmtime` en sous-processus, sans aucune surcharge d'orchestration.

---

## 3. Conditions de Déclenchement (Transition de WATCH → ADOPT)
L'intégration de SpinKube/Kubernetes dans Nokido sera déclenchée si :

1. **Passage au Multi-Node / Cluster** : Le déploiement de Nokido passe d'une seule machine locale à un essaim de serveurs physiques distants nécessitant un ordonnancement (scheduling), une haute disponibilité (HA), et un auto-scaling d'agents distribués.
2. **Intégration d'Entreprise Cloud-Native** : Nokido doit cohabiter dans une infrastructure Kubernetes d'entreprise déjà établie, où les agents doivent être gérés comme des Pods standards via des CRDs unificados.
3. **Consommation d'API de services externes via K8s** : Le besoin d'orchestrer dynamiquement des milliers de fonctions WASM d'inférence légère à la demande sur un cluster hybride edge/cloud (ex: Akamai/Linode avec shims WASM).

---

## 4. Recommandation à Court Terme
Conserver le verdict **WATCH**.
Pour le périmètre actuel (mono-machine), continuer à privilégier l'exécution WASM intégrée dans le proxy Deno (V8) ou via le moteur léger Wasmtime local pour isoler les services HTTP critiques (comme `web_hub`).
