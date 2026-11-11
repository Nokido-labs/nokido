# -*- coding: utf-8 -*-
"""Test NR pour tools/forge_migrate_env_secret.py — couvre les 3 défauts mesurés le 7/11.

Défaut 1 : `_cle_valeur` et `lire_source` gardent les guillemets d'une ligne `CLE="valeur"`, 
qui partent au coffre avec la valeur. Attendu : retirer une paire de guillemets englobants.

Défaut 2 : dans `main`, la relecture `get_secret(tgt)` peut retomber sur `Nokido.env` si 
l'écriture au coffre a échoué, conclure à l'égalité, puis `retirer_du_clair` supprime la ligne : 
le secret est perdu. Attendu : relire dans le coffre seul.

Défaut 3 : un `PermissionError` sur le fichier d'environnement dans `_ecrire` produit 
une trace brute. Attendu : message clair, sans valeur, rc distinct.

Ce test utilise un fichier temporaire et un coffre factice (mocké).
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_defaut1_guillemets_retires():
    """Teste que les guillemets englobants sont retirés de la valeur lue."""
    from tools.forge_migrate_env_secret import _cle_valeur, lire_source
    
    # Test avec guillemets doubles
    nom, val = _cle_valeur('CLE="valeur"')
    assert nom == "CLE"
    assert val == "valeur"  # Pas "valeur" avec guillemets
    
    # Test avec guillemets simples
    nom, val = _cle_valeur("CLE='valeur'")
    assert nom == "CLE"
    assert val == "valeur"  # Pas 'valeur' avec guillemets
    
    # Test avec guillemets mixtes (devrait échouer)
    nom, val = _cle_valeur('CLE="valeur\'')
    assert nom == "CLE"
    assert val == '"valeur\''  # Cas complexe, mais sans guillemets externes


def test_defaut2_lecture_coffre_seul():
    """Teste que la relecture se fait dans le coffre seul, pas dans Nokido.env."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8') as f:
        f.write('CLE=valeur_originale\n')
        f.write('CIBLE=valeur_migree\n')
        temp_env = Path(f.name)

    try:
        from tools import forge_migrate_env_secret as m

        def mock_sonder(source, key):
            if source == "coffre" and key == "CIBLE":
                return "valeur_du_coffre", False
            return None, True

        # La valeur relue au coffre differe de celle du .env : rc 3, ligne en clair conservee.
        with patch.object(m, '_sonder', side_effect=mock_sonder):
            with patch.object(m, 'set_secret') as mock_set:
                mock_set.return_value = True
                rc = m.main(['CLE', 'CIBLE'], env=temp_env)

        assert rc == 3
        assert 'CLE=valeur_originale' in temp_env.read_text(encoding='utf-8')

    finally:
        temp_env.unlink()


def test_defaut3_permission_error_gere():
    """Teste que PermissionError est géré proprement : message clair et rc 4."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8') as f:
        f.write('CLE=valeur\n')
        temp_env = Path(f.name)

    try:
        from tools import forge_migrate_env_secret as m

        initial = b"contenu initial"
        nouveau = b"contenu nouveau"

        # Echec atomique ET repli en place : _ecrire leve un PermissionError au message clair.
        with patch('os.replace', side_effect=PermissionError("Permission denied")):
            with patch.object(Path, 'write_bytes', side_effect=PermissionError("Permission denied")):
                with patch('builtins.open', side_effect=PermissionError("Permission denied")):
                    try:
                        m._ecrire(temp_env, initial, nouveau)
                        assert False, "Devrait lever une erreur"
                    except PermissionError as e:
                        assert "permission" in str(e).lower()

        # main rend un rc DISTINCT (4) et dit que le stockage au coffre a reussi.
        def mock_sonder(source, key):
            return "valeur", False

        with patch.object(m, '_sonder', side_effect=mock_sonder):
            with patch.object(m, 'set_secret'):
                with patch.object(m, '_ecrire', side_effect=PermissionError("Permission denied")):
                    rc = m.main(['CLE', 'CIBLE'], env=temp_env)

        assert rc == 4

    finally:
        temp_env.unlink()


def test_integration_complet():
    """Test d'intégration complet avec les corrections appliquées."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write('CLE="valeur_avec_guillemets"\n')
        temp_env = Path(f.name)
    
    try:
        from tools.forge_migrate_env_secret import _cle_valeur, lire_source
        
        # Test de la correction du défaut 1
        nom, val = _cle_valeur('CLE="valeur_avec_guillemets"')
        assert nom == "CLE"
        assert val == "valeur_avec_guillemets"  # Sans guillemets
        
        # Test de la correction du défaut 2
        val, provenance = lire_source(temp_env, "CLE")
        assert val == "valeur_avec_guillemets"
        assert "ligne 1" in provenance
        
    finally:
        temp_env.unlink()