# Erratum A1 — inventaire des writers de `token_usage`

**Date** : 2026-09-12 · **Porte sur** : l'etape A1 du chantier P0-A
**Ne modifie PAS** `usage_T0_2026-09-12.json`, qui reste le temoin fige des
7839 lignes. Une baseline qu'on reecrit cesse d'etre un T0 : l'erratum vit
donc a cote, date, et c'est lui qui fait foi sur ce point precis.

## Ce qui a change

    A1 initial  : 6 writers
    A1 corrige  : 7 writers
    cause       : sous-detection `INSERT OR ...`

## Les deux sites manques

| fichier | ligne | verbe | pourquoi rate |
|---|---|---|---|
| `app/forge_roles.py` | 256 | `INSERT OR IGNORE INTO` | le scan cherchait le litteral `INSERT INTO` |
| `tools/forge_log_retention.py` | 1249 | *(faux positif, voir plus bas)* | — |

## Et la correction de la correction

Le second passage, elargi aux verbes nus, a produit DEUX faux positifs, tous
deux dans `tools/forge_log_retention.py` :

- une **docstring** disant « Journaux de securite INSERT-only » puis citant le
  FICHIER `sandbox/token_usage.db` — de la prose, pas du SQL ;
- ce fichier porte la table `token_events`, **sans aucun rapport** avec la
  table `token_usage`. Un nom de fichier avait ete pris pour un nom de table.

`forge_log_retention` n'est donc **pas** un writer de `token_usage`. Le compte
exact est :

    7 fichiers touchant token_usage en ecriture ou en DDL,
    dont 1 proprietaire (app/forge_token_monitor.py)
    et 5 sites a raccorder (A3).

Sequence de l'instrument, conservee parce qu'elle est la lecon :

    motif texte -> faux negatif -> motif elargi -> faux positif ->
    clause SQL complete + exclusion des docstrings (AST)

Un « 0 violation » obtenu avec une regex qui ne voit que la moitie du SQL
aurait ferme A3 sur un faux vert. Trois etats valent mieux qu'un chiffre
rassurant : ce NR echoue aussi sur un fichier illisible ou non parsable, et il
affirme son denominateur.

## Regle qui en decoule

    UNIQUE_WRITER(token_usage) = app/forge_token_monitor.py

Verbes surveilles hors proprietaire : INSERT, INSERT OR ..., REPLACE INTO,
UPDATE, DELETE FROM, CREATE TABLE, ALTER TABLE, DROP TABLE.
Cliquet : `tests/nr/test_token_usage_unique_writer_nr.py`.
