# Audit de securite — Route d'echange de jetons OAuth (RFC 8693) et DPoP (RFC 9449)

**Date :** 2026-10-29  
**Cible :** Route d'echange de jetons `POST /oauth/token` (`app/forge_oauth_route.py`) et primitives associees (`app/forge_token_exchange.py`, `app/forge_dpop.py`, `app/forge_auth_tokens.py`).  
**Cadre :** Enquete lecture seule — verification stricte de la conformite DPoP RFC 9449 et de l'etancheite des portees/rings RFC 8693.

---

## 1. Contexte et postulats etablis

- **Statut de la route :** La route `POST /oauth/token` est en phase alpha (`app/forge_oauth_route.py:5`).
- **Tests associes :** Les tests unitaires et d'integration resident dans `tests/test_forge_oauth_route.py` et la conformite DPoP dans `tests/nr/test_dpop_rfc9449_nr.py`.
- **Comportement de l'observation :** Sur les appels de ring <= 3, l'intercepteur journalise les refus potentiels sans bloquer (`app/forge_oauth_route.py:149-155`) tant que `NOKIDO_OAUTH_ENFORCE` n'est pas arme (`app/forge_oauth_route.py:31-32`). Ce comportement est voulu par conception et ne constitue pas un defaut.

---

## 2. Tableau d'evaluation par cas (Question fermee)

| Cas | Preuve (fichier:ligne + ligne recopiee) | Etat |
|---|---|---|
| **DPoP absent** | `app/forge_oauth_route.py:112` : `    if jwk is None:`<br>`app/forge_oauth_route.py:113` : `        return _err(400, "invalid_dpop_proof", "preuve DPoP absente (RFC 9449 §5)")`<br>`tests/test_forge_oauth_route.py:73` : `    assert r.status_code == 400 and r.json()["error"] == "invalid_dpop_proof"` | **REFUTE** |
| **DPoP rejoue** | `app/forge_dpop.py:480` : `        if charge["jti"] in _jti_vus:`<br>`app/forge_dpop.py:481` : `            return _refus("jti deja vu : rejeu")`<br>`app/forge_oauth_route.py:115` : `    if etat != "LIEE":`<br>`app/forge_oauth_route.py:116` : `        return _err(400, "invalid_dpop_proof", "preuve DPoP refusee")`<br>`tests/nr/test_dpop_rfc9449_nr.py:192` : `    assert etat == "REFUSEE" and "rejeu" in raison, (etat, raison)` | **REFUTE** |
| **DPoP mal signe** | `app/forge_dpop.py:470` : `        pub.verify(_jws_vers_der(signature),`<br>`app/forge_dpop.py:473` : `    except Exception as exc:`<br>`app/forge_dpop.py:474` : `        return _refus("signature invalide (%s)" % type(exc).__name__)`<br>`app/forge_oauth_route.py:115` : `    if etat != "LIEE":`<br>`app/forge_oauth_route.py:116` : `        return _err(400, "invalid_dpop_proof", "preuve DPoP refusee")`<br>`tests/nr/test_dpop_rfc9449_nr.py:227` : `    assert dp.verifier(corps + "." + altere, "POST", URI, JETON)[0] == "REFUSEE"` | **REFUTE** |
| **DPoP htm/htu faux** | `app/forge_dpop.py:438` : `    if str(charge["htm"]).upper() != methode.upper():`<br>`app/forge_dpop.py:439` : `        return _refus("htm ne correspond pas a la methode")`<br>`app/forge_dpop.py:440` : `    if _uri_normalisee(str(charge["htu"])) != _uri_normalisee(uri):`<br>`app/forge_dpop.py:441` : `        return _refus("htu ne correspond pas a l'URI")`<br>`app/forge_oauth_route.py:115` : `    if etat != "LIEE":`<br>`app/forge_oauth_route.py:116` : `        return _err(400, "invalid_dpop_proof", "preuve DPoP refusee")`<br>`tests/nr/test_dpop_rfc9449_nr.py:168` : `    assert dp.verifier(preuve, "GET", URI, JETON)[0] == "REFUSEE"` | **REFUTE** |
| **DPoP iat hors fenetre** | `app/forge_dpop.py:448` : `    if abs(maintenant - iat) > _FENETRE_IAT_S:`<br>`app/forge_dpop.py:449` : `        return _refus("iat hors fenetre (%.0f s d'ecart)" % (maintenant - iat))`<br>`app/forge_oauth_route.py:115` : `    if etat != "LIEE":`<br>`app/forge_oauth_route.py:116` : `        return _err(400, "invalid_dpop_proof", "preuve DPoP refusee")`<br>`tests/nr/test_dpop_rfc9449_nr.py:185` : `    assert etat == "REFUSEE" and "fenetre" in raison, (etat, raison)` | **REFUTE** |
| **Jeton de portee SUPERIEURE** | `app/forge_token_exchange.py:107` : `    if not demandees or (pol and not set(demandees) <= set(pol["scopes"])):`<br>`app/forge_token_exchange.py:108` : `        r = _decision(mode, "invalid_scope", "portee hors politique", base)`<br>`app/forge_oauth_route.py:122` : `                      politique or POLITIQUE_DEFAUT, _secret(), "bloquant", now=now)`<br>`app/forge_oauth_route.py:125` : `        return _err(400, c.get("error", "invalid_request"), c.get("error_description", ""))`<br>`tests/test_forge_oauth_route.py:68` : `    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"` | **REFUTE** |
| **Jeton de ring SUPERIEUR** | `app/forge_oauth_route.py:26` : `    "JOB": {"ring": 3, "scopes": ["task:status", "task:assign"], "audiences": ["hub"]},`<br>`app/forge_token_exchange.py:100` : `    pol = (politique or {}).get(sub["ident"])`<br>`app/forge_token_exchange.py:115` : `    jeton = emettre_jeton_lie(sub["ident"], pol["ring"], demandees,`<br>`app/forge_token_exchange.py:64` : `    charge = {"typ": "access", "sub": sujet, "ring": ring, "scope": " ".join(scopes),` | **REFUTE** |
| **Le coffre (secrets au repos / TPM)** | `app/forge_oauth_route.py:37` : `    return get_manager()._secret`<br>Composant materiel/OS de stockage sous-jacent, hors de portee de l'analyse statique du code de la route. | **ILLISIBLE** |
| **Les jetons reels** | `app/forge_oauth_route.py:24` : `OBSERVES: list = []          # journal en memoire : aucune valeur de jeton`<br>`tests/test_forge_oauth_route.py:92` : `    assert jeton not in json.dumps(orr.OBSERVES)`<br>Les jetons de production ne sont ni stockes ni journalises dans le code audite. | **ILLISIBLE** |
| **Le reseau** | `app/forge_oauth_route.py:138` : `    statut, corps, entetes = traiter(request.headers.get("content-type", ""),`<br>Couche transport / intermediaire reseau externe non instrumentee statiquement dans le code. | **ILLISIBLE** |

