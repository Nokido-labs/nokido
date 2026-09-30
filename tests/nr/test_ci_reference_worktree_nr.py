"""NR 2026-09-09 (T0) — la CI de REFERENCE mesure un SHA, jamais l'arbre partage.

LE DEFAUT VISE, ET IL EST ARCHITECTURAL. `_inscrire_generation` interroge
`git status` du WORKING TREE. La validite de la preuve depend donc de ce que font
les autres surfaces pendant toute la duree du run — 20 minutes, quatre agents
actifs (CLAUDE, ANTIGRAVITY, GEMINI, COWORK). Ce n'est pas un accident de
calendrier qu'on reglerait en attendant une fenetre calme : c'est une propriete du
montage. Meme avec des tests parfaitement deterministes, la CERTIFICATION de ce
qu'ils ont teste ne l'est pas.

Mesure du 2026-09-09 : quatre CI vertes de suite n'avaient capture aucun sha, et
la journee entiere a consiste a faire tenir l'arbre tranquille assez longtemps.
L'attente etait le symptome. La cause est que la CI tient un ARBRE la ou elle
devrait tenir un SHA.

CE QUE FIXE CE NR. La CI de reference cree un worktree DETACHE sur le sha d'entree
et s'y re-execute : `ROOT` etant derive de `__file__`, tout le verdict — tests,
gates, git status, generation — bascule alors sur le worktree sans une ligne de
plus. L'arbre partage peut etre modifie, commite, reset pendant ce temps : ca ne
change rien a la preuve.

DEUX PIEGES QUE CE NR REFUSE :

1. LA RECURSION. La re-execution ne doit plus porter `--reference`, sinon le
   worktree en cree un autre, indefiniment.
2. LE FAIL-OPEN, le plus grave. Si le worktree ne peut pas etre prepare (sha
   illisible, git indisponible, ACL), la CI de reference doit REFUSER en le
   nommant. Retomber sur l'arbre partage rendrait un verdict d'apparence normale
   dont plus personne ne saurait qu'il ne certifie rien -- exactement le motif
   « UNKNOWN range du cote sain » que la constitution interdit.

Zero service externe. ATTENTION : cette phrase a ete FAUSSE le 2026-09-11. Apres
la convergence vers un createur unique, injecter le `git` de `preparer_reference`
ne suffisait plus : la creation etait passee dans `forge_worktree.create_proof`,
qui lance son PROPRE git sur le depot reel. Le docstring proclamait donc un
hermetisme que le test avait perdu -- et c'est lui qu'on relisait pour s'en
assurer. Un fichier qui se decrit lui-meme ne prouve rien ; les sondes
`_aucun_processus_lance` et `_empreinte` le MESURENT desormais.
"""

import contextlib
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(Path(__file__).resolve().parent), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402
from _patron_garde import prouver_que_le_garde_mord  # noqa: E402

SHA = "45a601ea56ddd59c6ca34bc27d880faac367b4dc"


def _git_ok(args):
    """git double : resout HEAD, accepte worktree add / checkout."""
    if "rev-parse" in args:
        return 0, SHA, ""
    return 0, "", ""


def _git_muet(args):
    """git indisponible : rend un rc non nul et un stderr qui NOMME la panne."""
    return 128, "", "fatal: not a git repository"


def _git_interdit(args):
    """git qui ne doit JAMAIS etre appele : son appel est une faute, pas un detail.

    Quand le sha est FOURNI, `preparer_reference` n'a plus rien a resoudre. Un
    double muet laisserait passer une resolution superflue sans qu'on le sache.
    """
    raise AssertionError(
        "le git injecte a ete appele alors que le sha etait deja fourni : %r"
        % (list(args),))


