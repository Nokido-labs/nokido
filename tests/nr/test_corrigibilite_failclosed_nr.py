"""NR — le kill-switch humain ne se desarme pas en devenant illisible.

MESURE DU 2026-09-12 qui a motive ce test. Le dispatch MCP consulte
`forge_corrigibility.corrigibility_gate`, qui consulte `forge_opsec`. Sur ce
chemin, QUATRE fail-open etaient empiles sur le meme signal :

  1. `forge_opsec.is_human_locked`      : `except Exception: return False`
  2. `corrigibility_gate`, lock illisible : `except Exception: pass`
  3. `corrigibility_gate`, enveloppe      : `except Exception: return (True, "")`
  4. `forge_mcp_registry`, dispatch       : `except Exception: pass`

Aucune des quatre ne journalisait. Consequence : rendre la base illisible
(ACL, corruption, verrou) desarmait l'interrupteur d'arret humain SANS laisser
la moindre trace. `UNKNOWN` valait `AUTORISE`, sur le garde ou cette direction
coute le plus cher.

CE QUE CE TEST NE DEMONTRE PAS — a lire avant de s'en rassurer :
  - il ne prouve PAS que le client ne peut pas ECRIRE `human_locked=0`.
    Mesure du meme jour : l'etat vit dans `RAG/embeddings.db`, le compte
    client y obtient le verrou d'ecriture, aucun trigger ne protege
    `opsec_state`. Ce NR ferme le desarmement par ILLISIBILITE, pas le
    desarmement par ECRITURE, qui reste OUVERT et demande de sortir l'etat
    de cette base (action owner : ACL + infrastructure).
  - il ne prouve PAS que le miroir `nokido_persist/state.json` soit une
    autorite de repli : il est dans le depot et inscriptible par le client,
    donc du MEME domaine de confiance. S'y replier serait un faux correctif.
  - il lit le code du dispatch par le TEXTE (le hub tourne en memoire sur
    l'ancien code jusqu'a son redemarrage) : il atteste la SOURCE, pas
    l'effet runtime courant.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REGISTRE = RACINE / "app" / "forge_mcp_registry.py"

opsec = pytest.importorskip("nokido_agent.app.forge_opsec")
corrig = pytest.importorskip("nokido_agent.app.forge_corrigibility")


ETATS = ("VERROUILLE", "NON_VERROUILLE", "ILLISIBLE")


def test_le_capteur_expose_trois_etats():
    """vrai / faux / illisible — jamais deux."""
    assert hasattr(opsec, "human_lock_state"), (
        "forge_opsec n'expose pas human_lock_state : le capteur ne peut pas "
        "distinguer 'pas verrouille' de 'je n'ai pas pu lire'")
    etat, motif = opsec.human_lock_state()
    assert etat in ETATS, "etat hors contrat: %r" % (etat,)
    assert isinstance(motif, str)


def test_base_illisible_rend_illisible_pas_non_verrouille(tmp_path, monkeypatch):
    """Le coeur du defaut : une base qu'on ne peut pas lire disait 'ouvert'."""
    faux = tmp_path / "pas_une_base"
    faux.mkdir()  # sqlite3.connect sur un DOSSIER echoue de facon deterministe
    monkeypatch.setattr(opsec, "DEFAULT_DB", faux, raising=False)
    etat, motif = opsec.human_lock_state()
    assert etat == "ILLISIBLE", (
        "base illisible lue comme %r : le kill-switch se desarme en silence" % (etat,))
    assert motif.strip(), "un etat ILLISIBLE sans motif n'est pas diagnosticable"


def test_le_contrat_booleen_des_huit_consommateurs_est_preserve(tmp_path, monkeypatch):
    """8 appelants lisent is_human_locked() comme un bool : ne pas les casser."""
    faux = tmp_path / "pas_une_base"
    faux.mkdir()
    monkeypatch.setattr(opsec, "DEFAULT_DB", faux, raising=False)
    v = opsec.is_human_locked()
    assert isinstance(v, bool), (
        "is_human_locked doit rester un bool : forge_circadian, "
        "forge_docker_monitor, forge_service_watchdog, forge_skill_policy et "
        "forge_corrigibility l'appellent tels quels")


