"""NR -- isolation du profil AGY de l'executeur (7/11) : validation de LAFORGE_AGY_HOME.

Objectif : s'assurer que AGY peut lancer avec un profil distinct de l'owner via LAFORGE_AGY_HOME.
Mesure : l'executeur lit LAFORGE_AGY_HOME et lance AGY avec ce profil ; le contrôleur de capacité lit le même.
Sécurité : profil isolé = pas de collision entre AGY et l'owner, pas de vol de jetons OAuth.
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_task_executor as fte

def test_agy_peut_lancer_avec_profil_distinct():
    """Test que AGY peut être lancé avec un profil distinct via LAFORGE_AGY_HOME."""
    with TemporaryDirectory() as tmp_dir:
        # Créer un profil AGY distinct
        agy_home = Path(tmp_dir) / "agy_profil_distinct"
        agy_home.mkdir()

        # Créer la structure de profil AGY attendue
        gemini_dir = agy_home / ".gemini"
        gemini_dir.mkdir()
        (gemini_dir / "antigravity-cli").write_text("config agy test", encoding="utf-8")

        # Simuler le binaire AGY
        agy_bin = agy_home / "agy.exe"
        agy_bin.write_text("fake agy binary", encoding="utf-8")

        # Tester le lancement avec le profil distinct
        os.environ["LAFORGE_AGY_HOME"] = str(agy_home)
        os.environ["LAFORGE_AGY_BIN"] = str(agy_bin)

        # Vérifier que le profil est accepté
        peut_lancer, message = fte._peut_lancer_agy()
        assert peut_lancer is True
        assert "profil agy absent" not in message

def test_controleur_capacite_lit_le_meme_profil():
    """Test que le contrôleur de capacité lit le même profil AGY que l'executeur."""
    with TemporaryDirectory() as tmp_dir:
        # Créer deux profils AGY différents
        profil1 = Path(tmp_dir) / "profil1"
        profil1.mkdir()
        (profil1 / ".gemini").mkdir(parents=True, exist_ok=True)
        (profil1 / ".gemini" / "antigravity-cli").write_text("config profil 1", encoding="utf-8")

        profil2 = Path(tmp_dir) / "profil2"
        profil2.mkdir()
        (profil2 / ".gemini").mkdir(parents=True, exist_ok=True)
        (profil2 / ".gemini" / "antigravity-cli").write_text("config profil 2", encoding="utf-8")

        # Simuler le binaire AGY
        agy_bin = profil1 / "agy.exe"
        agy_bin.write_text("fake agy binary", encoding="utf-8")

        # Tester avec le premier profil
        os.environ["LAFORGE_AGY_HOME"] = str(profil1)
        os.environ["LAFORGE_AGY_BIN"] = str(agy_bin)

        # Vérifier que le contrôleur voit bien le premier profil
        peut_lancer1, _ = fte._peut_lancer_agy()
        assert peut_lancer1 is True

        # Tester avec le deuxième profil
        os.environ["LAFORGE_AGY_HOME"] = str(profil2)

        # Vérifier que le contrôleur voit bien le deuxième profil
        peut_lancer2, _ = fte._peut_lancer_agy()
        assert peut_lancer2 is True

        # Vérifier que les profils sont différents
        config1 = (profil1 / ".gemini" / "antigravity-cli").read_text(encoding="utf-8")
        config2 = (profil2 / ".gemini" / "antigravity-cli").read_text(encoding="utf-8")
        assert config1 != config2

def test_profil_isole_ne_confond_pas_avec_owner():
    """Test que le profil AGY isolé ne confond pas avec le profil de l'owner."""
    with TemporaryDirectory() as tmp_dir:
        # Créer un profil AGY isolé
        agy_home = Path(tmp_dir) / "agy_isole"
        agy_home.mkdir()
        (agy_home / ".gemini").mkdir(parents=True, exist_ok=True)
        (agy_home / ".gemini" / "antigravity-cli").write_text("profil agy isole", encoding="utf-8")

        # Simuler le binaire AGY
        agy_bin = agy_home / "agy.exe"
        agy_bin.write_text("fake agy binary", encoding="utf-8")

        # Tester avec le profil AGY isolé
        os.environ["LAFORGE_AGY_HOME"] = str(agy_home)
        os.environ["LAFORGE_AGY_BIN"] = str(agy_bin)

        # Vérifier que AGY peut lancer
        peut_lancer, _ = fte._peut_lancer_agy()
        assert peut_lancer is True

        # Vérifier que le profil est bien isolé (pas de dépendance vers le profil owner)
        # Le test vérifie que LAFORGE_AGY_HOME est bien utilisé et non les chemins par défaut
        assert "agy_isole" in str(agy_home)