class _CreateurFactice:
    """Double du MODULE `forge_worktree` : enregistre ses appels, n'ecrit RIEN.

    C'est la profondeur du double qui compte, et c'est elle qui manquait. Poser le
    double sur le `git` de `preparer_reference` laissait le VRAI `create_proof`
    lancer son propre git sur le depot reel : le verdict dependait alors de
    l'historique present sur la machine. On substitue donc la PRIMITIVE, pas sa
    plomberie.
    """

    def __init__(self):
        self.reponse = {}
        self.appels = []

    def create_proof(self, target_sha, execution_id=None, **kw):
        self.appels.append({"sha": target_sha, "execution_id": execution_id})
        return dict(self.reponse)

    def installer(self, monkeypatch):
        faux = types.ModuleType("forge_worktree")
        faux.create_proof = self.create_proof
        monkeypatch.setitem(sys.modules, "forge_worktree", faux)
        return self


@contextlib.contextmanager
def _aucun_processus_lance():
    """Tout lancement de processus dans le bloc est une faute, et elle est NOMMEE.

    Un worktree ne peut naitre que d'un processus git : surveiller le LANCEMENT
    couvre donc �� aucun git reel �� et �� aucun worktree cree �� d'un seul tenant,
    sans dependre du chemin qu'emprunte l'implementation -- une sonde posee sur
    `forge_worktree` deviendrait aveugle le jour ou la creation demenagerait, ce
    qui est exactement ce qui vient d'arriver.
    """
    originaux = {}
    cibles = ((subprocess, "run"), (subprocess, "Popen"),
              (subprocess, "check_output"), (subprocess, "call"),
              (subprocess, "check_call"), (os, "system"))

    def _piege(etiquette):
        def _f(*a, **k):
            raise AssertionError(
                "processus lance dans un NR qui doit rester hermetique : %s %r"
                % (etiquette, (a[0] if a else None,)))
        return _f

    for mod, nom in cibles:
        originaux[(mod, nom)] = getattr(mod, nom)
        setattr(mod, nom, _piege("%s.%s" % (mod.__name__, nom)))
    try:
        yield
    finally:
        for (mod, nom), vrai in originaux.items():
            setattr(mod, nom, vrai)


def _empreinte(chemin):
    """Etat OBSERVABLE d'un emplacement. TROIS etats, jamais deux.

    Un emplacement illisible est NOMME `illisible`, il ne se confond pas avec
    `absent` : sinon une ACL ferait passer une mutation pour une absence de
    mutation, et la sonde rassurerait d'autant plus qu'elle voit moins.
    """
    try:
        if not chemin.exists():
            return "absent"
        return sorted(p.name for p in chemin.iterdir())
    except OSError as exc:
        return "illisible: %s" % (exc.__class__.__name__,)


def test_la_sonde_de_processus_mord_et_se_retire():
    """Une sonde non prouvee est un garde branche sur un signal que nul n'emet.

    Elle leve AVANT d'executer : aucun processus n'est reellement lance ici.
    """
    avant = subprocess.run
    with pytest.raises(AssertionError):
        with _aucun_processus_lance():
            subprocess.run(["git", "worktree", "add", "--detach", "nulle-part"])
    assert subprocess.run is avant, (
        "la sonde n'a pas rendu `subprocess.run` : elle contaminerait toute la "
        "suite du run, et le prochain test echouerait pour une raison etrangere")


def test_l_empreinte_distingue_absent_vide_et_peuple(tmp_path):
    """Sinon �� 0 fichier cree �� ne vaudrait rien : une sonde aveugle rend zero."""
    cible = tmp_path / "preuve"
    assert _empreinte(cible) == "absent"
    cible.mkdir()
    assert _empreinte(cible) == []
    (cible / "execution-42").mkdir()
    assert _empreinte(cible) == ["execution-42"]


def test_la_reexecution_ne_reporte_pas_le_drapeau_de_reference():
    """Sinon le worktree relance un worktree, indefiniment."""
    assert hasattr(ci_local, "_argv_sans_reference"), (
        "ci_local n'expose pas _argv_sans_reference : rien ne garantit que la "
        "re-execution dans le worktree ne se relance pas elle-meme")
    for argv in (["--reference", SHA, "--no-mutation"],
                 ["--reference", "--no-mutation"],
                 ["--no-mutation", "--reference", SHA]):
        reste = ci_local._argv_sans_reference(argv)
        assert "--reference" not in reste, "recursion : %r -> %r" % (argv, reste)
        assert SHA not in reste, "le sha suit le drapeau retire : %r" % (reste,)
        assert "--no-mutation" in reste, "les autres drapeaux doivent survivre"


