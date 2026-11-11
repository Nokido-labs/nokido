# Enquête : Rouges masqués en CI (run 41915107147)

Date : 2026-11-05
Agent : AGT_ANTIGRAVITY

## Synthèse

Trois tests masqués en CI ont été examinés et traités conformément aux instructions de l'exécuteur.

---

### (a) `test_aucun_import_urllib_dans_le_corps_de_la_fonction`
- **Test** : `tests/nr/test_crawl_tier1_nr.py::test_aucun_import_urllib_dans_le_corps_de_la_fonction`
- **Cause lue** : `app/forge_crawl_tool.py:273` (`from urllib.parse import urlparse as _urlparse` situé dans le corps de `crawl_url_detail`). Cet import local dans le corps rendait le nom global `urllib` local à toute la fonction Python, provoquant `UnboundLocalError` lors des usages plus hauts ou violant l'assertion AST anti-régression.
- **Fichier changé** : `app/forge_crawl_tool.py`
  - Ajout de `import urllib.parse` au niveau module (ligne 16).
  - Remplacement de `from urllib.parse import urlparse as _urlparse` par `_urlparse = urllib.parse.urlparse` dans `crawl_url_detail`.

---

### (b) `test_toute_rfc_citee_par_le_code_est_dans_l_audit_ou_declaree_obsolete`
- **Test** : `tests/nr/test_rfc_citees_par_le_code_dans_l_audit_nr.py::test_toute_rfc_citee_par_le_code_est_dans_l_audit_ou_declaree_obsolete`
- **Cause lue** : `tools/audit_rfc_compliance.py:102` — La RFC 7009 (OAuth 2.0 Token Revocation, citée par le code de sécurité et d'authentification) était absente du dictionnaire `CRITICAL_RFCS` de l'outil d'audit et absente de `RFC_OBSOLETES`.
- **Fichier changé** : `tools/audit_rfc_compliance.py`
  - Ajout de `"RFC 7009",  # revocation de jeton OAuth 2.0` sous la section `"JOSE, jetons et identite des agents (citees par le code)"`.

---

### (c) `test_aucun_nouveau_module_ne_derive_ses_donnees_de_file`
- **Test** : `tests/nr/test_cliquet_racine_donnees_nr.py::test_aucun_nouveau_module_ne_derive_ses_donnees_de_file`
- **Cause lue / Diagnostic** :
  - Le cliquet surveille que le nombre de modules dérivant leurs données de `__file__` (ex. `Path(__file__)` suivi d'une concaténation avec `RAG`, `data`, `logs`, `sandbox` ou `runtime`) ne dépasse pas `PLAFOND["app"] == 244`.
  - La CI rapporte 245 modules sous `app/` pour un plafond de 244 (+1 dépassement).
  - En inspectant les commits récents et les modules sous `app/` (notamment `app/web_hub/acp_views.py` et `app/web_hub/acp_harness.py` qui ont été migrés vers `forge_db_path.racine_donnees()`), l'apparition d'un nouveau module ou d'un fichier dérivant ses données de `__file__` a été identifiée dans l'arbre partagé (ou un module récemment introduit non migré).
  - Conformément à la consigne (« trouve le module nouveau s'il se deduit de la lecture, corrige-le pour qu'il passe par forge_db_path ; ne monte pas le plafond [...] ou NON TROUVE. Si un rouge semble deja corrige sur l'arbre principal, dis-le ») : sans accès shell / git pour lister l'exacte divergence entre les 245 fichiers détectés par le cliquet de la CI et l'arbre, le module spécifique à l'origine du 245ème comptage sous `app/` reste **NON TROUVE** directement depuis le bac à sable contraint (les modules ACP ayant déjà été migrés dans les révisions précédentes, possiblement présent sur l'arbre principal ou dans une branche concurrente).
