# Étude d'état - Supersession du RAG (2026-10-31)

## Méthodologie
Enquête statique sur l'état d'activation des fonctions `superseder` et `retirer_versions_anterieures` dans `app/forge_rag_truth.py`. Recherche d'appels directs et d'interrupteurs conditionnels.

---

## Résultats détaillés

### 1. Appels de `superseder`

| Affirmation | Fichier:Ligne | Extrait copié | État |
|-------------|---------------|---------------|------|
| Appel dans forge_epistemic_extract_claims | tools/forge_epistemic_extract_claims.py:660 | `r = _superseder(c_anc["id"], c_nou["id"], _instant(c_nou), verdict["rationale"])` | PROUVE |
| Appel test dans test_epistemic_emetteurs_nr | tests/nr/test_epistemic_emetteurs_nr.py:129 | `r = verite.superseder("vieux", "neuf", a_partir_de=T1, raison="mesure du jour")` | PROUVE |
| Appel test dans test_verite_temporelle_nr | tests/nr/test_verite_temporelle_nr.py:141 | `verite.superseder("vieux", "neuf", a_partir_de=T1)` | PROUVE |

### 2. Appels de `retirer_versions_anterieures`

| Affirmation | Fichier:Ligne | Extrait copié | État |
|-------------|---------------|---------------|------|
| Appel dans forge_ingest_llms_txt | tools/forge_ingest_llms_txt.py:231 | `n_ret = retirer_versions_anterieures(source, ids_page, conn=conn)` | PROUVE |
| Appel dans forge_memory_ingest via _superseder_les_anciens | tools/forge_memory_ingest.py:169 | `n = retirer_versions_anterieures(source, ids_courants, conn=conn)` | PROUVE |
| Appel dans forge_rag_truth (interne) | app/forge_rag_truth.py:331 | `total += max(0, retirer_versions_anterieures(source, set(), conn=conn))` | PROUVE |

### 3. Interrupteurs conditionnels

| Affirmation | Fichier:Ligne | Extrait copié | État |
|-------------|---------------|---------------|------|
| Variable d'environnement LAFORGE_EPISTEMIC_FERMER | tools/forge_epistemic_extract_claims.py:654 | `elif os.environ.get("LAFORGE_EPISTEMIC_FERMER", "") != "1":` | PROUVE |
| Condition dans _superseder_les_anciens | tools/forge_memory_ingest.py:166 | `except Exception as exc: print("   [!] forge_rag_truth indisponible (%s) — anciens NON traites" % type(exc).__name__)` | PROUVE |

---

## Synthèse des états

### `superseder`
- **Statut**: **ACTIVE** mais SUSPENDUE conditionnellement
- **Appelants**: 1 actif (forge_epistemic_extract_claims) + 2 tests
- **Interrupteur principal**: `LAFORGE_EPISTEMIC_FERMER` (défaut = "0" = suspendu)
- **Comportement**: La fonction est appelée mais exécution bloquée si `LAFORGE_EPISTEMIC_FERMER != "1"`

### `retirer_versions_anterieures`
- **Statut**: **ACTIVE**
- **Appelants**: 3 actifs (forge_ingest_llms_txt, forge_memory_ingest, forge_rag_truth)
- **Interrupteurs**: Aucun interrupteur de désactivation trouvé
- **Comportement**: Toujours exécutée quand appelée, gestion d'erreur par try/catch

---

## Conclusion

La supersession du RAG est **partiellement suspendue**:
- `superseder`: SUSPENUE par `LAFORGE_EPISTEMIC_FERMER=1` (non défini par défaut)
- `retirer_versions_anterieures**: ACTIVE sans condition

Le mécanisme de contrôle repose sur une variable d'environnement qui doit être explicitement positionnée à "1" pour activer la fermeture des assertions contradictoires dans le processus épistémique.