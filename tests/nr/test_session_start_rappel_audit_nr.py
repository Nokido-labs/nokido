"""NR -- un changement de modele ou de CLI rappelle l'audit de prompts au demarrage de session.

Owner, 2026-09-26 : « il aura fallu quand meme que je tape la commande de moi-meme ». L'audit
des surfaces toujours chargees (skill claude-api, argument prompt-audit) n'etait declenche par
rien : ni le changement de modele, ni celui de la version de Claude Code.

Contrat garde ici :
  1. le hook SessionStart lit `model` dans son entree (champ documente, doc hooks ingeree le
     26/09 : « "model": "claude-opus-5" ») ; la variante de contexte (`[1m]`) n'est pas un
     autre modele ;
  2. la version du CLI se lit dans le transcript (`"version"` des lignes JSONL) ; illisible, elle
     reste INCONNUE -- jamais devinee, jamais comptee comme inchangee ni comme changee ;
  3. le rappel revient a CHAQUE demarrage tant que l'audit n'est pas acquitte (`--audit-fait`) :
     un rappel unique se perd, c'est exactement ce qui s'est passe ;
  4. un etat sans audit enregistre n'est PAS un etat audite (UNKNOWN != NO) ;
  5. le chemin reel `--audit-fait` (point d'entree `__main__`) acquitte et fait taire le rappel.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python x2 (l.179)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "tools" / "claude_session_start.py"


def _module():
    spec = importlib.util.spec_from_file_location("claude_session_start_nr", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _transcript(tmp_path, versions):
    p = tmp_path / "session.jsonl"
    lignes = [json.dumps({"type": "user", "version": v}) for v in versions]
    lignes.append(json.dumps({"type": "summary"}))
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return p


def test_la_variante_de_contexte_n_est_pas_un_autre_modele():
    m = _module()
    assert m.modele_normalise("claude-opus-5-5[1m]") == m.modele_normalise("claude-opus-5-5")
    assert m.modele_normalise("") is None and m.modele_normalise(None) is None


def test_la_version_se_lit_dans_le_transcript(tmp_path):
    m = _module()
    assert m.version_du_transcript(_transcript(tmp_path, ["2.1.280", "2.1.282"])) == "2.1.282"
    assert m.version_du_transcript(tmp_path / "absent.jsonl") is None
    assert m.version_du_transcript(_transcript(tmp_path, [])) is None


def test_un_changement_de_modele_rappelle_l_audit():
    m = _module()
    etat = {"audite": {"modele": "claude-opus-5", "version": "2.1.282"}}
    texte, etat2 = m.rappel_audit(etat, "claude-opus-5-5[1m]", "2.1.282")
    assert texte and "claude-opus-5 -> claude-opus-5-5" in texte
    assert "prompt-audit" in texte and "--audit-fait" in texte
    assert etat2["vu"]["modele"] == "claude-opus-5-5"


def test_un_changement_de_version_rappelle_l_audit():
    m = _module()
    etat = {"audite": {"modele": "claude-opus-5-5", "version": "2.1.282"}}
    texte, _ = m.rappel_audit(etat, "claude-opus-5-5", "2.1.290")
    assert texte and "2.1.282 -> 2.1.290" in texte


def test_rien_n_a_change_rien_n_est_dit():
    m = _module()
    etat = {"audite": {"modele": "claude-opus-5-5", "version": "2.1.282"}}
    assert m.rappel_audit(etat, "claude-opus-5-5[1m]", "2.1.282")[0] is None


def test_une_version_illisible_n_est_ni_changee_ni_inchangee():
    m = _module()
    etat = {"audite": {"modele": "claude-opus-5-5", "version": "2.1.282"},
            "vu": {"modele": "claude-opus-5-5", "version": "2.1.282"}}
    texte, etat2 = m.rappel_audit(etat, "claude-opus-5-5", None)
    assert texte is None
    assert etat2["vu"]["version"] == "2.1.282", "une lecture illisible a efface la derniere version connue"


def test_sans_audit_enregistre_on_ne_se_croit_pas_audite():
    m = _module()
    texte, _ = m.rappel_audit({}, "claude-opus-5-5", "2.1.282")
    assert texte and "prompt-audit" in texte


def test_le_rappel_revient_tant_qu_il_n_est_pas_acquitte(tmp_path):
    m = _module()
    etat_f = tmp_path / "etat.json"
    etat_f.write_text(json.dumps({"audite": {"modele": "claude-opus-5", "version": "2.1.282"}}), encoding="utf-8")
    entree = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "model": "claude-opus-5-5",
                         "transcript_path": str(_transcript(tmp_path, ["2.1.282"]))})
    assert m.section_audit(entree, etat_f)
    assert m.section_audit(entree, etat_f), "le rappel s'est tu sans acquittement"


# -- Doc hooks (ingeree 26/09) : « Only SessionStart hooks can receive a `model` field, and Claude Code
# doesn't always include it. PreModelSwitch and PostModelSwitch hooks receive `from_model` and
# `to_model` instead, so use a PostModelSwitch hook to follow the model as it changes during a session. »

def _etat(tmp_path, audite, vu=None):
    f = tmp_path / "etat.json"
    d = {"audite": audite}
    if vu:
        d["vu"] = vu
    f.write_text(json.dumps(d), encoding="utf-8")
    return f


def test_post_model_switch_rappelle_l_audit(tmp_path):
    m = _module()
    f = _etat(tmp_path, {"modele": "claude-opus-5-5", "version": "2.1.282"})
    entree = json.dumps({"hook_event_name": "PostModelSwitch", "source": "user",
                         "from_model": "claude-opus-5-5", "to_model": "claude-fable-5-1[1m]"})
    texte = m.section_changement_modele(entree, f)
    assert texte and "claude-opus-5-5 -> claude-fable-5-1" in texte and "prompt-audit" in texte
    assert json.loads(f.read_text(encoding="utf-8"))["vu"]["modele"] == "claude-fable-5-1"


def test_post_model_switch_vers_le_modele_audite_ne_dit_rien(tmp_path):
    m = _module()
    f = _etat(tmp_path, {"modele": "claude-opus-5-5", "version": "2.1.282"})
    entree = json.dumps({"hook_event_name": "PostModelSwitch", "source": "resume", "to_model": "claude-opus-5-5"})
    assert m.section_changement_modele(entree, f) is None


def test_post_model_switch_sans_to_model_ne_devine_rien(tmp_path):
    m = _module()
    f = _etat(tmp_path, {"modele": "claude-opus-5-5"}, vu={"modele": "claude-opus-5-5"})
    texte = m.section_changement_modele(json.dumps({"hook_event_name": "PostModelSwitch"}), f)
    assert texte is None or "ILLISIBLE" in texte
    assert json.loads(f.read_text(encoding="utf-8"))["vu"]["modele"] == "claude-opus-5-5"


def test_sessionstart_sans_model_se_tait_quand_un_modele_est_connu(tmp_path):
    m = _module()
    f = _etat(tmp_path, {"modele": "claude-opus-5-5", "version": "2.1.282"},
              vu={"modele": "claude-opus-5-5", "version": "2.1.282"})
    assert m.section_audit(json.dumps({"source": "startup"}), f) is None


def test_sessionstart_sans_model_le_dit_quand_aucun_modele_n_a_jamais_ete_vu(tmp_path):
    m = _module()
    f = _etat(tmp_path, {"modele": "claude-opus-5-5", "version": "2.1.282"})
    texte = m.section_audit(json.dumps({"source": "startup"}), f)
    assert texte and "ILLISIBLE" in texte


def test_reprise_cache_expire_annonce_le_cout():
    m = _module()
    texte = m.alerte_cout_reprise(json.dumps({
        "source": "resume", "seconds_since_last_response": 5400, "context_tokens": 182340,
        "prompt_cache_likely_expired": True, "estimated_cache_write_usd": 1.1396}))
    assert texte and "182" in texte and "1.14" in texte and "compact" in texte


def test_cache_frais_ou_champs_absents_rien_n_est_dit():
    m = _module()
    assert m.alerte_cout_reprise(json.dumps({"source": "resume", "prompt_cache_likely_expired": False,
                                             "context_tokens": 182340})) is None
    assert m.alerte_cout_reprise(json.dumps({"source": "startup"})) is None
    assert m.alerte_cout_reprise("pas du json") is None


def test_le_point_d_entree_changement_modele(tmp_path):
    f = _etat(tmp_path, {"modele": "claude-opus-5-5", "version": "2.1.282"})
    env = dict(os.environ, NOKIDO_CLAUDE_AUDIT_ETAT=str(f))
    entree = json.dumps({"hook_event_name": "PostModelSwitch", "source": "user",
                         "from_model": "claude-opus-5-5", "to_model": "claude-sonnet-5"})
    r = subprocess.run([sys.executable, str(SCRIPT), "--changement-modele"], cwd=ROOT, env=env, input=entree,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert "claude-opus-5-5 -> claude-sonnet-5" in r.stdout
    assert "LAFORGE_PYTHON =" not in r.stdout and "INBOX" not in r.stdout, "le hook complet a tourne"


def test_le_point_d_entree_audit_fait_acquitte(tmp_path):
    etat_f = tmp_path / "etat.json"
    etat_f.write_text(json.dumps({"audite": {"modele": "claude-opus-5", "version": "2.1.282"},
                                  "vu": {"modele": "claude-opus-5-5", "version": "2.1.290"}}), encoding="utf-8")
    env = dict(os.environ, NOKIDO_CLAUDE_AUDIT_ETAT=str(etat_f))
    r = subprocess.run([sys.executable, str(SCRIPT), "--audit-fait"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    etat = json.loads(etat_f.read_text(encoding="utf-8"))
    assert etat["audite"]["modele"] == "claude-opus-5-5" and etat["audite"]["version"] == "2.1.290"
    m = _module()
    entree = json.dumps({"model": "claude-opus-5-5", "transcript_path": str(_transcript(tmp_path, ["2.1.290"]))})
    assert m.section_audit(entree, etat_f) is None