def test_illisible_refuse_un_tool_mutant(tmp_path, monkeypatch):
    faux = tmp_path / "pas_une_base"
    faux.mkdir()
    monkeypatch.setattr(opsec, "DEFAULT_DB", faux, raising=False)
    ok, raison = corrig.corrigibility_gate("governed_edit", "CLAUDE", 1)
    assert ok is False, (
        "tool MUTANT autorise alors que l'etat du kill-switch est illisible")
    assert "ILLISIBLE" in raison.upper() or "illisible" in raison, (
        "le refus doit NOMMER la cause, sinon il est indiagnosticable: %r" % (raison,))


def test_illisible_laisse_passer_le_read_only(tmp_path, monkeypatch):
    """Doctrine du module : read-only reste permis, l'humain doit pouvoir inspecter.

    Controle POSITIF : sans lui, un garde qui refuse TOUT passerait le test
    precedent sans rien prouver.
    """
    faux = tmp_path / "pas_une_base"
    faux.mkdir()
    monkeypatch.setattr(opsec, "DEFAULT_DB", faux, raising=False)
    ok, _ = corrig.corrigibility_gate("read", "CLAUDE", 1)
    assert ok is True, (
        "read-only refuse : on retire a l'humain le moyen d'inspecter "
        "pendant l'incident")


def test_le_dispatch_ne_tait_plus_la_panne_du_garde():
    if not REGISTRE.is_file():
        pytest.skip("registre absent: %s" % REGISTRE)
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    i = src.find("corrigibility_gate")
    assert i != -1, "le garde de corrigibilite a disparu du dispatch"
    # BORNE EXACTE : le bloc suivant dans le dispatch est le gate d'intention,
    # qui porte son PROPRE fail-open. Il est declare WARN-mode, c'est un point
    # ouvert DISTINCT — ce test ne le juge pas, et ne doit pas l'attraper par
    # debordement de fenetre, sinon il rapporte un defaut qu'il ne mesure pas.
    j = src.find("Gate d'intention", i)
    fin = j if j != -1 else i + 2500
    bloc = src[i:fin]
    m = re.search(r"except Exception[^\n:]*:\s*\n\s*pass\b", bloc)
    assert not m, (
        "le dispatch avale encore la panne du garde de corrigibilite en "
        "silence : la disparition du kill-switch doit etre AUDIBLE")
    assert "critical" in bloc.lower(), (
        "aucune journalisation CRITICAL autour du garde de corrigibilite")


def test_la_liste_de_repli_du_dispatch_reste_synchrone():
    """Le repli du dispatch duplique MUTATING_TOOLS : le verrouiller ici.

    Une duplication non testee derive ; testee, elle est une redondance
    deliberee. C'est le seul moyen pour le dispatch de refuser les mutants
    quand le module du garde est lui-meme inatteignable.
    """
    if not REGISTRE.is_file():
        pytest.skip("registre absent: %s" % REGISTRE)
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    # L'annotation de type est admise, mais PAS un `[^=]*` permissif : l'usage
    # `self._CORRIGIBILITE_MUTANTS_REPLI` apparait AVANT la declaration dans le
    # fichier (dispatch L~730, attribut de classe L~1050), et un motif lache
    # ferait le pont de l'un a l'autre en croyant lire la declaration.
    m = re.search(
        r"_CORRIGIBILITE_MUTANTS_REPLI\s*(?::\s*frozenset\s*)?=\s*"
        r"frozenset\(\s*\((.*?)\)\s*\)", src, re.S)
    assert m, ("le dispatch ne declare pas _CORRIGIBILITE_MUTANTS_REPLI : sans "
               "elle, une panne d'import du garde ne peut refuser que tout ou rien")
    noms = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    attendu = set(corrig.MUTATING_TOOLS)
    assert noms == attendu, (
        "repli desynchronise de MUTATING_TOOLS.\n  en trop: %s\n  manquants: %s"
        % (sorted(noms - attendu), sorted(attendu - noms)))
