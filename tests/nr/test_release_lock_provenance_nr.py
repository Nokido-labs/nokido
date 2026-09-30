"""NR — provenance cryptographique du verrou de composition.

Ce qu'on protege : un verrou signe doit se verifier VALIDE, et TOUTE retouche de
son contenu (un SHA change a la main) ou de sa signature doit etre detectee. Un
sceau qui ne detecte pas la falsification ne vaut rien -- c'est le faux-vert que
tout le reste du fichier combat, applique a la cryptographie.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.348)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

_VERROU = {
    "schema": 1,
    "emis_le": "2026-08-15T12:00:00",
    "gate": "PASS",
    "note": "test",
    "workspace": "a" * 40,
    "components": {
        "Nokido": {"sha": "b" * 40, "etat": "ok"},
        "netcfg-agent": {"sha": "c" * 40, "etat": "ok"},
    },
}


@pytest.fixture
def signeur_hmac(monkeypatch):
    """Signeur HERMETIQUE : pas de TPM, cle HMAC de test.

    Depuis 2b-1 (2026-09-28) la cle persona est illisible, en echec ferme, pour tout compte
    autre que son proprietaire -- `_sign_provenance` rend alors `scheme: none`, et c'est
    voulu. Ces tests prouvent la DETECTION de falsification, pas l'acces a la cle : ils
    lisaient la vraie cle et sont tombes en CI (36440801595, compte user). On leur
    donne donc leur propre signeur, comme les tests TPM plus bas.
    """
    import forge_release_lock as R

    monkeypatch.setattr(R, "_persona_signer",
                        lambda: (lambda _p: None, lambda _p, _s: False, lambda: b"cle-hmac-de-test-nr"))
    return R


def test_sans_cle_lisible_le_verrou_porte_son_empreinte_et_se_dit_non_signe(monkeypatch):
    """Le comportement REEL d'un compte sans acces a la cle (2b-1) : empreinte posee,
    `scheme: none` DIT, et la verification rend ABSENTE -- jamais VALIDE."""
    import forge_release_lock as R

    def _illisible():
        raise RuntimeError("cle persona illisible")

    monkeypatch.setattr(R, "_persona_signer", lambda: (lambda _p: None, lambda _p, _s: False, _illisible))
    v = copy.deepcopy(_VERROU)
    v["provenance"] = R._sign_provenance(v)
    assert v["provenance"]["scheme"] == "none" and v["provenance"]["digest"]
    assert R._verify_provenance(v)["etat"] == "ABSENTE"


def test_un_verrou_signe_se_verifie_valide(signeur_hmac):
    R = signeur_hmac

    v = copy.deepcopy(_VERROU)
    v["provenance"] = R._sign_provenance(v)
    assert v["provenance"]["scheme"] in ("tpm-ecdsa-p256", "hmac-sha256")
    assert v["provenance"]["digest"]
    assert R._verify_provenance(v)["etat"] == "VALIDE"


def test_un_sha_change_a_la_main_est_detecte_falsifie(signeur_hmac):
    """Le coeur de la provenance : editer un SHA du verrou apres coup casse
    l'empreinte, donc la verification, meme sans toucher la signature."""
    R = signeur_hmac

    v = copy.deepcopy(_VERROU)
    v["provenance"] = R._sign_provenance(v)
    v["components"]["Nokido"]["sha"] = "0" * 40  # livrer autre chose en douce
    assert R._verify_provenance(v)["etat"] == "FALSIFIEE"


def test_une_signature_bidouillee_est_invalide(signeur_hmac):
    R = signeur_hmac

    v = copy.deepcopy(_VERROU)
    v["provenance"] = R._sign_provenance(v)
    sig = v["provenance"]["sig"]
    # flip un caractere hex sans changer la longueur -> empreinte intacte, sig KO
    autre = "f" if sig[-1] != "f" else "e"
    v["provenance"]["sig"] = sig[:-1] + autre
    assert R._verify_provenance(v)["etat"] == "INVALIDE"


def test_le_gate_fait_partie_du_scelle(signeur_hmac):
    """Repasser un verrou FAIL en PASS a la main doit casser l'empreinte :
    l'attestation porte AUSSI le verdict du gate, pas seulement les SHA."""
    R = signeur_hmac

    v = copy.deepcopy(_VERROU)
    v["provenance"] = R._sign_provenance(v)
    v["gate"] = "FAIL"
    assert R._verify_provenance(v)["etat"] == "FALSIFIEE"


def test_verrou_sans_provenance_rend_absente_jamais_valide():
    import forge_release_lock as R

    v = copy.deepcopy(_VERROU)
    assert R._verify_provenance(v)["etat"] == "ABSENTE"
    v["provenance"] = {"scheme": "none", "digest": "x", "raison": "pas de signeur"}
    assert R._verify_provenance(v)["etat"] == "ABSENTE"


