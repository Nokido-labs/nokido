# -*- coding: utf-8 -*-
"""NR — le README ne promet pas une installation que personne n'a reussie.

CE QUE P4.2a A MESURE le 2026-09-09, dans un venv reellement neuf. Trois ruptures,
decouvertes l'une apres l'autre, chacune cachee par la precedente :

  1. `pip install "git+https://...#egg=nokido-agent[hub]"`
     -> error: invalid-egg-fragment. pip a retire le support de `#egg=nom[extra]`.
        La commande documentee etait INEXECUTABLE.

  2. il n'existe AUCUN module `nokido` ni `nokido_agent` a importer. L'usage passe
     par cinq entry points console, pas par un import -- mon propre script de
     reproduction se serait casse la, une etape plus loin.

  3. LA RUPTURE DE FOND : le corps s'importe A PLAT (`import forge_secrets`,
     4 449 occurrences dans 1 147 fichiers) et compense par `sys.path.insert`
     (1 186 occurrences dans 766 fichiers). Ces imports supposent la DISPOSITION DU
     DEPOT, pas un paquet installe : une fois le wheel pose, `forge_secrets` vit
     dans `site-packages/app/` et `import forge_secrets` ne le trouve plus.

CONCLUSION MESUREE : `nokido-agent` n'a jamais ete installe ni teste installe. Ce
n'est pas un defaut de `pyproject.toml` -- c'est une architecture d'execution qui
suppose le checkout. Rendre `pip install` reel demande une migration (namespace +
reecriture des imports), chiffree sur ces nombres et suivie a part.

CE QUE CE GARDE PROTEGE, et c'est le seul point qui compte : que la promesse ne
revienne pas dans le README sans qu'une reproduction l'ait etablie. Une commande
d'installation est une PROMESSE FAITE A UN INCONNU ; elle se prouve en l'executant
dans un environnement neuf, jamais en verifiant qu'elle est bien ecrite.

⚠️ Ce fichier ne prouve PAS que quoi que ce soit s'installe. Il prouve seulement
qu'on n'annonce pas le contraire de ce qu'on a mesure.
"""

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
README = RACINE / "README.md"

# `pip install nokido-agent...` ou `pip install git+https://...` : les deux formes
# dont P4.2a a montre qu'aucune ne fonctionne aujourd'hui.
_PROMESSE_PIP = re.compile(
    r"pip\s+install\s+[\"']?(?:nokido-agent|git\+https://)", re.I)

# La forme `#egg=nom[extra]`, refusee par pip (invalid-egg-fragment).
_EGG_AVEC_EXTRA = re.compile(r"#egg=[A-Za-z0-9_.-]+\[")


def _readme() -> str:
    return README.read_text(encoding="utf-8", errors="replace")


def _commandes() -> str:
    """Uniquement les BLOCS DE CODE : une commande se distingue d'une mention.

    Premiere version de ce garde, le 2026-09-09 : il criait a faux sur la phrase
    « Making `pip install nokido-agent` work is a genuine migration » -- une phrase
    qui dit precisement que ca NE marche PAS. Un garde qui crie a faux se fait
    desarmer, donc on corrige l'instrument, pas le texte qui avait raison.

    Ce qu'on cherche est ce qu'un lecteur COPIERAIT : le contenu des blocs ``` .
    """
    return "\n".join(re.findall(r"```[a-zA-Z]*\n(.*?)```", _readme(), re.S))


def test_le_readme_ne_promet_aucune_installation_par_pip():
    """La promesse ne revient que le jour ou une reproduction l'etablit.

    Le jour ou `pip install nokido-agent` marchera vraiment, ce test devra etre
    RETIRE -- et son retrait sera le geste qui engage : il exigera de montrer le
    temoin P4 correspondant, pas un README bien redige.
    """
    trouve = _PROMESSE_PIP.findall(_commandes())
    assert not trouve, (
        "un bloc de code du README propose une installation pip que P4.2a a mesuree "
        "inexecutable (imports a plat + sys.path : le paquet installe ne se retrouve "
        "pas) — %r" % trouve)


