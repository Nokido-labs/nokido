"""NR -- forge_migrate_env_secret reconnait une ligne « Libelle: valeur », pas seulement `CLE=VALEUR` (owner 21/10).

Owner, 21/10 : « je t'ai cree un bearer dans le nokido.env pour que tu le mettes au coffre, des lignes 494 a 513 ».
Le bloc est un copier-coller de la page SourceForge « Authorized Applications » : `Bearer Token: <40 hex>`,
`Client ID: <20 hex>`, `Client Secret: <80 hex>`, `Redirect URL: https://...`. L'outil ne lisait que `CLE=VALEUR` :
il fallait manipuler le jeton a la main, ce qu'on ne fait jamais.

Contrats (sur un fichier temporaire, aucune valeur reelle) :
  1. lire_source lit `Libelle: valeur` (premier `:`) ; `CLE=VALEUR` inchange ;
  2. une valeur qui contient `=` (URL) n'est pas mal decoupee sous la forme `Libelle: valeur` ;
  3. retirer_du_clair remplace SEULEMENT la ligne visee par un commentaire SANS valeur ; les voisines sont intactes.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_migrate_env_secret as M  # noqa: E402

BLOC = ("Authorized Applications\n"
        "Bearer Token: deadbeef00deadbeef00\n"
        "Client ID: cafe0001\n"
        "Redirect URL: https://exemple.test/cb?a=b\n"
        "ANCIEN_FORMAT=valeur_x\n")


def _env(tmp_path):
    p = tmp_path / "Nokido.env"
    p.write_bytes(BLOC.encode("utf-8"))
    return p


def test_libelle_deux_points_et_cle_egal(tmp_path):
    env = _env(tmp_path)
    assert M.lire_source(env, "Bearer Token")[0] == "deadbeef00deadbeef00"
    assert M.lire_source(env, "Client ID")[0] == "cafe0001"
    assert M.lire_source(env, "ANCIEN_FORMAT")[0] == "valeur_x"


def test_url_avec_egal_non_mal_decoupee(tmp_path):
    assert M.lire_source(_env(tmp_path), "Redirect URL")[0] == "https://exemple.test/cb?a=b"


def test_retrait_de_la_seule_ligne_visee(tmp_path):
    env = _env(tmp_path)
    assert M.retirer_du_clair(env, "Bearer Token", "deadbeef00deadbeef00", "SOURCEFORGE_X") == 1
    texte = env.read_text(encoding="utf-8")
    assert "deadbeef00deadbeef00" not in texte
    assert "# Bearer Token -> migre au coffre SOURCEFORGE_X" in texte
    assert "Client ID: cafe0001" in texte and "ANCIEN_FORMAT=valeur_x" in texte
    assert "Redirect URL: https://exemple.test/cb?a=b" in texte