def _verrou_tpm_scelle():
    """Un verrou dont l'empreinte est correcte et le scheme = tpm, sig bidon."""
    import forge_release_lock as R

    v = copy.deepcopy(_VERROU)
    digest = __import__("hashlib").sha256(R._provenance_payload(v)).hexdigest()
    v["provenance"] = {"scheme": "tpm-ecdsa-p256", "digest": digest, "sig": "ab" * 32}
    return v


def test_cle_tpm_inaccessible_rend_indetermine_pas_invalide(monkeypatch):
    """Un compte sans ACL sur la cle machine ne peut pas verifier : c'est
    INDETERMINE (defaut d'acces), jamais INVALIDE (accusation de falsification).
    L'empreinte a deja garanti que le contenu n'a pas bouge."""
    import forge_release_lock as R

    # signer dont _sign rend None (pas d'acces cle), _verify rend False
    monkeypatch.setattr(R, "_persona_signer",
                        lambda: (lambda _p: None, lambda _p, _s: False, lambda: b"k"))
    r = R._verify_provenance(_verrou_tpm_scelle())
    assert r["etat"] == "INDETERMINE"


def test_signature_tpm_reellement_fausse_rend_invalide(monkeypatch):
    """Acces OK (probe signe) mais signature qui ne verifie pas = INVALIDE."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "_persona_signer",
                        lambda: (lambda _p: b"sig", lambda _p, _s: False, lambda: b"k"))
    r = R._verify_provenance(_verrou_tpm_scelle())
    assert r["etat"] == "INVALIDE"


# ── composition() : ce que le verrou FIGE ────────────────────────────────────
# MESURE 2026-08-18 : 10 mutants sur 14 survivaient ici. Les tests couvraient la
# signature (scelle, TPM, falsification) mais jamais la LECTURE de l'etat du
# depot — or c'est elle qui decide si un composant est `ok`, `non_verifie` ou
# `desynchronise`. Muter `==` en `!=` sur cette comparaison faisait passer une
# absence de mesure pour une conformite, sans qu'un seul test bronche.

class _Rep:
    """Reponse de _git : (rc, sortie)."""

    def __init__(self, rc=0, out=""):
        self.rc, self.out = rc, out


def _faux_git(table, journal=None):
    def _appel(*args, cwd=None):
        if journal is not None:
            journal.append((args, cwd))
        for cle, rep in table.items():
            if cle in args:
                return (rep.rc, rep.out)
        return (0, "")
    return _appel


GITLINK = "160000 commit " + "a" * 40 + "\tNokido"


def test_un_head_illisible_rend_None_jamais_zero(monkeypatch):
    import forge_release_lock as R

    monkeypatch.setattr(R, "_git", _faux_git({"rev-parse": _Rep(128, "")}))
    assert R.composition()["workspace"] is None


def test_un_composant_dont_le_checkout_est_illisible_n_est_jamais_ok(monkeypatch):
    """Premiere emission 2026-08-14 : cinq composants sur six avaient
    sha_checkout=null et s'affichaient `ok` — une absence de mesure presentee
    comme une conformite."""
    import forge_release_lock as R

    appels = []

    def _git(*args, cwd=None):
        appels.append((args, cwd))
        if "ls-tree" in args:
            return (0, GITLINK)
        if "rev-parse" in args and cwd is not None:
            return (128, "")          # sous-depot non initialise
        if "rev-parse" in args:
            return (0, "b" * 40)
        return (0, "")

    monkeypatch.setattr(R, "_git", _git)
    fiche = R.composition()["components"]["Nokido"]
    assert fiche["etat"] == "non_verifie"
    assert fiche["sha_checkout"] is None


def test_un_checkout_qui_diffère_du_pointeur_est_desynchronise(monkeypatch):
    import forge_release_lock as R

    monkeypatch.setattr(R, "_git", _faux_git({
        "ls-tree": _Rep(0, GITLINK),
        "rev-parse": _Rep(0, "c" * 40),
    }))
    assert R.composition()["components"]["Nokido"]["etat"] == "desynchronise"


def test_un_checkout_conforme_est_ok(monkeypatch):
    import forge_release_lock as R

    monkeypatch.setattr(R, "_git", _faux_git({
        "ls-tree": _Rep(0, GITLINK),
        "rev-parse": _Rep(0, "a" * 40),
    }))
    fiche = R.composition()["components"]["Nokido"]
    assert fiche["etat"] == "ok" and fiche["sha"] == "a" * 40


def test_une_ligne_qui_n_est_pas_un_gitlink_n_entre_pas_dans_la_composition(monkeypatch):
    """Un blob ou un arbre ordinaire n'est pas un composant : l'y compter
    figerait dans le verrou des SHA de fichiers."""
    import forge_release_lock as R

    lignes = ("100644 blob " + "d" * 40 + "\tREADME.md\n"
              "040000 tree " + "e" * 40 + "\tapp")
    monkeypatch.setattr(R, "_git", _faux_git({
        "ls-tree": _Rep(0, lignes),
        "submodule": _Rep(1, "pas de sous-depot"),
        "rev-parse": _Rep(0, "f" * 40),
    }))
    assert R.composition()["components"] == {}


def test_un_ls_tree_muet_bascule_sur_le_repli(monkeypatch):
    """rc non nul OU sortie vide : dans les deux cas la lecture n'a rien donne
    et il faut basculer sur `submodule status`, pas conclure « aucun composant »."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "_git", _faux_git({
        "ls-tree": _Rep(0, ""),
        "submodule": _Rep(1, "muet"),
    }))
    assert "erreur" in R.composition()


