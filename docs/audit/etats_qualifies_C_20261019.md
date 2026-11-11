# Rapport d'enquête - États qualifiés C (audit pair)

**Date :** 2026-10-19
**Type :** Audit pair
**Bilan :** 3 cas graves identifiés où « non » (liste vide, score 0.0, tier "none") est confondu avec « inconnu / illisible ».

---

## Constitution du problème

Doctrine : `UNKNOWN != NO`, `ILLISIBLE` jamais rangé du côté sain.

1. **Except qui rend False/0/[]**
2. **Seuil compare à une valeur par défaut**
3. **Source muette lue comme « rien à signaler »**

---

## Module : `forge_curiosity_driver.py`

### 1. `detect_stack_gaps()` - ligne 565-617

**Retour actuel :** `[]` si `stack_versions.json` ne peut être lu ou si `db_path()` échoue.

**État honnête proposé :** `ILLISIBLE` (panne technique, pas absence de gap)

**Appelants réels :**
- `forge_curiosity_driver.py:330` - `gaps.extend(detect_stack_gaps())`

**Problème :** Quand le fichier de versions n'est pas lisible, on ajoute une liste vide à `gaps`. Le cycle de curiosité n'en voit pas de différence, donc il ne lance pas de veille. Mais en réalité, on a simplement pas vérifié les gaps de stack.

**Test RED :** `tests/nr/test_detect_stack_gaps_empty.md`

---

### 2. `detect_self_gaps()` - ligne 524-560

**Retour actuel :** Liste avec gap illisible (`n: 0`) quand `regulation_gaps()` lève une exception ou retourne `None`.

**État honnête proposé :** `ILLISIBLE` (panne du capteur de soi)

**Appelants réels :**
- `forge_curiosity_driver.py:330` - `gaps.extend(detect_self_gaps())`

