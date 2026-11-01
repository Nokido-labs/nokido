"""NR 29/10 (owner : RSI sur l'organe immunitaire) -- banc `redaction_dlp` : juge deterministe du caviardage de
forge_semantic_firewall.redact_text. Garde du banc : (1) le corpus ne contient AUCUNE valeur sensible en clair (les
valeurs sont fabriquees par le juge) ; (2) les protections acquises tiennent (email, IP, chemin Windows caviardes) --
un candidat ne gagne jamais un axe en en cassant un autre ; (3) le banc est declare et fige ses empreintes.
Mesure de reference 29/10 : F1 0,87 (fuites : cle de type AKIA, mot de passe en JSON ; URL caviardee en entier)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT), str(ROOT.parent)]

from bancs import banc_redaction_dlp as J  # noqa: E402


def test_le_corpus_ne_porte_aucune_valeur_sensible():
    brut = J.CORPUS.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{20,}|gh" + r"p_[A-Za-z0-9]{20,}|AK" + r"IA[A-Z0-9]{12,}|eyJ[A-Za-z0-9]{10,}", brut)
    assert all("{" in json.loads(l)["gabarit"] or not json.loads(l)["sensibles"] for l in brut.splitlines() if l.strip())


def test_les_protections_acquises_tiennent():
    import forge_semantic_firewall as F
    for nature in ("EMAIL", "IP", "CHEMIN_WIN"):
        valeur = J._FABRIQUES[nature]("garde#" + nature)
        rendu, _m = F.redact_text("trace : %s fin" % valeur)
        assert valeur not in rendu, "protection perdue : %s" % nature


def test_le_juge_mesure_et_le_banc_est_declare():
    r = J.mesurer()
    assert 0.0 <= r["metrique"] <= 1.0 and r["cas"] >= 16
    cfg = json.loads((ROOT / "config" / "bancs_amelioration.json").read_text(encoding="utf-8"))
    b = cfg["redaction_dlp"]
    assert "tools/bancs/corpus_redaction_dlp.jsonl" in b["juge"]["empreintes"]
    assert "tests/nr/test_banc_redaction_dlp_nr.py" in b["garde_tests"]
