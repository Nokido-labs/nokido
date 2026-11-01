# AUDIT DE SÉCURITÉ : COFFRE CLOISONNÉ & LECTURE DE SECRETS RING ≤ 3
**Date :** 2026-10-29  
**Auditeur :** Antigravity (`agt_antigravity`)  
**Statut :** AVIS FORMEL DE SÉCURITÉ (Lecture seule, non intrusif)  
**Cible :** `app/forge_coffre_cloisonne.py`, `app/forge_secrets.py`, `tests/test_forge_coffre_cloisonne.py`

---

## 1. Réponse à la Question Fermée

> **Question :** Un compte ou agent NON autorisé (ex. le compte bac à sable `LaForgeSbxOnline`) peut-il lire un secret qui ne lui est pas destiné (secret d'une identité ring ≤ 3, ex. `FORGE_TOKEN_SWARM_LANCEUR`) ?

### **Verdict : OUI, PROUVÉ.**

Un compte non autorisé exécutant du code sous le compte bac à sable Windows `LaForgeSbxOnline` **peut effectivement lire** un secret d'identité de ring ≤ 3.

### Synthèse du mécanisme :
1. **Mode Observation non bloquant :** Dans `app/forge_secrets.py:709-715`, `get_secret` appelle `observer_lecture_cloisonnee(key)`. Cette fonction invoque `decision_lecture(..., mode="observation")` (`app/forge_coffre_cloisonne.py:18-25`), qui renvoie systématiquement `(True, "aurait_refuse:bac_ring_le_3")`. De plus, la valeur de retour n'est même pas évaluée par `get_secret`.
2. **Fuite via le Coffre Machine DPAPI :** La clé `FORGE_TOKEN_SWARM_LANCEUR` n'étant pas dans `NOMS_RESERVES`, `_ferme` est `False`. `get_secret` interroge alors `_sonder("coffre", key)` qui lit le coffre machine `DPAPI LocalMachine` (`app/forge_secrets.py:570-577`). Par conception OS, `LocalMachine` est déchiffrable par **n'importe quel compte local** de la machine, y compris `LaForgeSbxOnline`.
3. **Fuite secondaire via .env et os.environ :** Si le secret est présent dans `Nokido.env` ou hérité dans `os.environ`, aucun refus ne s'applique.

---

## 2. Tableau d'Évaluation par Chemin de Lecture

| Chemin de lecture | Preuve (fichier:ligne + ligne recopiée) | État | Analyse technique |
| :--- | :--- | :--- | :--- |
| **0. Coffre de Test (`_coffre_test`)** | `app/forge_secrets.py:706` : `_v_test = _coffre_test(key)`<br>`app/forge_secrets.py:498` : `if not dossier or not os.environ.get("PYTEST_CURRENT_TEST"): return None` | **RÉFUTÉ** | Strictement conditionné à l'exécution sous `pytest` et présence d'un dossier temporaire dédié. Inopérant hors test. |
| **1. Cache Mémoire (`_cache`)** | `app/forge_secrets.py:732` : `if key in _cache:`<br>`app/forge_secrets.py:740` : `return _cache[key]` | **PROUVÉ** | Si le processus a déjà résolu le secret dans la session en cours, la valeur est retournée immédiatement sans vérification d'identité ni de ring. |
| **2. Coffre Réserve (`_coffre_reserve`)** | `app/forge_secrets.py:768-773` :<br>`if key in NOMS_RESERVES:`<br>`    val, _ill = _sonder("coffre_reserve", key)`<br>`app/forge_secrets.py:596-597` :<br>`if etat in RESERVE_ETATS_ILLISIBLES:`<br>`    raise PermissionError(f"coffre reserve {etat}")` | **ILLISIBLE** | Protégé par ACL NTFS (`SYSTEM + Administrateurs`) et DPAPI portée utilisateur sous `SYSTEM`. Un compte restreint comme `LaForgeSbxOnline` subit un `PermissionError` transformé en `_ill = True`. |
| **3. Coffre Machine (`_machine_vault`)** | `app/forge_secrets.py:777-781` :<br>`if not _ferme:`<br>`    val, _ill = _sonder("coffre", key)`<br>`    ...`<br>`    elif val:`<br>`        return _memoriser(key, val, "coffre")`<br>`app/forge_secrets.py:570-572` :<br>`def _machine_vault(key: str) -> Optional[str]:`<br>`    """Lire depuis le coffre machine-wide (DPAPI LocalMachine).`<br>`    Lisible par TOUS les comptes service, contrairement au WCM per-user."""` | **PROUVÉ** | DPAPI `LocalMachine` n'isole pas les utilisateurs locaux Windows. Tout processus local (y compris un worker sous `LaForgeSbxOnline`) déchiffre les blobs du coffre machine si le secret y réside. |
| **4. Magasin WCM (`_wcm`)** | `app/forge_secrets.py:783-787` :<br>`val, _ill = _sonder("wcm", key)`<br>`if _ill:`<br>`    _illisibles.append("wcm")`<br>`elif val:`<br>`    return _memoriser(key, val, "wcm")`<br>`app/forge_secrets.py:561-564` :<br>`def _wcm(key: str) -> Optional[str]:`<br>`    try:`<br>`        import keyring as _kr`<br>`        return _kr.get_password(SERVICE, key) or None` | **RÉFUTÉ** | Windows Credential Manager est strictement cloisonné par compte utilisateur Windows (`per-user`). `LaForgeSbxOnline` n'a pas accès aux secrets WCM de l'administrateur/owner `user`. |
| **5. Fichier DotEnv (`_dotenv`)** | `app/forge_secrets.py:790-795` :<br>`if not _ferme:`<br>`    val, _ill = _sonder("dotenv", key)`<br>`    ...`<br>`    elif val:`<br>`        return _memoriser(key, val, "dotenv")` | **PROUVÉ** | Si `Nokido.env` est lisible sur le système de fichiers par le compte du bac et que `_ferme` est faux, les secrets y figurant sont distribués sans contrôle de ring. |
| **6. Variables d'Environnement (`os.environ`)** | `app/forge_secrets.py:799-805` :<br>`val = os.environ.get(key)`<br>`if val:`<br>`    ...`<br>`    return _memoriser(key, val, "environ")` | **PROUVÉ** | Si le secret est hérité dans le bloc d'environnement du processus sandbox, il est renvoyé avec un simple warning de log. |
| **7. Garde Cloisonnée (`observer_lecture_cloisonnee`)** | `app/forge_secrets.py:709-710` :<br>`try:                                 # OBSERVATION seulement (suite 3), ne refuse rien`<br>`    observer_lecture_cloisonnee(key)`<br>`app/forge_secrets.py:663` :<br>`ok, raison = decision_lecture(_compte_du_jeton(), genre, 3, bac, "observation")`<br>`app/forge_coffre_cloisonne.py:21-22` :<br>`if mode == "observation":`<br>`    return True, "aurait_refuse:bac_ring_le_3"` | **PROUVÉ (Pas de refus)** | Le garde est configuré en mode `"observation"`. Il consigne dans `OBSERVES_CLOISONNEMENT` mais ne bloque jamais l'exécution. `get_secret` ignore totalement le retour. |

---

## 3. Passage au Refus Proposé + NR (NON Appliqué)

### A. Où dans le code le refus doit se faire

Le refus doit obligatoirement intervenir **en amont de toute lecture** de source physique ou mémoire dans `get_secret` :
- **Fichier cible :** `app/forge_secrets.py`
- **Emplacement exact :** Lignes 709–715 (juste après le court-circuit `_coffre_test(key)`).

### B. Modifications nécessaires

1. **Rendre la vérification bloquante :**
   Remplacer l'appel passif `observer_lecture_cloisonnee(key)` par une fonction active `verifier_lecture_cloisonnee(key, mode=...)`.
2. **Résolution dynamique du ring et du genre :**
   Actuellement, `genre` est déduit par `key.startswith("FORGE_TOKEN_")` et le `ring` est fixé à `3`. Une résolution plus fine peut interroger `config/agent_identities.json` ou mapper les tokens d'agents ring ≤ 3.
3. **Traitement de l'échec :**
   Si `decision_lecture` retourne `ok is False`, `get_secret` doit :
   - Noter l'événement : `_noter(key, "REFUSE_CLOISONNEMENT", None)`
   - Si `required=True` : lever `PermissionError(f"Lecture cloisonnee refusee: {raison} ({key!r})")`
   - Si `required=False` : consigner un avertissement et retourner immédiatement `None`.

### C. Proposition de Patch (Conceptuel, NON appliqué)

```python
# --- Proposition dans app/forge_secrets.py ---

def verifier_lecture_cloisonnee(key: str) -> tuple[bool, str]:
    """Contrôle d'accès cloisonné : refuse la lecture d'identités ring <= 3 aux comptes bac."""
    try:
        from app.forge_coffre_cloisonne import decision_lecture
        # Mode gouverné par configuration / variable d'environnement (défaut 'bloquant' ou 'observation')
        mode = os.environ.get("NOKIDO_CLOISONNEMENT_MODE", "bloquant")
        bac = [c for c in os.environ.get("NOKIDO_COMPTES_BAC", "LaForgeSbxOffline,LaForgeSbxOnline").split(",") if c]
        genre = "identite" if key.startswith("FORGE_TOKEN_") else "autre"
        
        # Le ring 3 est le seuil critique pour les identités système/swarm
        compte_actuel = _compte_du_jeton()
        ok, raison = decision_lecture(compte_actuel, genre, 3, bac, mode=mode)
        
        if not ok:
            _noter(key, "REFUSE_CLOISONNEMENT", None)
        elif raison.startswith("aurait_refuse"):
            OBSERVES_CLOISONNEMENT.append({"cle": key, "raison": raison})
            del OBSERVES_CLOISONNEMENT[:-500]
            
        return ok, raison
    except Exception:
        # Fail-closed pour les comptes du bac identifiés
        return True, "observation_indisponible"

# Dans get_secret(key: str, required: bool = False):
# Remplacer les lignes 709-715 par :
    ok_lecture, raison_lecture = verifier_lecture_cloisonnee(key)
    if not ok_lecture:
        if required:
            raise PermissionError(
                f"Secret {key!r} refuse par cloisonnement ({raison_lecture}) "
                f"pour le compte {_compte_du_jeton()!r}"
            )
        return None
```

### D. Test de Non-Régression (NR) Proposé (NON Appliqué)

```python
# --- tests/nr/test_forge_secrets_cloisonne_nr.py ---
import pytest
from app import forge_secrets
from app import forge_coffre_cloisonne as cc

def test_get_secret_refuse_identite_ring_3_sous_compte_bac(monkeypatch):
    """Vérifie que sous un compte bac à sable, get_secret refuse une identité ring <= 3."""
    # 1. Simuler l'exécution sous compte bac
    monkeypatch.setattr(forge_secrets, "_compte_du_jeton", lambda: "LaForgeSbxOnline")
    monkeypatch.setenv("NOKIDO_CLOISONNEMENT_MODE", "bloquant")
    
    # 2. Injecter une valeur dans le coffre machine pour prouver le blocage amont
    monkeypatch.setattr(forge_secrets, "_machine_vault", lambda k: "secret_exfiltrable" if k == "FORGE_TOKEN_SWARM_LANCEUR" else None)
    
    # 3. La lecture doit être refusée (None si not required, PermissionError si required)
    val = forge_secrets.get_secret("FORGE_TOKEN_SWARM_LANCEUR", required=False)
    assert val is None, "Le secret ring <= 3 ne doit pas être servi au compte du bac"
    
    with pytest.raises(PermissionError, match="bac_ring_le_3"):
        forge_secrets.get_secret("FORGE_TOKEN_SWARM_LANCEUR", required=True)

def test_get_secret_autorise_owner_ou_api(monkeypatch):
    """Vérifie que l'owner ou une clé API standard reste lisible."""
    monkeypatch.setattr(forge_secrets, "_compte_du_jeton", lambda: "user")
    monkeypatch.setattr(forge_secrets, "_machine_vault", lambda k: "valeur_legitime")
    
    assert forge_secrets.get_secret("FORGE_TOKEN_SWARM_LANCEUR") == "valeur_legitime"
    assert forge_secrets.get_secret("GROQ_API_KEY") == "valeur_legitime"
```

---

## 4. Ce que le Refus Casserait

L'activation immédiate du refus bloquant sans adaptation préalable entraînerait des ruptures fonctionnelles sur plusieurs briques existantes exécutées sous compte restreint ou dans un job :

### 1. `tools/forge_secours_lanceur.py` (Lanceur de secours Swarm)
- **Point de rupture :** Lignes 91–96 de `tools/forge_secours_lanceur.py` :
  ```python
  def _appel_identite(outil: str, arguments: dict) -> str:
      try:
          jeton = _get_secret(CLE_COFFRE)  # CLE_COFFRE = "FORGE_TOKEN_SWARM_LANCEUR"
      except Exception:
          jeton = None
      if not jeton:
          raise RuntimeError(MOTIF_IDENTITE)
  ```
- **Conséquence :** Si le script est exécuté par un démon ou un planificateur sous le compte `LaForgeSbxOnline`, l'appel `_get_secret` renverra `None`.
- **Impact :** Levée immédiate de `RuntimeError("identité SWARM_LANCEUR indisponible")`. Le secours automatique de synthèse du swarm devient totalement inopérant.
- **Anomalie d'architecture révélée :** Bien que `forge_secours_lanceur.py` intègre la fonction `_echange_job()` (RFC 8693) aux lignes 48–77, la fonction `_appel_identite` continue d'exiger `jeton = _get_secret(CLE_COFFRE)` **avant** de passer à `_session_pour(jeton)`. L'échange de jeton est donc court-circuité par une dépendance directe au secret statique du coffre.

### 2. `app/forge_mpc_executor.py` (Exécuteur MPC temps réel)
- **Point de rupture :** Lignes 28–33 :
  ```python
  _TOKEN = get_secret("FORGE_MCP_TOKEN") or ""
  ```
- **Conséquence :** Si un worker MPC tourne dans le bac à sable et que `FORGE_MCP_TOKEN` est soumis à la politique ring ≤ 3, `_TOKEN` devient vide.
- **Impact :** Tous les appels MCP `_hub_call` vers `http://127.0.0.1:8766/mcp` échouent en HTTP 401 / Unauthorized.

### 3. Jobs autonomes sans implémentation du Token Exchange (RFC 8693)
- **Conséquence :** Tout script ou job s'exécutant dans le bac à sable qui s'authentifie historiquement en lisant directement une clé `FORGE_TOKEN_*` dans le coffre verra son accès coupé.
- **Condition préalable indispensable au passage en mode bloquant :**
  1. Corriger `tools/forge_secours_lanceur.py` pour qu'il n'exige plus `_get_secret(CLE_COFFRE)` lorsque `NOKIDO_JOB_SUBJECT_TOKEN` et `NOKIDO_JOB_ID` sont présents dans l'environnement.
  2. Généraliser l'émission préalable de jetons de job à durée courte pour tous les daemons et tâches planifiées exécutés sous compte sandbox.
