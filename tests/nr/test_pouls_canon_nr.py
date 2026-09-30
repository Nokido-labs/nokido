# -*- coding: utf-8 -*-
"""NR — CLIQUET : aucun nouvel ecrivain de pouls hors du chemin canonique.

`forge_heartbeat.beat_daemon` est le chemin UNIQUE d'ecriture d'un pouls. Le
recensement du 2026-07-28 avait trouve 39 reimplementations maison ; la migration du
2026-09-05 en a repris 20, et ce cliquet interdit a la dette de remonter.

POURQUOI CE CLIQUET EXISTE — la mesure, pas le principe. Une ecriture maison
n'inscrit pas le `pid` : le pouls atteste alors d'une vie sans dire QUI la porte.
Consequence mesuree le 2026-09-05 : 24 pouls sur 49 sans pid, donc la moitie de la
flotte sans hote attribuable, donc `forge_nervous_map.autorites()` incapable de dire
sous quelle autorite vit l'organe. Certaines de ces ecritures ne produisaient meme pas
du JSON (`organ_afferent` ecrivait `str(time.time())`, `harness_worker` une date ISO
nue) alors que `proxy_deno/core/service_loader.ts` declare un fichier JSON : elles
etaient donc ILLISIBLES au contrat.

CE QUE CE TEST NE MESURE PAS, ET POURQUOI. `tools/forge_signal_graph` compte
`beat_daemon` parmi ses `WRITE_HELPERS` : il repond « qui ecrit un pouls », pas « qui
l'ecrit A LA MAIN ». Utilise tel quel comme cliquet, il rendait 51 avant ET apres la
migration de vingt modules — un compteur insensible a ce qu'il est cense mesurer. Le
detecteur ci-dessous cherche donc l'ecriture BRUTE : un nom lie a un litteral
`*.heartbeat` qui recoit `write_text` / `write_bytes` / `touch`, ou qui part dans un
`open(..., "w")`.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files (l.59)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CANON = "app/forge_heartbeat.py"
METHODES_ECRITURE = {"write_text", "write_bytes", "touch"}

# CLIQUET. Il ne peut que DESCENDRE a portee de detecteur CONSTANTE. Le baisser en
# meme temps qu'on migre fait partie du travail ; le remonter demande de justifier
# pourquoi un organe doit reimplementer un geste que le corps tient a un seul endroit.
#
# HISTORIQUE, parce qu'un chiffre qui bouge doit dire POURQUOI :
#   43  mesure initiale (2026-09-05, avant migration)
#   23  apres migration de 20 ecrivains vers `beat_daemon`
#   25  MEME JOUR, sans qu'aucune dette ne revienne : le detecteur a gagne la
#       detection des noms CONSTRUITS (f-strings), qui lui echappaient entierement.
#       `nokido_hub` et `forge_peer_discovery` etaient donc deja la, invisibles.
#       Une mesure qui s'elargit n'est PAS une dette qui monte — mais taire la
#       difference reviendrait a maquiller l'un en l'autre.
PLAFOND_ECRIVAINS_BRUTS = 25


def _fichiers_suivis() -> list[str]:
    """Frontiere = ce que git SUIT. `os.walk` ramasse des copies et des datasets."""
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--",
         "app/*.py", "tools/*.py"],
        capture_output=True, text=True, errors="replace", timeout=120)
    if out.returncode != 0:
        pytest.skip("git ls-files indisponible : perimetre NON etabli, "
                    "un cliquet sur une frontiere inconnue ne prouve rien")
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def _ecriture_brute(rel: str):
    """Lignes d'ecriture MANUELLE d'un pouls. `None` = fichier ILLISIBLE.

    Trois etats, jamais deux : un fichier qu'on n'a pas pu analyser n'est pas un
    fichier sans dette — sinon la couverture est surestimee en silence.
    """
    try:
        arbre = ast.parse((ROOT / rel).read_text("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return None
    pouls = set()
    nom_construit = False
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and n.targets:
            if ".heartbeat" in ast.unparse(n.value):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        pouls.add(t.id)
        # ANGLE MORT FERME LE 2026-09-05. `forge_task_executor` ecrivait TROIS pouls
        # (`task_executor`, `_worker_code`, `_antigravity`) via
        # `SANDBOX / f"task_executor_{slug}.heartbeat"`, puis `_hb.write_text(...)` ou
        # `_hb` vient d'un APPEL et non d'un litteral : le detecteur ne voyait rien,
        # et ces trois organes echappaient au cliquet comme ils echappaient a l'atlas.
        # Un nom construit a l'execution reste un nom de pouls.
        if isinstance(n, ast.JoinedStr) and ".heartbeat" in ast.unparse(n):
            nom_construit = True
    if not pouls and not nom_construit:
        return []
    sites = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in METHODES_ECRITURE:
            base = f.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and (base.id in pouls or nom_construit):
                sites.append(n.lineno)
        elif isinstance(f, ast.Name) and f.id == "open" and n.args:
            a0 = n.args[0]
            if isinstance(a0, ast.Name) and a0.id in pouls:
                mode = ast.unparse(n.args[1]) if len(n.args) > 1 else ""
                if "w" in mode or "a" in mode:
                    sites.append(n.lineno)
    return sorted(set(sites))


def _recensement() -> tuple[dict, list]:
    bruts, illisibles = {}, []
    for rel in _fichiers_suivis():
        if rel == CANON:
            continue
        sites = _ecriture_brute(rel)
        if sites is None:
            illisibles.append(rel)
        elif sites:
            bruts[rel] = sites
    return bruts, illisibles


def test_cliquet_ecrivains_de_pouls_hors_canon():
    bruts, illisibles = _recensement()
    assert not illisibles, (
        "%d fichier(s) ILLISIBLE(S) : la dette est SOUS-estimee, le cliquet ne "
        "prouve rien -> %s" % (len(illisibles), illisibles[:5]))
    assert len(bruts) <= PLAFOND_ECRIVAINS_BRUTS, (
        "la dette de pouls REMONTE : %d ecrivains bruts pour un plafond de %d. "
        "Un pouls s'ecrit par `forge_heartbeat.beat_daemon`, seul chemin qui inscrit "
        "le pid — sans lui l'organe bat sans porteur attribuable.\nNouveaux : %s"
        % (len(bruts), PLAFOND_ECRIVAINS_BRUTS, sorted(bruts)))


def test_cliquet_est_serre_sur_la_mesure():
    """Un cliquet trop lache ne cliquette pas : il doit coller a la mesure.

    Sans ce test, on pourrait migrer dix modules sans jamais descendre le plafond, et
    le garde laisserait revenir dix dettes sans rien dire.
    """
    bruts, _ = _recensement()
    assert len(bruts) >= PLAFOND_ECRIVAINS_BRUTS - 2, (
        "le plafond (%d) est LARGE de %d par rapport a la mesure (%d) : le descendre, "
        "sinon la dette peut revenir sans declencher le garde"
        % (PLAFOND_ECRIVAINS_BRUTS, PLAFOND_ECRIVAINS_BRUTS - len(bruts), len(bruts)))


def test_beat_daemon_inscrit_pid_et_horodatage(tmp_path, monkeypatch):
    """Le contrat du canon : `pid` + `ts`, et la charge de l'appelant preservee.

    `_ROOT` est deplace vers un dossier temporaire, et la sonde de couplage est
    neutralisee : ce test ne doit ni fabriquer un organe dans `sandbox/` — le
    diagnostic enumere ce dossier et y verrait un organe vivant — ni polluer le
    registre des signaux.
    """
    import forge_heartbeat as fh
    import forge_signal_coupling as fsc

    monkeypatch.setattr(fh, "_ROOT", tmp_path)
    monkeypatch.setattr(fsc, "emit_signal", lambda *a, **k: True)

    assert fh.beat_daemon("organe_de_test", note="essai", n=3) is True
    ecrit = tmp_path / "sandbox" / "organe_de_test.heartbeat"
    assert ecrit.exists(), "le pouls n'a pas ete ecrit sous la racine deplacee"
    charge = __import__("json").loads(ecrit.read_text(encoding="utf-8"))
    assert charge.get("pid"), "pas de pid : c'est precisement ce qui rend un organe " \
                              "inattribuable"
    assert charge.get("ts"), "pas d'horodatage"
    assert charge.get("note") == "essai" and charge.get("n") == 3, \
        "la charge de l'appelant doit survivre a la centralisation"


def test_beat_daemon_ne_leve_jamais(tmp_path, monkeypatch):
    """Invariant : echec de la sonde != echec du heartbeat, et jamais d'exception.

    Une charge non serialisable passait chez plusieurs implementations maison grace a
    `default=str` ; le canon doit accepter ce que les variantes acceptaient, sinon
    centraliser DEGRADE.
    """
    import forge_heartbeat as fh
    import forge_signal_coupling as fsc

    monkeypatch.setattr(fh, "_ROOT", tmp_path)

    def _sonde_qui_casse(*a, **k):
        raise RuntimeError("registre de couplage indisponible")

    monkeypatch.setattr(fsc, "emit_signal", _sonde_qui_casse)

    class Opaque:
        def __repr__(self):
            return "<opaque>"

    assert fh.beat_daemon("organe_de_test", objet=Opaque()) is True, \
        "une sonde qui casse ne doit PAS faire echouer le pouls"
    ecrit = tmp_path / "sandbox" / "organe_de_test.heartbeat"
    assert "<opaque>" in ecrit.read_text(encoding="utf-8")