def test_une_sortie_non_vide_sur_rc_non_nul_n_est_pas_parsee(monkeypatch):
    """git ecrit parfois sur stdout EN ECHOUANT (message d'erreur, aide). Lire
    ces lignes comme des composants figerait des SHA imaginaires dans le verrou :
    il faut les DEUX conditions, rc nul ET sortie."""
    import forge_release_lock as R

    monkeypatch.setattr(R, "_git", _faux_git({
        "ls-tree": _Rep(128, GITLINK),          # sortie plausible, mais rc en echec
        "submodule": _Rep(1, "muet"),
    }))
    comp = R.composition()
    assert comp["components"] == {}
    assert "erreur" in comp


def test_git_interroge_le_workspace_par_defaut_et_l_arbre_demande_sinon(monkeypatch):
    import forge_release_lock as R

    vus = {}

    class _R:
        returncode, stdout, stderr = 0, "  sortie  ", ""

    def _faux_run(argv, **kw):
        vus.update(kw)
        vus["argv"] = list(argv)
        return _R()

    monkeypatch.setattr(R.subprocess, "run", _faux_run)
    rc, out = R._git("rev-parse", "HEAD")
    assert rc == 0 and out == "sortie", "la sortie doit etre capturee et nettoyee"
    assert vus["capture_output"] is True and vus["text"] is True
    assert str(R.WORKSPACE) in vus["argv"]
    R._git("rev-parse", "HEAD", cwd=R.WORKSPACE / "Nokido")
    assert str(R.WORKSPACE / "Nokido") in vus["argv"]


def test_l_empreinte_ignore_l_ordre_des_composants():
    """Deux verrous identiques au reordonnancement des composants pres portent
    la MEME empreinte : la canonicalisation trie, sinon un simple re-ordre
    casserait une signature legitime."""
    import forge_release_lock as R

    a = copy.deepcopy(_VERROU)
    b = copy.deepcopy(_VERROU)
    b["components"] = {k: b["components"][k] for k in reversed(list(b["components"]))}
    assert R._provenance_payload(a) == R._provenance_payload(b)


def test_l_amorce_namespace_MORD_quand_le_script_est_lance_par_chemin():
    """MUTANT SURVIVANT tue le 2026-09-10 (genre `comparaison`, ligne 49).

    La migration PyPI a injecte cette amorce dans 973 fichiers :

        if _RACINE_AMORCE not in _sys_amorce.path:
            _sys_amorce.path.insert(0, _RACINE_AMORCE)

    `sys.path[0]` vaut le dossier du SCRIPT (`tools/`), jamais la racine : sans
    elle, `from nokido_agent...` leve ModuleNotFoundError des que ce fichier est
    lance PAR CHEMIN. Le cliquet a retourne `not in` en `in` et AUCUN test n'a
    bronche — du code neuf, dans 973 fichiers, sans le moindre garde. Ce n'est
    pas un test qui a cesse de couvrir : c'est une surface qui n'a jamais ete
    couverte.

    Ce test emprunte le CHEMIN REEL : interpreteur NEUF, cwd tiers, aucun
    PYTHONPATH. Il charge le fichier HORS `__main__` (l'amorce s'execute, la CLI
    non) puis importe le namespace. Avec le mutant, l'import echoue.

    ⚠️ Un `--help` ne suffirait PAS : les imports `nokido_agent` de ce module
    vivent DANS des fonctions (L195), donc argparse rendrait 0 sans jamais les
    atteindre. Un test qui passe sans toucher la propriete ne la protege pas.
    """
    import os
    import subprocess
    import tempfile

    script = ROOT / "tools" / "forge_release_lock.py"
    programme = (
        "import importlib.util as u;"
        f"s=u.spec_from_file_location('_sous_test', r'{script}');"
        "m=u.module_from_spec(s); s.loader.exec_module(m);"
        "import nokido_agent.app.forge_persona_tpm;"
        "print('AMORCE_OK')"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory() as ailleurs:
        # `errors="replace"` : un sous-processus peut cracher des octets non
        # decodables, et `_readerthread` meurt alors en plein vol (incident 47 Go
        # garde par le gate firehose). Un test qui explose sur l'encodage de sa
        # propre sortie ne mesure plus rien.
        r = subprocess.run([sys.executable, "-c", programme], cwd=ailleurs,
                           env=env, capture_output=True, text=True,
                           errors="replace", timeout=180)
    assert "AMORCE_OK" in r.stdout, (
        "l'amorce n'a pas mis la racine du depot dans sys.path : lance par "
        f"chemin, ce script ne peut pas importer nokido_agent (rc={r.returncode})\n"
        f"stdout={r.stdout[-500:]}\nstderr={r.stderr[-800:]}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
