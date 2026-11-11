# Enquete : Rouge masque sur `test_soif_pistes_methodes_nr.py` (2026-11-05)

## 1. Symptome
Dans `tests/nr/test_soif_pistes_methodes_nr.py`, les tests `test_lacune_stagnante_lance_des_veilles_officielles_et_le_note` et `test_le_demon_lance_les_pistes_apres_les_remesures` echouaient intermittamment avec `0` pistes lancees pour `>= 2` attendues.

## 2. Cause racine
Dans `forge_epistemic_veille.lancer_pistes`, un garde metabolique verifie la tension de l'hote :
```python
tendu, raison = corps_sous_tension()
if tendu:
    ...
    return {"lancees": 0, "differe": "DIFFERE_METABOLIQUE", "motif": raison}
```
Quand la machine reellement sous charge/tension execute le test, `corps_sous_tension()` renvoie `(True, ...)`. La fonction differe alors le lancement des pistes en renvoyant `lancees: 0`, provoquant l'echec de l'assertion `assert r["lancees"] == len(crees) >= 2`.

C'est exactement la meme cause que celle identifiee et corrigee dans `tests/nr/test_soif_interne_depose_enquete_code_nr.py` (commit `225140445`).

## 3. Resolution
Dans `tests/nr/test_soif_pistes_methodes_nr.py`, isolation hermetique via `monkeypatch` dans le helper `_lacunes` appele par les deux tests :
```python
monkeypatch.setattr(ev, "corps_sous_tension", lambda: (False, "test"))
```
Le test est rendu hermetique a la charge reelle de l'hote sans alterer ce qu'il valide (comportement normal hors tension metabolique).