---

## 3. Analyse detaillee des garanties de securite

### 3.1 Verification de la preuve de possession DPoP (RFC 9449)

La fonction `traiter` dans `app/forge_oauth_route.py` soumet systematiquement l'en-tete `dpop` a une validation prealable bloquante :
1. **Extraction de la cle publique JWK :**
   `app/forge_oauth_route.py:111` : `jwk = _jwk_de_preuve(preuve or "")`
   Si la preuve est absente ou ne contient pas de JWK valide, le traitement s'arrete immediatement :
   `app/forge_oauth_route.py:112-113` :
   ```python
   if jwk is None:
       return _err(400, "invalid_dpop_proof", "preuve DPoP absente (RFC 9449 §5)")
   ```
2. **Verification cryptographique et semantique :**
   `app/forge_oauth_route.py:114` :
   ```python
   etat, _raison = forge_dpop.verifier(preuve, "POST", url, jkt_attendu=forge_dpop.thumbprint(jwk))
   ```
   Tout retour ou `etat != "LIEE"` entraine un rejet HTTP 400 (`app/forge_oauth_route.py:115-116`).
3. **Controles RFC 9449 appliques dans `forge_dpop.verifier` :**
   - **Signature :** verifiee via ECDSA SHA-256 avec la cle publique fournie (`app/forge_dpop.py:470-474`).
   - **Methode HTTP (`htm`) :** `app/forge_dpop.py:438` rejette si `htm != methode.upper()`.
   - **URI (`htu`) :** `app/forge_dpop.py:440` compare les URI normalisees (sans query ni fragment) et rejette en cas d'ecart.
   - **Fenetre temporelle (`iat`) :** `app/forge_dpop.py:448` impose `abs(maintenant - iat) <= _FENETRE_IAT_S` (300 secondes).
   - **Anti-rejeu (`jti`) :** `app/forge_dpop.py:480-482` verifie sous verrou thread-safe l'unicite de `jti` dans la fenetre.