**Problème :** L'exception est transformée en un gap avec `n: 0`, ce qui est indiscernable d'un vrai gap (qui aurait `n > 0`). Le code le documente comme intentionnel (« l'échec du capteur EST une lacune »), mais ça confond « panne technique » avec « lacune réelle ».

**Test RED :** `tests/nr/test_detect_self_gaps_error.md`

---

### 3. `coverage_score()` - ligne 782-807

**Retour actuel :** `{"ok": False, "gap": None}` si `preflight_check_verbose()` lève une exception.

**État honnête proposé :** `ILLISIBLE` (panne RAG)

**Appelants réels :**
- `forge_epistemic_veille.py:296` - `cov = coverage_score(q, context)`

**Problème :** Quand `preflight_check_verbose()` lève une exception, la fonction capture l'exception et renvoie `{"ok": False, "gap": None}`. L'appelant (`coverage_score`) renvoie `None` pour `gap`, ce qui est interprété comme « inconnu » et non comme « panne ».

**Test RED :** `tests/nr/test_coverage_score_error.md`

---

## Module : `forge_self_correction.py`

### 1. `preflight_check_verbose()` - ligne 402-429

**Retour actuel :** `{"results": [], "tier": "none"}` quand tous les niveaux échouent.

**État honnête proposé :** `ILLISIBLE` (panne RAG)

**Appelants réels :**
- `forge_epistemic_veille.py:296` - `v = preflight_check_verbose(q, context)`
- `forge_dsl.py:200` - `v = preflight_check_verbose(q, "")`
- `forge_extern_patterns.py:260` - `res = preflight_check_verbose(query, context=...)`
- `forge_grounder.py:140` - `v = preflight_check_verbose(claim, "")`

**Problème :** Quand tous les niveaux (RAGEngine, FTS5, LIKE) échouent, on renvoie une liste vide. Les appelants vérifient souvent `if results:` ou `if results: break`, et ils pensent qu'il y a des résultats. Mais en réalité, aucun niveau n'a fonctionné.

**Test RED :** `tests/nr/test_preflight_check_verbose_empty.md`

---

### 2. `_fts5_search()` - ligne 175-213

**Retour actuel :** `[]` si la connexion échoue ou la query échoue.

**État honnête proposé :** `ILLISIBLE` (panne FTS5)

**Appelants réels :**
- `preflight_check()` - utilise `_fts5_search()` comme fallback

**Problème :** Si FTS5 échoue, on ajoute la panne à `pannes` mais on renvoie quand même une liste vide. Si RAGEngine a aussi échoué, on renvoie un message d'erreur dans `preflight_check()`, mais si seulement FTS5 a échoué, on renvoie une liste vide.

**Test RED :** `tests/nr/test_fts5_search_error.md`

---

## Module : `forge_metacognition_gate.py`

### 1. `ConfidenceScorer.score()` - ligne 175-230

**Retour actuel :** `SiloScore(0.0, 0, -0.30, 0.0, 0.0)` pour une réponse vide ou qui commence par un pattern de refus.

**État honnête proposé :** `UNKNOWN` (réponse vide ou refus - pas de confiance)

**Appelants réels :**
- `forge_arbitrator.py:146` - `_silo = _gs.score(response)`
- `forge_dialogue_outcome.py:72` - `intr = float(ConfidenceScorer().score(assistant_msg).final_score)`
- `forge_metacognition_gate.py:509` - `score_obj = self._scorer.score(response)`

**Problème :** Si la réponse est vide ou commence par un pattern de refus, on renvoie un score de 0.0. Dans `forge_arbitrator.py:150`, ce score déclenche une escalade (`needs = _silo.final_score < 0.60`). Mais le commentaire dans `ConfidenceScorer` dit « PARLER d'une erreur n'est pas ETRE une erreur ». Donc un score 0.0 pour un refus est intentionnel, mais il déclenche quand même une escalade, ce qui est contradictoire.

**Test RED :** `tests/nr/test_confidence_scorer_zero.md`

---

### 2. `MetaCognitionGate.process()` - ligne 517

**Retour actuel :** Sort de la boucle avec un score 0.0 si le tier est max.

**État honnête proposé :** `BLOQUE` (si le tier est max, on accepte le résultat même s'il est faible)

**Appelants réels :**
- `forge_metacognition_gate.py:509` - `score_obj = self._scorer.score(response)`

**Problème :** Si `score_obj.final_score >= self.spin_threshold` ou `tier >= len(MODEL_TIERS) - 1`, on sort de la boucle. Si le tier est max (3) et le score est 0.0, on sort de la boucle et on accepte le résultat. Mais si le tier n'est pas max, un score 0.0 provoquera une escalade. Ce comportement est documenté, mais il confond « confiance faible » avec « confiance nulle ».

**Test RED :** `tests/nr/test_gate_process_zero_score.md`

---

## Cas les plus graves

### Cas 1 : `forge_arbitrator.py:150` - Score 0.0 déclenche une escalade

**Fichier :** `app/forge_arbitrator.py`
**Ligne :** 150
**Retour :** `_silo.final_score` (0.0 pour réponse vide ou refus)
**Appelant :** `forge_arbitrator.py:150` - vérifie `if _silo.final_score < 0.60`

**Test RED :** `tests/nr/test_arbitrator_zero_score.md`

---

### Cas 2 : `preflight_check_verbose()` - Liste vide quand tous les niveaux échouent

**Fichier :** `app/forge_self_correction.py`
**Ligne :** 426-429
**Retour :** `{"results": [], "tier": "none"}` quand tous les niveaux échouent
**Appelant :** Plusieurs modules vérifient `if results:` ou `if results: break`

**Test RED :** `tests/nr/test_preflight_check_verbose_empty.md`

---

### Cas 3 : `detect_stack_gaps()` - Liste vide quand `stack_versions.json` ne peut être lu

**Fichier :** `app/forge_curiosity_driver.py`
**Ligne :** 565-617
**Retour :** `[]` si le fichier ne peut être lu ou si `db_path()` échoue
**Appelant :** `forge_curiosity_driver.py:330` - `gaps.extend(detect_stack_gaps())`

**Test RED :** `tests/nr/test_detect_stack_gaps_empty.md`

---

## Conclusion

Trois cas graves identifiés où « non » (liste vide, score 0.0, tier "none") est confondu avec « inconnu / illisible » :

1. **Score 0.0** dans `forge_arbitrator.py` déclenche une escalade inutile.
2. **Liste vide** dans `preflight_check_verbose()` quand tous les niveaux échouent est interprétée comme absence de résultats.
3. **Liste vide** dans `detect_stack_gaps()` quand `stack_versions.json` ne peut être lu est interprétée comme absence de gap.

Ces cas doivent être corrigés pour distinguer clairement « non » (absence réelle) et « inconnu / illisible » (panne technique).