def test_le_garde_vise_les_COMMANDES_et_pas_la_prose():
    """Contre-epreuve : expliquer qu'une chose ne marche pas n'est pas la promettre.

    Sans cette distinction, le README ne pourrait plus DIRE pourquoi `pip install`
    est absent -- on remplacerait une promesse fausse par un silence, ce qui est
    pire : le lecteur devinerait au lieu de savoir.
    """
    assert "pip install" in _readme(), (
        "le README doit pouvoir mentionner pip install pour expliquer son absence")
    assert not _PROMESSE_PIP.findall(_commandes())


def test_la_forme_egg_avec_extras_ne_revient_pas():
    """pip la refuse : `invalid-egg-fragment`. Elle n'a jamais pu fonctionner."""
    assert not _EGG_AVEC_EXTRA.findall(_readme())


def test_le_statut_alpha_de_l_installation_est_DIT():
    """Retirer une promesse ne suffit pas : le lecteur doit savoir a quoi s'en tenir.

    Un README muet sur l'installation laisse deviner ; un README qui DIT
    « exécution depuis le dépôt cloné » informe. C'est la meme regle que partout
    ailleurs : une absence se NOMME.
    """
    texte = _readme().lower()
    assert "not supported yet" in texte or "non supporte" in texte, (
        "le README doit DIRE que `pip install` n'est pas encore supporte")
    assert "git clone" in texte, (
        "le chemin reellement supporte doit etre documente, pas seulement l'absence "
        "de l'autre")


def test_le_nom_de_distribution_reste_cite():
    """`nokido-agent` reste le nom declare par pyproject : le dire n'est pas le promettre."""
    assert "nokido-agent" in _readme()


# --- identite de distribution != installabilite -----------------------------
#
# Le gate `c_nom_paquet` extrayait le nom depuis `egg=`, donc depuis une COMMANDE
# D'INSTALLATION. Retirer la promesse pip a fait retomber le controle en
# INDETERMINE -- alors que la propriete qu'il mesure, « le nom annonce au public
# est-il celui que pyproject declare », existe INDEPENDAMMENT de toute commande.
#
# On lit donc une declaration STRUCTUREE, sur le patron de la ligne `<!-- STATS: -->`
# que le depot utilise deja. Surtout PAS la prose : chercher « nokido-agent »
# n'importe ou ferait revenir le faux positif corrige quelques lignes plus haut,
# ou la phrase « Making `pip install nokido-agent` work is a migration » etait prise
# pour une promesse. Mention d'un concept != declaration normative.

def _audit():
    import importlib  # noqa: PLC0415
    import sys  # noqa: PLC0415
    chemin = str(RACINE / "tools")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    return importlib.import_module("forge_capability_audit")


_PYPROJECT_TEST = '[project]\nname = "nokido-agent"\n'


def test_la_declaration_structuree_suffit_sans_commande_pip():
    v = _audit().c_nom_paquet("<!-- DIST:nokido-agent -->\nblabla", _PYPROJECT_TEST)
    assert v["statut"] == "ALIGNE", (
        "l'identite de distribution doit se mesurer sans dependre d'une commande "
        "d'installation : %r" % v)


def test_la_PROSE_seule_ne_suffit_PAS():
    """Contre-epreuve du faux positif : mentionner n'est pas declarer."""
    v = _audit().c_nom_paquet(
        "Making `pip install nokido-agent` work is a genuine migration.",
        _PYPROJECT_TEST)
    assert v["statut"] == "INDETERMINE", (
        "une mention en prose ne vaut pas declaration -- sinon le garde confond "
        "« on en parle » et « on l'annonce » : %r" % v)


def test_la_forme_egg_reste_reconnue_en_repli():
    """On ETEND la reconnaissance, on ne la remplace pas."""
    v = _audit().c_nom_paquet("pip install git+https://x#egg=nokido-agent",
                              _PYPROJECT_TEST)
    assert v["statut"] == "ALIGNE"


def test_une_declaration_DIVERGENTE_est_toujours_attrapee():
    v = _audit().c_nom_paquet("<!-- DIST:laforge-agent -->", _PYPROJECT_TEST)
    assert v["statut"] == "DIVERGE", (
        "annoncer un autre nom que celui de pyproject doit rester une divergence")


def test_le_readme_porte_la_declaration_structuree():
    import re as _re  # noqa: PLC0415
    assert _re.search(r"<!--\s*DIST:\s*[A-Za-z0-9_.-]+\s*-->", _readme()), (
        "le README doit declarer son nom de distribution de facon lisible par le "
        "gate, sur le patron de la ligne STATS")