### 3.2 Etancheite de la portee (scope) et du ring (RFC 8693)

Dans `app/forge_token_exchange.py`, la fonction `echanger` est invoquee par `traiter` avec `mode="bloquant"` (`app/forge_oauth_route.py:122`) :
1. **Verification de la portee demandee :**
   `app/forge_token_exchange.py:106-111` :
   ```python
   demandees = [s for s in (scope or "").split() if s]
   if not demandees or (pol and not set(demandees) <= set(pol["scopes"])):
       r = _decision(mode, "invalid_scope", "portee hors politique", base)
       if not r["ok"] or mode != "observation":
           return r
       base["aurait_refuse"] = "invalid_scope"
   ```
   En mode bloquant, `_decision` retourne `{"ok": False, "corps": {"error": "invalid_scope", ...}}` (`app/forge_token_exchange.py:75`). L'appelant ne peut obtenir aucune portee excedant la politique (`["task:status", "task:assign"]` pour `"JOB"` defini a `app/forge_oauth_route.py:26`).
2. **Fixation stricte du ring :**
   Le jeton emis recoit le ring defini par la politique du sujet :
   `app/forge_token_exchange.py:115` :
   ```python
   jeton = emettre_jeton_lie(sub["ident"], pol["ring"], demandees,
                             forge_dpop.thumbprint(dpop_jwk), ttl, secret, now,
                             act={"sub": "job:%s" % sub["job_id"]})
   ```
   Pour le sujet `"JOB"`, `pol["ring"]` vaut strictement `3` (`app/forge_oauth_route.py:26`). L'appelant ne dispose d'aucun parametre pour demander ou influencer le niveau de ring. Aucune elevation vers les rings 0, 1 ou 2 n'est possible.
3. **Lien de parente de processus (PID) :**
   `app/forge_oauth_route.py:117-119` impose que si le job a ete lance par le hub, l'appelant doit appartenir a l'arbre de processus de ce job :
   `app/forge_oauth_route.py:98-99` :
   ```python
   if not _pid_dans_arbre(int(pid_appelant), LIES[ch["job_id"]]):
       return "appelant hors du process lance pour ce job"
   ```

### 3.3 Verification croisee avec `app/forge_auth_tokens.py`

Le mecanisme d'echange / renouvellement dans `app/forge_auth_tokens.py` applique une rigueur similaire :
- `app/forge_auth_tokens.py:343-344` : `if int(ring) < int(courant.ring): ring = courant.ring` interdit toute promotion de ring lors du renouvellement.
- `app/forge_auth_tokens.py:411-412` : tout changement ou elargissement de portee est rejete (`invalid_scope`).
- Si un jeton est lie a une cle DPoP (`cnf.jkt`), la fonction de decodage sous-jacente (`app/forge_integrity.py:523-526`) exige la presentation de la preuve DPoP correspondante, faute de quoi `ValueError` est levee et interceptee en `invalid_grant` (`app/forge_auth_tokens.py:415-416`).

---

## 4. Correctif propose + NR

Aucun cas d'emission abusive de jeton n'a ete **PROUVE**.
Tous les vecteurs d'attaque formules dans la question fermee (DPoP absent, rejoue, mal signe, htm/htu faux, iat hors fenetre, demande de portee superieure ou demande d'elevation de ring) sont **REFUTES** avec preuve textuelle et tests de non-regression a l'appui.

Par consequent, aucun correctif de code ni nouveau test NR n'est necessaire.

---

## 5. Conclusion

La route `POST /oauth/token` implementee dans `app/forge_oauth_route.py` applique de maniere stricte et bloquante la verification de possession DPoP selon la RFC 9449, ainsi que le confinement strict des portees et du ring (fixe a 3) selon la RFC 8693. La question fermee recoit la reponse : **REFUTE** pour l'ensemble des scenarios de vulnerabilite testables.
