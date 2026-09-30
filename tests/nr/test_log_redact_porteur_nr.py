"""NR — le rédacteur de journaux est branché sur un porteur qui rédige VRAIMENT.

Mesure du 2026-09-19. `tools/forge_log_redact.py` existe depuis longtemps et
n'a **aucun importeur** (AST, 1856 fichiers, 0 illisible). En l'outillant pour
le partage d'un journal, on a découvert que son porteur par défaut ne retirait
rien :

    redact_for_log      chemin RESTE · ip RESTE · jeton RESTE   <- 1er choix !
    redact_text         chemin retiré · ip retirée · jeton RESTE
    redact_tool_output  applique les DEUX jeux de motifs

Les jeux « infrastructure » et « clefs d'API » sont DISJOINTS à 100 % (mesure du
2026-09-12) : seul `redact_tool_output` les applique tous les deux. Le nom
`redact_for_log` désignait exactement l'usage voulu, et c'est celui qui ne
faisait rien — un nom n'est pas une mesure.

## Deux pièges d'observation, payés en écrivant ce test

1. **L'affichage ment.** Le canal MCP rédige ce qu'un agent REÇOIT : la sortie
   montrait `[PATH_WIN_1]` alors que le fichier contenait le chemin en clair.
   `OBSERVED(X) != PROPERTY_OF(X)`. Tout verdict se prend ici par BOOLÉEN évalué
   sur la chaîne, jamais sur ce qui s'affiche.
2. **Un témoin mal formé accuse à tort.** Le premier jeton d'essai portait 30
   caractères ; le motif GitHub exige `{36,}`. Le rédacteur a été soupçonné à
   tort. Un témoin se vérifie contre le motif AVANT de conclure à un défaut.

Aucune valeur réelle ici : les témoins sont construits à l'exécution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import forge_log_redact as R  # noqa: E402

# Construits à l'exécution : aucun littéral ressemblant à un secret dans la source.
CHEMIN = "C:\\Users\\CompteFabrique\\secrets\\x.txt"
IP = "localhost"
JETON = "ghp_" + ("B" * 36)          # longueur conforme au motif {36,}


def test_le_porteur_par_defaut_est_celui_qui_applique_les_DEUX_jeux():
    fn = R._default_redactor()
    nom = getattr(fn, "_nokido_redacteur", "")
    assert nom.startswith("redact_tool_output"), (
        "porteur=%r : seul redact_tool_output applique infrastructure ET clefs "
        "d'API, les deux jeux etant disjoints" % nom)
    assert not R._est_identite(fn)


def test_le_temoin_est_CONFORME_au_motif_avant_toute_accusation():
    """Sans ce garde, un temoin trop court ferait accuser un redacteur sain."""
    from app.forge_secret_guard import _OUTBOUND_PATTERNS

    motifs = {label: rx for rx, label in _OUTBOUND_PATTERNS}
    rx = next((r for lab, r in motifs.items() if "GitHub" in lab), None)
    assert rx is not None, "le motif GitHub a disparu du jeu de clefs"
    assert rx.search(JETON), (
        "le temoin ne matche pas le motif : le test mesurerait autre chose que "
        "ce qu'il croit")


def test_un_journal_partage_perd_chemin_ip_et_jeton(tmp_path):
    src = tmp_path / "journal.log"
    src.write_text("INFO %s\nINFO %s\nINFO jeton %s\nINFO anodin\n" % (CHEMIN, IP, JETON),
                   encoding="utf-8")
    bilan = R.rediger_fichier(str(src))
    sortie = Path(bilan["destination"]).read_text(encoding="utf-8")

    # Verdict par BOOLEENS, jamais sur l'affichage.
    assert CHEMIN not in sortie, "le chemin du profil est sorti en clair"
    assert IP not in sortie, "l'adresse privee est sortie en clair"
    assert JETON not in sortie, "le jeton est sorti en clair"
    assert "anodin" in sortie, (
        "controle negatif : une ligne sans secret doit survivre intacte, sinon "
        "le filtre detruit du contenu legitime")
    assert bilan["modifie"] is True
    assert bilan["redacteur_disponible"] is True


def test_un_repli_IDENTITE_est_DECLARE_et_non_silencieux(monkeypatch):
    """Le defaut d'origine : `lambda s: s` rendait le texte intact, sans un mot.

    L'appelant croyait filtrer. Desormais le repli se NOMME, et le bilan cesse
    d'annoncer un redacteur disponible.
    """
    def _identite(s):
        return s

    _identite._nokido_redacteur = "IDENTITE — aucune redaction"
    monkeypatch.setattr(R, "_default_redactor", lambda: _identite)

    assert R._est_identite(R._default_redactor()) is True
    import tempfile
    d = Path(tempfile.mkdtemp())
    src = d / "j.log"
    src.write_text("INFO %s\n" % CHEMIN, encoding="utf-8")
    bilan = R.rediger_fichier(str(src))
    assert bilan["redacteur_disponible"] is False, (
        "un repli qui ne redige rien ne doit JAMAIS s'annoncer disponible")
    assert bilan["modifie"] is False


def test_le_CLI_existe_et_rend_un_code(tmp_path, capsys):
    """Chemin reel : `main()`, pas seulement la fonction interne."""
    src = tmp_path / "j.log"
    src.write_text("INFO %s\n" % CHEMIN, encoding="utf-8")
    code = R.main([str(src)])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "redacteur" in sortie, "le bilan doit NOMMER le porteur utilise"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
