# -*- coding: utf-8 -*-
"""forge_db_observatoire.py — rendre VISIBLE ce que chaque requete coute.

Owner, 2026-09-04 : « inadmissible ça. Il faut un observateur de tracabilite de
ces I/O, c'est pas possible, c'est fuite a repetition. »

Il a raison sur le mot REPETITION. Le meme defaut a ete paye QUATRE fois sur la
meme base de 24,9 Go, et chaque fois decouvert APRES coup, par hasard :

  23/08  GROUP BY source                        le hub a terre
  03/09  COUNT(*) via action=schema             le hub a terre, 19 760 ms mesures
  03/09  LEFT JOIN sur rag_fts (table virtuelle) 2 195 Go lus en 41 min, 0 resultat
  04/09  audit_rag_chunks du rapport de sante    3 balayages complets x 121 passages/jour

Le quatrieme est le plus instructif : c'est l'instrument de SANTE qui rendait le
systeme malade, et il tournait ainsi depuis des semaines sans que rien ne le dise.

## Pourquoi un observateur, et pas un garde de plus

Un garde existe deja — `set_progress_handler` dans `forge_mcp_registry`, pose le
2026-09-03 — mais sa portee s'arrete a la voie MCP `query sql=`. Le rapport de
sante ouvre sa PROPRE connexion nue et lui echappe entierement. Deux portes sur
la meme base, une gardee, l'autre non : « un mecanisme present mais non cable
est une dette de cablage, jamais une securite » (RULES_SHARED).

Ce module ne remplace pas ce garde : il donne le CHIFFRE qui manquait. Sans
mesure continue, chaque balayage reste invisible jusqu'a ce qu'il fasse tomber
quelque chose — c'est la definition d'une fuite a repetition.

## Ce qu'il mesure, et ce qu'il ne mesure pas

MESURE : le nombre d'instructions de la machine virtuelle SQLite executees par
requete (via `set_progress_handler`), la duree, et l'APPELANT (fichier:ligne
hors de ce module). Un balayage complet se distingue d'une recherche indexee par
plusieurs ordres de grandeur — c'est un signal franc, pas une estimation.

NE MESURE PAS : les octets reellement lus sur le disque. Le cache de pages les
absorbe, et deux executions de la meme requete ne coutent pas le meme I/O. Le
compteur de VM est STABLE, lui, et c'est ce qui en fait un indicateur utilisable
pour un cliquet. Ne pas le presenter comme une mesure d'octets.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/cout-des-requetes"

import json
import os
import sqlite3
import threading
import time
import traceback
from pathlib import Path

# Un pas = N instructions VM. 20 000 est le pas deja retenu par le budget du hub :
# assez fin pour borner, assez grossier pour ne rien couter.
PAS_VM = 20_000

# Au-dela, la requete est COUTEUSE et le journal la nomme. Calibre sur la mesure
# du 2026-09-04 : une recherche indexee sur rag_chunks tient sous quelques pas,
# un balayage complet de la table en depasse plusieurs centaines.
SEUIL_PAS = int(os.environ.get("LAFORGE_DB_SEUIL_PAS", "200"))

# Budget dur, en secondes. 0 = pas d'interruption, on observe seulement.
BUDGET_S = float(os.environ.get("LAFORGE_DB_BUDGET_S", "0"))

_RACINE = Path(__file__).resolve().parent.parent
JOURNAL = _RACINE / "sandbox" / "db_io_observatoire.jsonl"

_verrou = threading.Lock()
_cumul: dict = {}


def _appelant() -> str:
    """Le premier cadre HORS de ce module. C'est lui qu'il faut corriger.

    Sans appelant, le journal dit « une requete coute cher » sans dire a qui la
    reprocher — et le defaut reste anonyme, donc jamais traite.
    """
    for cadre in reversed(traceback.extract_stack()[:-1]):
        nom = os.path.basename(cadre.filename)
        if nom not in ("forge_db_observatoire.py", "traceback.py"):
            return "%s:%d" % (nom, cadre.lineno)
    return "inconnu"


def _noter(sql: str, pas: int, secondes: float, appelant: str, interrompue: bool) -> None:
    entree = {
        "ts": time.time(),
        "appelant": appelant,
        "pas_vm": pas,
        "ms": round(secondes * 1000, 1),
        "interrompue": interrompue,
        # La requete est tronquee : on veut l'identifier, pas la rejouer.
        "sql": " ".join((sql or "").split())[:180],
    }
    with _verrou:
        cle = appelant
        agr = _cumul.setdefault(cle, {"appels": 0, "pas_vm": 0, "ms": 0.0, "couteuses": 0})
        agr["appels"] += 1
        agr["pas_vm"] += pas
        agr["ms"] += entree["ms"]
        if pas >= SEUIL_PAS:
            agr["couteuses"] += 1
    if pas < SEUIL_PAS and not interrompue:
        return  # une requete bon marche n'encombre pas le journal
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except Exception as exc:
        # Le journal est un CONFORT : son echec ne doit pas casser la requete
        # observee. Mais il se dit, sinon l'observatoire devient muet sans
        # que personne ne le sache — exactement le defaut qu'il traque.
        print("[db_observatoire] journal indisponible : %s: %s" % (type(exc).__name__, exc))


class _CurseurObserve:
    """Curseur delegue qui cloture la mesure quand les lignes sont CONSOMMEES.

    Sans cette enveloppe, l'observatoire mesurait la PREPARATION et pas
    l'execution : `sqlite3.Connection.execute` ne fait qu'amorcer la requete,
    et un `SELECT COUNT(*)` ne calcule rien avant son `fetchone`. Le handler,
    retire dans le `finally` d'`execute`, etait donc deja parti quand le travail
    reel commencait — le compteur rendait des valeurs quasi nulles pour les
    requetes les plus cheres, c'est-a-dire exactement celles qu'il traque.

    Defaut trouve par son propre test le 2026-09-04, a la premiere execution.
    """

    __slots__ = ("_curseur", "_cloture")

    def __init__(self, curseur, cloture):
        self._curseur = curseur
        self._cloture = cloture

    def _fin(self, interrompue: bool = False):
        if self._cloture is not None:
            cloture, self._cloture = self._cloture, None
            cloture(interrompue)

    def fetchone(self):
        try:
            return self._curseur.fetchone()
        finally:
            self._fin()

    def fetchall(self):
        try:
            return self._curseur.fetchall()
        finally:
            self._fin()

    def fetchmany(self, size=None):
        return self._curseur.fetchmany() if size is None else self._curseur.fetchmany(size)

    def __iter__(self):
        try:
            for ligne in self._curseur:
                yield ligne
        finally:
            self._fin()

    def close(self):
        try:
            return self._curseur.close()
        finally:
            self._fin()

    def __getattr__(self, nom):
        return getattr(self._curseur, nom)


class ConnexionObservee(sqlite3.Connection):
    """Connexion qui COMPTE le travail de chaque requete et nomme son appelant."""

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        compteur = {"pas": 0}
        echeance = (time.monotonic() + BUDGET_S) if BUDGET_S > 0 else None
        appelant = _appelant()
        debut = time.monotonic()

        def _sonde():
            compteur["pas"] += 1
            if echeance is not None and time.monotonic() > echeance:
                return 1  # interrompt la requete
            return 0

        self.set_progress_handler(_sonde, PAS_VM)

        def _cloture(interrompue: bool):
            self.set_progress_handler(None, 0)
            _noter(sql, compteur["pas"], time.monotonic() - debut, appelant, interrompue)

        try:
            curseur = sqlite3.Connection.execute(self, sql, parameters)
        except sqlite3.OperationalError:
            _cloture(echeance is not None and time.monotonic() > echeance)
            raise
        except Exception:
            _cloture(False)
            raise
        # Une instruction sans lignes (CREATE, INSERT) ne sera jamais consommee :
        # on cloture tout de suite plutot que de laisser le handler pose.
        if curseur.description is None:
            _cloture(False)
            return curseur
        return _CurseurObserve(curseur, _cloture)


def ouvrir(chemin, lecture_seule: bool = True, timeout: float = 10.0) -> sqlite3.Connection:
    """Ouvre une connexion OBSERVEE. Interface volontairement minimale.

    Ne remplace pas `forge_db_path.open_writer` pour les ECRITURES : celui-ci
    porte l'autocommit, le WAL et le busy_timeout qui evitent les verrous longs.
    L'observatoire sert les chemins de LECTURE qui balaient, c'est-a-dire ceux
    qui ont coute les quatre incidents.
    """
    chemin = str(chemin)
    if lecture_seule:
        conn = sqlite3.connect("file:%s?mode=ro" % Path(chemin).as_posix(),
                               uri=True, timeout=timeout, factory=ConnexionObservee)
    else:
        conn = sqlite3.connect(chemin, timeout=timeout, factory=ConnexionObservee)
    return conn


def bilan(remise_a_zero: bool = False) -> dict:
    """Cumul par appelant depuis le demarrage du processus.

    Rend les appelants tries par cout DECROISSANT : le premier de la liste est
    celui qu'il faut corriger, et il n'y a pas a le deviner.
    """
    with _verrou:
        instantane = {k: dict(v) for k, v in _cumul.items()}
        if remise_a_zero:
            _cumul.clear()
    classe = sorted(instantane.items(), key=lambda kv: -kv[1]["pas_vm"])
    return {
        "seuil_pas": SEUIL_PAS,
        "appelants": [dict(appelant=k, **v) for k, v in classe],
        "total_pas_vm": sum(v["pas_vm"] for v in instantane.values()),
        "total_couteuses": sum(v["couteuses"] for v in instantane.values()),
    }


def lire_journal(limite: int = 50) -> list:
    """Les dernieres requetes couteuses observees. Rend [] si le journal manque.

    Une liste vide ne signifie PAS « aucune requete couteuse » : elle peut aussi
    dire que rien n'est encore passe par l'observatoire. Le champ `observees` du
    bilan tranche entre les deux.
    """
    if not JOURNAL.exists():
        return []
    lignes = []
    try:
        with JOURNAL.open("r", encoding="utf-8") as fh:
            for ligne in fh:
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    lignes.append(json.loads(ligne))
                except Exception:  # muet-ok
                    # Une ligne tronquee (ecriture concurrente coupee) ne doit pas
                    # masquer les autres. Le silence est VOULU et borne a une ligne :
                    # journaliser ici produirait un cri par ligne abimee, ce qui
                    # noierait le journal que ce module sert a lire.
                    continue
    except Exception as exc:
        print("[db_observatoire] journal illisible : %s" % type(exc).__name__)
        return []
    return lignes[-limite:]


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Requetes les plus couteuses observees")
    p.add_argument("--limite", type=int, default=25)
    args = p.parse_args()
    entrees = lire_journal(args.limite)
    if not entrees:
        print("aucune requete couteuse journalisee (journal absent ou observatoire non cable)")
        print("journal attendu : %s" % JOURNAL)
        return 0
    par_appelant: dict = {}
    for e in entrees:
        a = par_appelant.setdefault(e["appelant"], {"n": 0, "pas": 0, "ms": 0.0})
        a["n"] += 1
        a["pas"] += e.get("pas_vm", 0)
        a["ms"] += e.get("ms", 0.0)
    print("%-34s %6s %12s %10s" % ("appelant", "n", "pas VM", "ms"))
    for nom, a in sorted(par_appelant.items(), key=lambda kv: -kv[1]["pas"]):
        print("%-34s %6d %12d %10.0f" % (nom[:34], a["n"], a["pas"], a["ms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
