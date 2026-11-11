# Enquête : Réaffectation vers MISTRAL et gestion des surfaces indisponibles (2026-11-07)

## 1. Contexte et constat
Le 7/11, la tâche `job_5abb579a` est passée de `OPENCODE_GPTOSS` à `MISTRAL` suite au déclenchement d'un coupe-circuit `OPEN`.
Or, `MISTRAL` rendait une erreur HTTP 402 ("API budget exhausted" / budget Vibe épuisé), alors que `quota_status` l'affichait comme disponible ("ok").

## 2. Fichier et lignes où la surface de réaffectation est choisie

Dans `tools/forge_task_executor.py` :
- **Ligne 7038-7040** (`_reaffecter`) :
  ```python
  vivants = [a for a in (ordre or _ORDRE_REPLI)
             if a not in essayes and not (_gratuit and a in _SURFACES_PAYANTES) and _candidat_eligible(a)
             and surface_capable(a, _exig)]
  ```
- **Ligne 7045** (`_reaffecter`) :
  ```python
  vers = next((a for a in vivants if autoriser_essai_half_open(a)[0]), None)
  ```
- Puis arbitrage via ordre hédoniste / charge (**Lignes 7053-7063**) :
  ```python
  if len(vivants) > 1:
      ...
      vers, arme = mesure[0], True
  if vers and len(vivants) > 1:
      vers = _vers_moins_chargee(conn, task, _desc, vers, vivants)
  ```

## 3. Consultation de `sandbox/surfaces_indisponibles.json`

**Oui**, le fichier `sandbox/surfaces_indisponibles.json` est bien consulté à ce point précis :
- Lors du filtrage des candidats dans `_candidat_eligible(a)` (`tools/forge_task_executor.py:6881`) :
  ```python
  def _candidat_eligible(a: str) -> bool:
      if not (_executeur_bat(a) and not _executeur_suspendu(a) and not _opencode_hors_quota(a)
              and statut_coupe_circuit(a)[0] != "OPEN" and not surface_est_indisponible(a)):
          return False
      ...
  ```
- `surface_est_indisponible(a)` (`tools/forge_task_executor.py:878-902`) consulte `_SURFACES_INDISPONIBLES` (mémoire locale) ainsi que `_lire_indispo()` (`tools/forge_task_executor.py:794`), qui lit directement `_FICHIER_INDISPO` (`sandbox/surfaces_indisponibles.json`, défini ligne 782-783).

Toutefois, pour que MISTRAL y soit marqué indisponible, il fallait qu'un quota épuisé ou un échec d'authentification ait été préalablement détecté et écrit dans ce registre par `_noter_indisponibilite` (`tools/forge_task_executor.py:945`). Le 7/11, le 402 « API budget exhausted » de Mistral n'était pas initialement classé comme quota dans l'expression régulière avant le correctif apporté par `test_budget_epuise_marque_surface_nr`. De plus, `quota_status` ne songeait pas à interroger la balance dynamique de l'API Mistral (se contentant d'un statut statique ou local).

## 4. Comportement à l'expiration de `jusqu_a` (`INDISPO_DEFAUT_S = 6 h`)

À l'expiration de `jusqu_a` (délai par défaut `INDISPO_DEFAUT_S = 6 h` lorsqu'aucune date exacte de réinitialisation n'est fournie par le fournisseur) :
- `surface_est_indisponible(agent, maintenant)` évalue la condition temporelle (`instant < float(d.get("jusqu_a"))`).
- Dès que `instant >= jusqu_a`, la condition n'est plus satisfaite et la fonction rend `None` (la surface n'est plus considérée comme indisponible).
- **Une tâche peut donc tout à fait retomber sur cette surface** dès lors que son délai d'indisponibilité a expiré et que son coupe-circuit n'est pas `OPEN`.
- Si le budget fournisseur est toujours épuisé côté API distante (aucune recharge n'ayant eu lieu), la surface échouera à nouveau lors de son premier essai, ce qui relancera une nouvelle mise en indisponibilité de 6 heures.

## 5. Ce qui n'a pas été établi
- Le mécanisme exact par lequel `quota_status` au hub synchronise (ou omet de synchroniser) l'état réel des crédits API tiers prépayés pour les modèles de type Mistral/Vibe en l'absence de webhook ou de sonde active du solde restant.