def test_le_worktree_est_demande_sur_le_sha_ET_detache(monkeypatch):
    """Un worktree attache suivrait une branche : il ne figerait rien.

    ADAPTE LE 2026-09-11, convergence vers un createur unique. Ce test espionnait le
    `git` injecte dans `preparer_reference` pour y voir passer `worktree add
    --detach`. La creation vit desormais dans `forge_worktree.create_proof` -- il y
    en avait TROIS implementations, qui avaient deja diverge -- donc ce `git` ne voit
    plus que la resolution du sha.

    LA PROPRIETE N'EST PAS ABANDONNEE, elle a change d'adresse : « detache, jamais de
    branche, HEAD sur le sha demande » est mesuree par
    `test_worktree_preuve_non_interference_nr::test_le_proof_est_detache_et_ne_cree_aucune_branche`,
    sur un depot git REEL plutot que sur un git simule.

    CE QUI RESTE ICI est la responsabilite propre de `preparer_reference` : resoudre
    le sha et le TRANSMETTRE au createur. Sans cela le juge mesurerait un autre
    commit -- se tromper de sujet est pire que ne pas juger.
    """
    import sys as _sys
    import types as _types

    vu = {}
    faux = _types.ModuleType("forge_worktree")

    def create_proof(target_sha, execution_id=None, **kw):
        vu["sha"] = target_sha
        vu["execution_id"] = execution_id
        return {"sha": target_sha, "path": "/proof/factice",
                "status": "created", "detached": True}

    faux.create_proof = create_proof
    monkeypatch.setitem(_sys.modules, "forge_worktree", faux)

    vues = []

    def git(args):
        vues.append(list(args))
        return _git_ok(args)

    r = ci_local.preparer_reference(sha=None, git=git)
    assert r["ok"], r
    assert r["sha"] == SHA
    assert any("rev-parse" in a for a in vues), (
        "le sha n'a pas ete resolu : %r" % (vues,))
    assert vu.get("sha") == SHA, (
        "le sha resolu n'a PAS ete transmis au createur canonique (%r) : le juge "
        "mesurerait un autre commit que celui demande" % (vu,))


