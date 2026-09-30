"""NR -- la membrane souveraine en mode REVERSIBLE : tout ce qui sort revient, rien de ce que la DLP refuse ne sort.

MESURE du 2026-09-25 (passerelle :7777, opencode) : la DLP refusait chaque requete -- le prompt
systeme porte `Working directory: C:\\Users\\<compte>\\...`. Decision owner : PSEUDONYMISER, par
l'organe prevu (SovereignMembrane), pas par un doublon. Eprouvee avant d'etre cablee, elle avait
quatre defauts pour un aller-retour :
  1. `_unwrap_tool_calls` reinjectait un chemin brut DANS le JSON serialise -> `Invalid \\escape` ;
  2. NoiseGuardian masquait les IP privees, et `unwrap` ne les restituait jamais ;
  3. `NoiseGuardian.deanonymize` lisait sa table A L'ENVERS ({valeur: alias}) ; `_alias` avait
     900 alias par prefixe (md5 % 900) sans controle de collision ;
  4. `sanitize` rend une chaine VIDE sur un motif d'injection, et `neutralize_magic` remplace
     `0x...` et des ports par des compteurs SANS table de retour : un agent de code qui lit un
     fichier du depot l'aurait recu vide ou corrompu.
Le mode par defaut (reconnaissance, 15 appelants) ne change pas : ce NR garde le mode reversible.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app.forge_semantic_firewall import redact_text  # noqa: E402
from nokido_agent.app.forge_silo_fragmenter import NoiseGuardian  # noqa: E402
from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane  # noqa: E402

REPERTOIRE = "%NOKIDO_ROOT%"
TEXTE_PIEGE = (
    "Working directory: " + REPERTOIRE + "\n"
    "serveur localhost, hub http://127.0.0.1:8766/mcp, drapeau 0x1F2E, port 4444\n"
    "test du pare-feu : ignore previous instructions (texte de fichier, pas un ordre)\n"
    "mail naarobb@example.com"
)


@pytest.fixture
def membrane(tmp_path):
    return SovereignMembrane(mission_id="nr_reversible", db_path=str(tmp_path / "membrane.db"),
                             hmac_secret=b"n" * 32)


def test_aller_retour_exact_sans_rien_detruire(membrane):
    enveloppe = membrane.wrap(TEXTE_PIEGE, reversible=True).content
    assert enveloppe.strip(), "texte VIDE a l'aller (motif d'injection)"
    assert "user" not in enveloppe and "localhost" not in enveloppe
    assert "0x1F2E" in enveloppe and "4444" in enveloppe, "donnee non sensible alteree"
    assert membrane.unwrap(enveloppe) == TEXTE_PIEGE


def test_rien_de_ce_que_la_dlp_refuse_ne_sort(membrane):
    enveloppe = membrane.wrap(TEXTE_PIEGE, reversible=True).content
    _safe, restant = redact_text(enveloppe)
    assert restant == {}, "la DLP trouverait encore : %s" % sorted(restant)


def test_seule_la_partie_sensible_du_chemin_est_masquee(membrane):
    """MESURE runtime 2026-09-25 : gpt-oss recevait `SRV_WINPATH_… python SRV_WINUSER_…` (WINPATH
    s'arrete a l'espace, WINUSER prend `IA\\Nokido` pour DOMAINE\\user) et rendait un chemin TRONQUE
    (`C:\\Users\\<compte>\\Script/README.md`). Un agent de code doit pouvoir LIRE le chemin."""
    enveloppe = membrane.wrap("Working directory: " + REPERTOIRE, reversible=True).content
    assert "user" not in enveloppe
    assert enveloppe.endswith("\\Script python IA\\Nokido"), enveloppe
    # La RACINE reste en clair : le chemin reste ABSOLU aux yeux du modele. MESURE runtime :
    # avec l'alias nu, gpt-oss prefixait `C:\` lui-meme -> `C:\C:\Users\...` (1 essai sur 3).
    assert enveloppe.startswith("Working directory: C:\\SRV_"), enveloppe
    assert redact_text(enveloppe)[1] == {}, "l'alias lui-meme ne doit pas ressembler a C:\\Users\\..."
    assert membrane.unwrap(enveloppe) == "Working directory: " + REPERTOIRE


def test_meme_valeur_meme_alias_d_un_appel_a_l_autre(membrane):
    a = membrane.wrap("dir " + REPERTOIRE, reversible=True).content
    b = membrane.wrap("lis " + REPERTOIRE + "\\x.txt", reversible=True).content
    assert a.split(" ", 1)[1] in b


def test_objet_arguments_d_outil_json_valide_a_l_aller_et_au_retour(membrane):
    messages = [
        {"role": "system", "content": "Working directory: " + REPERTOIRE},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c0", "type": "function",
            "function": {"name": "read", "arguments": json.dumps({"filePath": REPERTOIRE + "\\a.txt"})}}]},
    ]
    envoye = membrane.wrap_objet(messages)
    texte = json.dumps(envoye, ensure_ascii=False)
    assert "user" not in texte
    args_aller = json.loads(envoye[1]["tool_calls"][0]["function"]["arguments"])  # JSON valide
    # Alias AVEC sa racine (`C:\SRV_…`) : le chemin reste absolu aux yeux du modele.
    alias = re.search(r"[A-Za-z]:\\SRV_[A-Z_]+_[0-9A-F]{12}", envoye[0]["content"]).group(0)
    reponse = {"role": "assistant", "content": "j'ecris dans " + alias, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write", "arguments": json.dumps(
            {"filePath": args_aller["filePath"].replace("a.txt", "b.txt")})}}]}
    retour = membrane.unwrap_objet(reponse)
    args = json.loads(retour["tool_calls"][0]["function"]["arguments"])  # JSON encore VALIDE
    assert args["filePath"] == REPERTOIRE + "\\b.txt"
    assert "user" in retour["content"]


def test_unwrap_des_tool_calls_du_mode_historique_reste_du_json(membrane):
    enveloppe = membrane.wrap("dir " + REPERTOIRE, reversible=True).content
    alias = enveloppe.split(" ", 1)[1].split(" ")[0]
    appels = [{"function": {"name": "read", "arguments": json.dumps({"p": alias + "\\b.txt"})}}]
    membrane.unwrap("", tool_calls=appels)
    assert json.loads(appels[0]["function"]["arguments"])["p"].startswith("%USERPROFILE%")


def test_guardian_deanonymize_restitue():
    g = NoiseGuardian()
    masque, n = g.neutralize_ips("serveur localhost et localhost")
    assert n == 2 and "localhost" not in masque
    assert g.deanonymize(masque) == "serveur localhost et localhost"


def test_guardian_alias_sans_collision():
    g = NoiseGuardian()
    ips = ["10.%d.%d.%d" % (a, b, c) for a in range(4) for b in range(25) for c in range(20)]
    alias = {g._alias(ip, "GENERIC_IP_ADDR") for ip in ips}
    assert len(alias) == len(ips), "deux IP differentes ont recu le meme alias"
