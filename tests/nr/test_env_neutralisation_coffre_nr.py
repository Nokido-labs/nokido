# -*- coding: utf-8 -*-
"""NR — la neutralisation du fichier d'environnement ne detruit QUE ce que le coffre detient.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la neutralisation des secrets du .env"

CE QUE LA MESURE A TROUVE (2026-09-06). Ecrire un secret au coffre ne reduit AUCUNE surface
tant que sa valeur reste en clair dans `Nokido.env`. Etat mesure ce jour-la : 110 cles
actives, 63 lignes commentees -- et **31 de ces lignes commentees portaient ENCORE leur
valeur**, dont un jeton de 37 caracteres et une cle de 110. Commenter avait DESACTIVE la
ligne, pas retire le secret.

LA GARDE, ET ELLE SEULE : l'EMPREINTE. Une valeur n'est retiree du fichier que si son hache
est exactement celui que le coffre rend pour la meme cle. Trois consequences, chacune testee
ici, et la premiere est la plus importante :

  1. une cle ABSENTE du coffre n'est JAMAIS touchee -- sinon on detruirait la seule copie ;
  2. une cle dont le coffre a une valeur DIFFERENTE n'est jamais touchee : on ne sait pas
     laquelle est la bonne, c'est un conflit et il se tranche a la main ;
  3. un commentaire narratif contenant un `=` ne peut PAS etre pris pour une affectation,
     non par finesse d'analyse mais parce qu'aucune empreinte ne correspondra.

Et le mode PLAN ne doit rien ecrire : un outil qui detruit avant d'avoir montre ce qu'il
detruit n'est pas utilisable sur un fichier de secrets.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_env_to_vault as fev  # noqa: E402


def _coffre(**paires):
    """Doublure de `vault_get` : rend la valeur connue, sinon None."""
    def _get(cle):
        return paires.get(cle)
    return _get


def _ecrire(tmp_path: Path, lignes: list[str]) -> Path:
    f = tmp_path / "Nokido.env"
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return f


def _lire(f: Path) -> list[str]:
    return f.read_text(encoding="utf-8").splitlines()


def test_le_plan_n_ecrit_rien(tmp_path):
    f = _ecrire(tmp_path, ["API_KEY=valeur-secrete", "AUTRE=1"])
    avant = f.read_text(encoding="utf-8")
    n = fev._neutraliser(f, _coffre(API_KEY="valeur-secrete"), appliquer=False)
    assert n == 0
    assert f.read_text(encoding="utf-8") == avant, "le mode plan a modifie le fichier"


def test_une_valeur_identique_au_coffre_est_retiree(tmp_path):
    f = _ecrire(tmp_path, ["API_KEY=valeur-secrete", "AUTRE=1"])
    n = fev._neutraliser(f, _coffre(API_KEY="valeur-secrete"), appliquer=True)
    assert n == 1
    lignes = _lire(f)
    assert "valeur-secrete" not in "\n".join(lignes), "la valeur est restee dans le fichier"
    assert any(l.startswith("# API_KEY=") for l in lignes), "le NOM doit etre conserve"
    assert any("valeur retiree le" in l for l in lignes), "la ligne doit dire ce qui s'est passe"
    assert "AUTRE=1" in lignes, "une cle hors coffre ne doit pas bouger"


def test_une_cle_absente_du_coffre_n_est_JAMAIS_touchee(tmp_path):
    """Le cas qui detruirait la seule copie du secret."""
    f = _ecrire(tmp_path, ["ORPHELINE=seule-copie"])
    n = fev._neutraliser(f, _coffre(), appliquer=True)
    assert n == 0
    assert "ORPHELINE=seule-copie" in _lire(f)


def test_une_valeur_divergente_n_est_JAMAIS_touchee(tmp_path):
    """Coffre et fichier different : on ne sait pas lequel est bon -> on ne detruit rien."""
    f = _ecrire(tmp_path, ["API_KEY=version-fichier"])
    n = fev._neutraliser(f, _coffre(API_KEY="version-coffre"), appliquer=True)
    assert n == 0
    assert "API_KEY=version-fichier" in _lire(f)


def test_une_ligne_deja_commentee_mais_portant_sa_valeur_est_videe(tmp_path):
    """Le defaut mesure : 31 lignes commentees portaient encore leur secret."""
    f = _ecrire(tmp_path, ["# KAGGLE_API_TOKEN=jeton-encore-la"])
    n = fev._neutraliser(f, _coffre(KAGGLE_API_TOKEN="jeton-encore-la"), appliquer=True)
    assert n == 1
    contenu = f.read_text(encoding="utf-8")
    assert "jeton-encore-la" not in contenu
    assert "KAGGLE_API_TOKEN" in contenu


def test_un_commentaire_narratif_avec_un_egal_reste_intact(tmp_path):
    """Faux positif structurellement impossible : aucune empreinte ne correspondra."""
    narratif = "# LOOP_AUTOMERGE = active seulement si la qualite depasse le seuil"
    f = _ecrire(tmp_path, [narratif])
    n = fev._neutraliser(f, _coffre(LOOP_AUTOMERGE="1"), appliquer=True)
    assert n == 0
    assert narratif in _lire(f)


def test_aucune_ligne_n_est_perdue(tmp_path):
    """Ecriture atomique : un .env tronque coute plus cher que le gain."""
    lignes = ["# entete", "", "A=secret-a", "B=garde", "# commentaire", "C=secret-c"]
    f = _ecrire(tmp_path, lignes)
    fev._neutraliser(f, _coffre(A="secret-a", C="secret-c"), appliquer=True)
    apres = _lire(f)
    assert len(apres) == len(lignes), f"{len(lignes)} lignes avant, {len(apres)} apres"
    assert "B=garde" in apres


def test_l_empreinte_ne_revele_jamais_la_valeur():
    """`_emp` est un hache tronque : il compare sans exposer."""
    e = fev._emp("un-secret-tres-long-qui-ne-doit-pas-fuiter")
    assert len(e) == 12 and all(c in "0123456789abcdef" for c in e)
    assert e == hashlib.sha256(
        "un-secret-tres-long-qui-ne-doit-pas-fuiter".encode()).hexdigest()[:12]
    assert "secret" not in e


def test_une_cle_exemptee_n_est_JAMAIS_videe_meme_si_l_empreinte_correspond(tmp_path, monkeypatch):
    """Le piege exact du 2026-09-06 : restaurer ne suffit pas.

    Une cle restauree depuis le coffre a desormais la MEME empreinte que le coffre --
    donc le passage suivant de --neutraliser la reprend. La garde ne peut pas etre
    l'empreinte ici : elle doit etre une liste explicite, dans le CODE.
    Le MECANISME est teste avec une cle injectee : la liste reelle a change le 2026-09-25
    (acces SSH lus au coffre, cf. test_la_levee_d_une_exemption_cite_son_garde).
    """
    monkeypatch.setattr(fev, "JAMAIS_NEUTRALISER", {"CLE_LUE_EN_BRUT"})
    f = _ecrire(tmp_path, ["CLE_LUE_EN_BRUT=C:/cles/id_ed25519"])
    n = fev._neutraliser(f, _coffre(CLE_LUE_EN_BRUT="C:/cles/id_ed25519"), appliquer=True)
    assert n == 0, "une cle exemptee ne doit jamais etre comptee comme videe"
    assert "CLE_LUE_EN_BRUT=C:/cles/id_ed25519" in _lire(f)


def test_neutraliser_se_limite_aux_cles_demandees(tmp_path):
    """MESURE 2026-09-25 : l'owner a demande de migrer ses ACCES SSH ; le plan --neutraliser en
    aurait vide 6, dont 5 secrets hors demande (dont des cles d'API possiblement lues en brut).
    Avec --cles, seules ces cles sont touchees ; le reste est DIT hors perimetre."""
    f = _ecrire(tmp_path, ["SSH_HOST=hote", "GEMINI_API_KEY=cle-gemini"])
    n = fev._neutraliser(f, _coffre(SSH_HOST="hote", GEMINI_API_KEY="cle-gemini"), appliquer=True,
                         limiter_a={"SSH_HOST"})
    apres = _lire(f)
    assert n == 1
    assert "GEMINI_API_KEY=cle-gemini" in apres
    assert not any(l.startswith("SSH_HOST=") for l in apres)


def test_la_levee_d_une_exemption_cite_son_garde():
    """Une exemption ne se LEVE que remplacee par un garde : sinon le prochain agent vide la ligne
    d'un lecteur brut. 2026-09-25 : PRIVATE_KEY_PATH leve -- brain_worker et forge_mesh_memory lisent
    au coffre, et un CLIQUET refuse tout nouveau lecteur brut des acces SSH dans app/."""
    src = (ROOT / "tools" / "forge_env_to_vault.py").read_text(encoding="utf-8")
    assert "os.environ" in src and "brain_worker" in src, "la raison doit rester ecrite"
    garde = "test_aucun_lecteur_brut_des_acces_ssh_hors_du_coffre"
    assert garde in src, "la levee doit citer le garde qui la remplace"
    assert garde in (ROOT / "tests" / "nr" / "test_acces_ssh_au_coffre_nr.py").read_text(encoding="utf-8")


def test_la_valeur_s_arrete_au_commentaire_de_fin_de_ligne():
    """7e occurrence du motif « un instrument lit son propre vocabulaire », 2026-09-06.

    La marque posee par --neutraliser est `# CLE=   # valeur retiree le ...`. Une sonde
    qui ne coupe pas au commentaire relit ce marqueur comme une VALEUR : elle a compte
    41 lignes « portant encore un secret » la ou il y en avait 30.
    """
    assert fev._valeur_reelle("   # valeur retiree le 2026-09-06 -- lire au coffre") == ""
    assert fev._valeur_reelle("abc123 # un commentaire") == "abc123"
    assert fev._valeur_reelle('"jeton" # note') == "jeton"
    assert fev._valeur_reelle("valeur-sans-commentaire") == "valeur-sans-commentaire"
    # un '#' colle ne separe pas : ce n'est pas un commentaire de fin de ligne
    assert fev._valeur_reelle("mot#dieze") == "mot#dieze"


def test_une_cle_desactivee_portant_sa_valeur_reste_INVISIBLE_sans_le_drapeau(tmp_path):
    """Une cle commentee AVEC sa valeur est encore exposee -- mais il faut la demander."""
    f = tmp_path / "Nokido.env"
    f.write_text("# MCP_API_KEY_1=secret-encore-la\nACTIVE=1\n", encoding="utf-8")
    sans = fev.lire_env(f)
    assert "MCP_API_KEY_1" not in sans, "le defaut doit rester le comportement historique"
    avec = fev.lire_env(f, inclure_commentees=True)
    assert avec.get("MCP_API_KEY_1") == "secret-encore-la"
    assert avec.get("ACTIVE") == "1"


def test_une_ligne_deja_neutralisee_n_est_pas_relue_comme_une_valeur(tmp_path):
    """Le cas qui ferait boucler l'outil sur sa propre marque."""
    f = tmp_path / "Nokido.env"
    f.write_text("# CLE=   # valeur retiree le 2026-09-06 -- lire au coffre DPAPI\n",
                 encoding="utf-8")
    assert fev.lire_env(f, inclure_commentees=True) == {}


@pytest.mark.parametrize("drapeau", ["--neutraliser", "--appliquer", "--force"])
def test_les_drapeaux_dangereux_restent_explicites(drapeau):
    """Aucune destruction par defaut : chaque geste irreversible se demande."""
    src = (ROOT / "tools" / "forge_env_to_vault.py").read_text(encoding="utf-8")
    assert f'"{drapeau}"' in src, f"{drapeau} a disparu de l'interface"
    assert 'action="store_true"' in src
