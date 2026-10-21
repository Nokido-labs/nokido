# Routeur LLM — Capacité Fournisseur Observée (p2_capacite_fournisseur_observee_0925)

## 1. Production et stockage de la capacité observée

### 1.1 Point d'entrée de capture
- **Fichier**: `app/forge_llm_router.py`
- **Fonction**: `_capter_capacite(provider, source)` (L1060-L1069)
- **Description**: Appelé depuis `_call_slot()` (L2049) juste après chaque appel réussi au provider
- **Comportement**: Transmet la réponse à `forge_quota_tracker.capturer_reponse()`, ne lève jamais d'exception (muet-ok)

### 1.2 Stockage
- **Fichier**: `app/forge_quota_tracker.py`
- **Fonction**: `capturer_reponse(provider, source, maintenant)` (extrait à L~500)
- **Emplacement**: Fichiers JSON individuels dans le dossier `CAPACITE_DIR`
- **Format**: `{provider_slug}.json` avec:
  - `capture_le`: timestamp UTC de la capture
  - `entetes`: dictionnaire des en-têtes x-ratelimit-* et autres métadonnées
  - `erreur`: booléen indiquant si la capture a eu lieu sur une erreur HTTP
- **Schéma**: `_CHAMPS` et `_RESETS` définissent les clés attendues (par ex. `x-ratelimit-reset`, `x-ratelimit-remaining`)
- **Fraîcheur**: Non explicitement documenté, mais la fonction `capacite_observee()` retourne l'âge (`age_s`) en secondes et détermine l'état FRAICHE/PERIMEE/INCONNU avec un seuil `PEREMPTION_S`

**Lectures uniquement**: Le routeur ne lit PAS directement ces fichiers JSON — il utilise la fonction `capacite_observee()` de `forge_quota_tracker` (voir question 2).

## 2. Choix du provider par le routeur et lecture actuelle

### 2.1 Sélection du provider
- **Fichier**: `app/forge_llm_router.py`
- **Fonction**: `LLMRouter._select_slot(use_case, exclure)` (L1257-L1288)
- **Critères de choix**:
  1. Chaîne active pour le use_case (via `chaine_active()`, L1271)
  2. Slots configurés et disponibles (`is_available()`, L1273)
  3. Si ≥2 candidats: meilleur TrustScore via `TrustScoreRegistry.get().best_provider()` (L1280-L1287)
  4. Sinon: premier candidat de la chaîne (L1288)

### 2.2 Fonction `is_available()` (ProviderSlot)
- **Fichier**: `app/forge_llm_router.py` (L1143-L1165)
- **Critères**:
  - Configuré (`is_configured`)
  - Cooldown expiré (`time.monotonic() < _cooldown`)
  - Failures < 3
  - Circuit breaker permet (`_breaker.allow()`)
  - Slots locaux: readiness réelle via `_slot_local_ready()` (sonde live)
  - RPM respecté (`_within_rpm()`)

**Manque critique**: Aucun appel à `capacite_observee()` ou référence explicite à la capacité observée dans la logique de décision.

### 2.3 Analyse de la présence ou absence de lecture de capacité observée
- **Recherche directive**: `grep` sur "capacite_observee" dans `forge_llm_router.py`
- **Résultat**: **Aucune occurrence** — le fichier ne contient pas d'appel à `capacite_observee()`
- **Conclusion**: Le routeur N'UTILISE PAS aujourd'hui la capacité observée dans le choix des providers

**Justification théorique**: Le code comporte des filtres et garde mais aucun filtrage basé sur la capacité observée. Les filtres actuels sont:
- `injoignables_prouves()` pour les slots injoignables (L1257-L1288, L728-L743)
- Filtrage par quota via `forge_provider_quota.filter_chain()` (L1403-L1414)
- Filtrage par disponibilité locale (`can_run_locally()`, L1420-L1448)
- Garde sémantique (`forge_semantic_firewall`), cortisol, dead_end (L1391-L1486)

## 3. Problématique: Capacité MAUVAISE vs CAPACITÉ INCONNUE

### 3.1 Situation actuelle (UNKNOWN ≠ NO)

La fonction `capacite_observee()` de `forge_quota_tracker.py` retourne trois états pour chaque provider (L499-L542):

| État | Définition | Code |
|------|------------|------|
| `INCONNU` | Fichier JSON absent ou illisible | `return {"etat": INCONNU, ...}` |
| `FRAICHE` | Capture récente + compteurs lisible + pas de réinitialisation passée | L519-L521 |
| `PERIMEE` | Capture vieillie (> PEREMPTION_S) OU réinitialisation passée | L523-L525 |

**Problème**: L'état `INCONNU` signifie "donnée manquante", pas "provider inexistant". Aucune distinction n'est faite entre:
- Provider A: **INCONNU** (jamais capturé) → devrait **NE PAS être écarté**
- Provider B: **FRAICHE** mais avec **valeur de capacité < 0** → devrait **être écarté** (mais ce cas ne se présente pas car les compteurs sont positifs par définition)

### 3.2 Définitions manquantes

Aucun mécanisme ne sépare clairement:
- **Mauvaise capacité** (ex: valeur < 0, sous-quota, déficit) → doit éliminer le provider
- **Capacité inconnue** (jamais capturée) → ne doit JAMAIS éliminer le provider

### 3.3 Proposition de changement d'architecture

#### 3.3.1 Nouvel état de capacité

Ajouter un quatrième état dans `forge_quota_tracker.py`:

```python
INCONNU = "INCONNU"  # Aucune capture (jamais appelé)
CAPACITE_MAUVAISE = "MAUVAISE"  # Compteur < 0, sous-quota, déficit
```

**Critères de transition**:
- `MAUVAISE`:
  - Compteur restant < 0 (ex: x-ratelimit-remaining < 0)
  - Vérification de l'intégrité (pas de NaN, pas de valeur illogique)
  - Capture récente (fraîcheur < PEREMPTION_S) → évite le spectre du "jamais appelé"
  - Marqueur explicite: `{"valeur": -1, "est_mauvais": true}` ou attribut `est_mauvais: true`

- `INCONNU`:
  - Fichier JSON absent OU éligible à l'oubli (ancienneté > PEREMPTION_S*2, ex: 14 jours)
  - Aucune lecture récente (timbre d'activité)
  - Aucun délai de purge (mécanisme "absence prouvée")

#### 3.3.2 Nouvelle fonction de filtrage pour le routeur

Dans `LLMRouter._select_slot()` (L1257-L1288), ajouter un appel à `filter_provider_capacite()`:

```python
def _filter_provider_capacite(chain: list[str]) -> list[str]:
    """Écarte les providers à capacité MAUVAISE, conserve les INCONNU."""
    try:
        from nokido_agent.app.forge_quota_tracker import filter_provider_capacite
        return filter_provider_capacite(chain)
    except ImportError:
        # Fallback: retourne la chaîne inchangée (compatibilité descendante)
        return chain

# Dans _select_slot():
chain = _filter_provider_capacite(chain)
```

#### 3.3.3 Fonction de filtrage à ajouter dans forge_quota_tracker.py

```python
def filter_provider_capacite(chain: list[str]) -> list[str]:
    """Filtre la chaîne de providers en écartant ceux à CAPACITE_MAUVAISE.
    Les providers INCONNU ne sont JAMAIS écartés (UNKNOWN ≠ NO).
    """
    # Faire la collecte LOCALEMENT (pas d'import dans ce module pour éviter circular)
    # 1. Lire les états pour chaque provider dans la chaîne
    # 2. Filtrer en conservant ceux dont l'état est FRAICHE ou INCONNU
    # 3. Retourner la chaîne filtrée

    return filtered_chain
```

**Logique de filtrage**:
```python
keep = []
for provider in chain:
    etat = capacite_observee(provider)["etat"]
    if etat == CAPACITE_MAUVAISE:
        logging.getLogger("Nokido.Router").info(
            "[routeur] provider %s écarté: capacité mauvaise (%s)", provider, etat)
        continue
    # INCONNU ou FRAICHE → conserver
    keep.append(provider)

return keep
```

#### 3.3.4 Intégration dans la chaîne de filtres

Insérer ce filtre après `chaine_active()` et avant le TrustScore pour respecter l'ordre de priorité:

1. `chaine_active(use_case)` — ordre de la chaîne
2. `_filter_provider_capacite()` — écarte les mauvaises capacités (Nouveau)
3. `forge_provider_quota.filter_chain()` — quota mensuel épuisé
4. `forge_host_capabilities.can_run_locally()` — modèle trop lourd pour l'hôte
5. TrustScoreRegistry.get().best_provider() — meilleur score
6. Sélection du premier candidat

### 3.4 Conséquences opérationnelles

**Avantages**:
- Prévention des erreurs 429 immédiats (le provider à épuisement est écarté avant le premier appel)
- Réduction des timeouts (provider déjà épuisé n'est pas choisi)
- Connaissance active de la disponibilité (contrairement aux marqueurs perimes statiques)

**Risques**:
- "False positive": capture défaillante sur un provider sain (prévenir par captures fréquentes, timeout courts, historique)
- "False negative": provider inconnu (INCONNU) conservé, ce qui est le comportement désiré (UNKNOWN ≠ NO)
- Performance: lecture de fichiers JSON (éviter par cache local, TTL de 1 minute)

### 3.5 Point de contrôle (anti-régression)

Ajouter un test NR dans `tests/nr/test_capacite_routeur_nr.py`:

```python
def test_capacite_inconnue_ne_ecarte_pas_provider():
    # Simuler un provider jamais capturé → INCONNU
    # Vérifier qu'il n'est PAS écarté par le routeur

def test_capacite_mauvaise_ecarte_provider():
    # Simuler un provider avec x-ratelimit-remaining < 0 → MAUVAISE
    # Vérifier qu'il EST écarté par le routeur

def test_capacite_fraiche_conserve_provider():
    # Simuler un provider à capacité fraîche
    # Vérifier qu'il est CONSERVÉ par le routeur
```

## Conclusion

Le routeur LLM N'UTILISE PAS la capacité observée aujourd'hui. L'infrastructure existe (fonction `_capter_capacite()`, stockage JSON, lecture via `capacite_observee()`), mais la connexion avec la logique de choix du provider n'est pas implémentée.

Pour harmoniser la règle "observer avant d'enforcer", il faut:
1. Ajouter un état `CAPACITE_MAUVAISE` dans `forge_quota_tracker`
2. Filtrer les providers à capacité mauvaise via `_filter_provider_capacite()`
3. Insérer ce filtre dans la chaîne de sélection `_select_slot()`
4. Garantir que les providers `INCONNU` ne sont jamais écartés (UNKNOWN ≠ NO)

Cela permet de prévenir les appels ratés (429, timeout) tout en conservant la flexibilité pour les providers inconnus (jamais appelés).
