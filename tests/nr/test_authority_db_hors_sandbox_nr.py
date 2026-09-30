"""NR — la base d'AUTORITE se resout a chaque appel, et son interrupteur est hors de portee du client.

Contexte mesure le 2026-09-13. Apres le resserrement des ACL, l'instrument M0.1
ne compte plus qu'UN partage reel : `%NOKIDO_DATA%\\embeddings.db`, ou `LaForgeSandboxUsers`
ecrit encore -- or cette base porte `opsec_state` (kill-switch humain de dernier
recours) et `forge_tools` (bareme d'autorisation par outil). Une ACL de fichier ne
sait pas separer des TABLES : il faut deplacer les deux tables.

Le patron impose par le corps est l'INTERRUPTEUR GLOBAL lu a chaque appel
(`forge_db_path.m2m_path()` + `sandbox/m2m.switch`), jamais une migration site par
site : un site bascule seul = un hub qui ecrit d'un cote et lit de l'autre.

Trois proprietes verrouillees ici, dont une strictement securitaire :

1. la resolution existe et vaut la base RAG tant que rien n'a bascule (aucune
   bascule accidentelle : un defaut ici deplacerait le kill-switch en silence) ;
2. elle est resolue A CHAQUE APPEL -- une constante figee a l'import ne se
   redirige pas (paye le 2026-09-10, repaye le 09-12) ;
3. **l'interrupteur ne vit PAS sous `sandbox/`** : ce dossier est `(M)` pour
   `LaForgeSandboxUsers`, donc un interrupteur pose la se laisserait rebasculer
   par le client vers la base qu'il ecrit -- le contournement exact qu'on ferme.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_db_path as fdp  # noqa: E402


def test_la_resolution_d_autorite_existe():
    assert hasattr(fdp, "authority_path"), (
        "aucune resolution dediee : opsec_state et forge_tools restent dans la base "
        "que le compte client ecrit"
    )
    assert hasattr(fdp, "authority_switch_actif")


def test_sans_interrupteur_rien_ne_bascule(monkeypatch):
    """Defaut sur la base RAG : une bascule accidentelle deplacerait le kill-switch."""
    monkeypatch.delenv("LAFORGE_AUTHORITY_DB", raising=False)
    if fdp.authority_switch_actif():
        pytest.skip("interrupteur pose sur ce poste — le defaut n'est pas observable ici")
    assert fdp.authority_path() == fdp.db_path()


def test_resolution_a_chaque_appel_pas_de_constante_figee(monkeypatch, tmp_path):
    """Une constante figee a l'import ne se redirige pas (defaut paye deux fois)."""
    cible = tmp_path / "authority.db"
    monkeypatch.setenv("LAFORGE_AUTHORITY_DB", str(cible))
    premier = fdp.authority_path()
    assert str(cible) == premier, "l'environnement n'est pas relu a l'appel"

    autre = tmp_path / "authority_bis.db"
    monkeypatch.setenv("LAFORGE_AUTHORITY_DB", str(autre))
    assert fdp.authority_path() == str(autre), (
        "deux appels successifs rendent la meme valeur : le chemin est fige, "
        "donc irredirigeable"
    )


def _parties_sous_le_depot(chemin: Path) -> list:
    """Parties du chemin RELATIVES a la racine du depot.

    DEFAUT MESURE le 2026-09-13 (certification de reference d49653340) : juger
    « sandbox » sur le chemin ABSOLU rend ces deux NR infalsifiables hors de
    l'arbre principal. Une certification bat son worktree sous
    `sandbox/workspace/tmp/...`, si bien que TOUT chemin y contient « sandbox »
    et que les deux tests echouaient par construction -- un rouge qui ne parle
    ni du code ni de la securite, seulement du lieu ou l'on mesure.

    Le contrat vise le `sandbox/` DU DEPOT (la zone `(M)` pour le compte
    client), pas une sous-chaine de chemin. On le juge donc en relatif, et le
    test MORD toujours : poser la base sous `<racine>/sandbox/` le fait tomber.
    Hors depot, on retombe sur l'absolu -- ne pas pouvoir rapporter un chemin ne
    doit jamais rendre un garde permissif.
    """
    racine = Path(fdp.__file__).resolve().parent.parent
    try:
        return [p.lower() for p in chemin.relative_to(racine).parts]
    except ValueError:
        return [p.lower() for p in chemin.parts]


def test_l_interrupteur_n_est_pas_dans_sandbox():
    """LE point securitaire : sandbox/ est (M) pour LaForgeSandboxUsers."""
    chemin = Path(str(fdp.authority_switch_path())).resolve()
    assert "sandbox" not in _parties_sous_le_depot(chemin), (
        f"interrupteur d'autorite dans une zone inscriptible par le client : {chemin}. "
        "Le client pourrait rebasculer l'autorite vers la base qu'il ecrit."
    )


def test_la_cible_par_defaut_est_hors_sandbox():
    """Deplacer une table sans deplacer le domaine de confiance ne ferme rien."""
    cible = Path(str(fdp.authority_db_defaut())).resolve()
    assert "sandbox" not in _parties_sous_le_depot(cible), (
        f"base d'autorite posee dans sandbox/ : {cible} — le client y ecrirait toujours"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