def test_un_worktree_impossible_REFUSE_au_lieu_de_retomber_sur_l_arbre(
        monkeypatch, tmp_path):
    """LE garde de T0, prouve des DEUX cotes -- SANS toucher au depot reel.

    REECRIT LE 2026-09-11, apres que ce test EXACT a fait virer la CI GitHub au
    rouge sur `a6c730292`. Il injectait le `git` de `preparer_reference` et
    laissait l'appel atteindre le VRAI `create_proof`, donc le vrai git :

        local  : le sha temoin est un commit reel      -> worktree cree -> ADMIS
        runner : checkout shallow, `rev-list --count HEAD` = 1
                 -> `sha inconnu dans ce depot`        -> refus  -> PARANOIAQUE

    Deux defauts, pas un. Le verdict dependait de l'historique present sur la
    machine, donc il pouvait virer sans qu'une ligne de code change -- un cliquet
    qui bouge tout seul ne garde rien. Et quand il passait, il CREAIT un vrai
    worktree de preuve : un test de garde qui contamine l'etat meme qu'il pretend
    verifier.

    Ce qui est mesure ici est CONCEPTUEL et n'a besoin d'aucun commit :

        create_proof REFUSE -> preparer_reference REFUSE en nommant la panne,
                               et ne retombe JAMAIS sur l'arbre partage.

    Le mode `--reference` sur un sha REELLEMENT disponible reste couvert, mais
    ailleurs et sur un depot git reel (`test_capture_sur_worktree_de_preuve_nr`,
    `test_worktree_preuve_non_interference_nr`). Deux niveaux, deux tests : un
    seul qui melange les deux ne juge bien ni l'un ni l'autre.
    """
    import forge_worktree as _vrai_avant_substitution
    racine_preuve = Path(_vrai_avant_substitution.PROOF_ROOT)
    racine_git_wt = RACINE / ".git" / "worktrees"
    avant = (_empreinte(racine_preuve), _empreinte(racine_git_wt))

    createur = _CreateurFactice().installer(monkeypatch)
    REFUS = {"status": "refuse", "error": "sha inconnu dans ce depot : %s" % SHA}
    ADMIS = {"status": "created", "sha": SHA, "detached": True,
             "path": str(tmp_path / "preuve" / "worktree")}

    def exercer_createur(reponse):
        createur.reponse = reponse
        return ci_local.preparer_reference(sha=SHA, git=_git_interdit)

    with _aucun_processus_lance():
        # GARDE A -- le refus du createur se propage, l'acceptation passe.
        prouver_que_le_garde_mord(
            nom="isolation de la preuve (T0) : le refus du createur se propage",
            exercer=exercer_createur,
            entree_refusee=REFUS,
            entree_admise=ADMIS,
            est_un_refus=lambda r: r.get("ok") is False,
        )

        # GARDE B -- git indisponible : refus, jamais de repli silencieux.
        createur.reponse = ADMIS
        prouver_que_le_garde_mord(
            nom="isolation de la preuve (T0) : git indisponible",
            exercer=lambda g: ci_local.preparer_reference(sha=None, git=g),
            entree_refusee=_git_muet,
            entree_admise=_git_ok,
            est_un_refus=lambda r: r.get("ok") is False,
        )

        # 1. LE SHA EST TRANSMIS au createur canonique.
        createur.appels.clear()
        createur.reponse = ADMIS
        r_ok = ci_local.preparer_reference(sha=SHA, git=_git_interdit)
        assert createur.appels, "create_proof n'a pas ete appele du tout"
        assert createur.appels[-1]["sha"] == SHA, (
            "le sha n'a PAS ete transmis au createur (%r) : le juge certifierait "
            "un autre commit que celui demande" % (createur.appels[-1],))
        assert r_ok["ok"] and r_ok["worktree"] == ADMIS["path"]

        # 2. LE REFUS EST PROPAGE, avec le motif du createur et non un resume.
        createur.reponse = REFUS
        r_ko = ci_local.preparer_reference(sha=SHA, git=_git_interdit)
        assert r_ko["ok"] is False
        assert REFUS["error"] in str(r_ko["motif"]), (
            "le motif du createur a ete perdu en route (%r) : un echec qui ne se "
            "nomme pas se re-instruit a chaque fois" % (r_ko["motif"],))

        # 3. AUCUN REPLI sur l'arbre partage, meme quand le refus PORTE un chemin.
        #    C'est la forme exacte du fail-open : un `path` d'apparence normale
        #    accompagnant une erreur, qu'un `res.get("path") or ...` lirait comme
        #    un succes. `error` prime sur `path`, toujours.
        createur.reponse = {"status": "refuse", "error": "ACL refusee",
                            "path": str(RACINE)}
        r_piege = ci_local.preparer_reference(sha=SHA, git=_git_interdit)
        assert r_piege["ok"] is False, (
            "un createur qui REFUSE en rendant un chemin a ete lu comme un "
            "succes : c'est le repli sur l'arbre partage, deguise en preuve")

        # 4. Le refus git nomme la panne (chemin d'erreur muet, paye le 2026-09-07).
        r_git = ci_local.preparer_reference(sha=None, git=_git_muet)
        assert r_git.get("motif"), "refus SANS motif"
        assert "git" in r_git["motif"].lower() or "128" in str(r_git["motif"])

    # 5 et 6. NON MUTATEUR : ni worktree, ni entree dans la racine de preuve.
    apres = (_empreinte(racine_preuve), _empreinte(racine_git_wt))
    assert apres == avant, (
        "ce NR a MUTE l'etat de preuve qu'il pretend verifier.\n"
        "  avant : %r\n  apres : %r\n"
        "  -> un test de garde qui ecrit dans PROOF_ROOT contamine la mesure "
        "suivante, et c'est precisement le defaut corrige le 2026-09-11."
        % (avant, apres))
