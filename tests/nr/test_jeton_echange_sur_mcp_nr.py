"""NR -- option B (owner 30/10) : un jeton d'acces ECHANGE (RFC 8693) n'est accepte sur /mcp qu'en schema DPoP avec une
preuve LIEE (RFC 9449), et sa PORTEE est appliquee outil par outil par la garde du hub ; trusted_script n'est jamais
accorde depuis le bac.

Mesures du 30/10 : _resolve_ring n'acceptait que le schema Bearer ; la garde forge_hub_gate ne controlait aucune portee ;
et le chemin /mcp appelle _tool_call SANS jeton (nokido_hub.py:3611), donc un controle qui lirait le jeton dans la garde
ne verrait jamais rien. Les portees de la requete passent par un contextvar pose a l'authentification.
Secret factice, cle ephemere : aucun secret reel.
"""
import ast
import asyncio
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE), str(RACINE.parent)]
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from app import forge_dpop  # noqa: E402
from app import forge_token_exchange as tx  # noqa: E402

SECRET = b"secret-factice-de-test-0123456789"
URI = "http://127.0.0.1:8766/mcp"


def _jeton(scopes, cle):
    jkt = forge_dpop.thumbprint(forge_dpop.jwk_public(cle))
    return tx.emettre_jeton_lie("JOB", 3, scopes, jkt, 300, SECRET)


def test_jeton_echange_accepte_en_dpop_avec_preuve_liee():
    cle = ec.generate_private_key(ec.SECP256R1())
    j = _jeton(["task:status"], cle)
    preuve = forge_dpop.creer_preuve("POST", URI, jeton_acces=j, cle=cle)
    res = tx.resoudre_jeton_echange("DPoP " + j, preuve, "POST", URI, SECRET)
    assert res[:2] == (3, "JOB")
    assert tx.PORTEES_REQUETE.get() == ["task:status"]


def test_jeton_lie_presente_en_bearer_refuse():
    cle = ec.generate_private_key(ec.SECP256R1())
    j = _jeton(["task:status"], cle)
    preuve = forge_dpop.creer_preuve("POST", URI, jeton_acces=j, cle=cle)
    res = tx.resoudre_jeton_echange("Bearer " + j, preuve, "POST", URI, SECRET)
    assert res is not None and res[0] == -1


def test_preuve_d_une_autre_cle_refusee():
    cle, autre = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    j = _jeton(["task:status"], cle)
    preuve = forge_dpop.creer_preuve("POST", URI, jeton_acces=j, cle=autre)
    assert tx.resoudre_jeton_echange("DPoP " + j, preuve, "POST", URI, SECRET)[0] == -1


def test_jeton_d_un_autre_format_laisse_le_chemin_existant():
    assert tx.resoudre_jeton_echange("Bearer abc.def", "", "POST", URI, SECRET) is None
    assert tx.resoudre_jeton_echange("", "", "POST", URI, SECRET) is None


def _gate(portees, name, args):
    from app import forge_hub_gate as G
    jeton = tx.PORTEES_REQUETE.set(portees)
    try:
        return asyncio.run(G._check_portee(name, args, "JOB", 3, ""))
    finally:
        tx.PORTEES_REQUETE.reset(jeton)


def test_la_garde_applique_la_portee_outil_par_outil():
    assert _gate(["task:status"], "task", {"action": "status"})[0] is True
    assert _gate(["task:status"], "rag", {"action": "search"})[0] is False
    assert _gate(["task:status"], "task", {"action": "assign"})[0] is False
    assert _gate(["ask:appel"], "ask", {})[0] is True
    assert _gate(["ask:appel", "rag:ingest"], "run", {"action": "trusted_script"})[0] is False
    assert _gate(None, "rag", {"action": "search"})[0] is True  # pas un jeton echange : non applicable


def test_portee_est_un_controle_gouverne_de_la_garde():
    from app import forge_hub_gate as G
    assert "portee" in G._ORDER and "portee" in G._GOVERNED and "portee" in G._DEFAULT_CHECKS


def test_aucune_politique_n_accorde_trusted_script():
    from app import forge_oauth_route as O
    for ident, pol in O.POLITIQUE_DEFAUT.items():
        assert not any(s.startswith("run:") for s in pol.get("scopes", [])), ident


def _requete_hub(monkeypatch, jeton, preuve, etat):
    from types import SimpleNamespace
    sys.path.insert(0, str(RACINE / "tools"))
    import nokido_hub as hub
    from nokido_agent.app import forge_oauth_route as O2
    monkeypatch.setattr(O2, "_secret", lambda: SECRET)
    return hub, lambda: SimpleNamespace(headers={"Authorization": "DPoP " + jeton, "DPoP": preuve},
                                        client=SimpleNamespace(host="127.0.0.1"), method="POST", url=URI, state=etat)


def test_le_hub_resout_le_jeton_echange_une_fois_par_requete(monkeypatch):
    """Mesure reelle du 30/10 (job_0b2250468862) : _resolve_ring est appele PLUSIEURS fois par requete ; le 2e passage
    voyait le meme jti -> « jti deja vu : rejeu » -> 401. Resolution mise en cache dans request.state (partage par
    tous les objets Request d'une meme requete)."""
    from types import SimpleNamespace
    from nokido_agent.app import forge_dpop as dp2
    from nokido_agent.app import forge_token_exchange as tx2
    cle = ec.generate_private_key(ec.SECP256R1())
    j = tx2.emettre_jeton_lie("JOB", 3, ["task:status"], dp2.thumbprint(dp2.jwk_public(cle)), 300, SECRET)
    hub, req = _requete_hub(monkeypatch, j, dp2.creer_preuve("POST", URI, jeton_acces=j, cle=cle), SimpleNamespace())
    assert hub._resolve_ring(req()) == (3, "JOB")
    assert hub._resolve_ring(req()) == (3, "JOB")  # meme requete, 2e passage : pas un rejeu


def test_un_refus_rend_un_code_court(monkeypatch):
    """Le 2e element de _resolve_ring sert de NOM d'agent en aval (presence, journal) : un motif long y faisait echouer
    l'ecriture de fichiers de presence (OSError, 30/10). Code court ; le motif detaille va au journal."""
    from types import SimpleNamespace
    from nokido_agent.app import forge_dpop as dp2
    from nokido_agent.app import forge_token_exchange as tx2
    cle, autre = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    j = tx2.emettre_jeton_lie("JOB", 3, ["task:status"], dp2.thumbprint(dp2.jwk_public(cle)), 300, SECRET)
    hub, req = _requete_hub(monkeypatch, j, dp2.creer_preuve("POST", URI, jeton_acces=j, cle=autre), SimpleNamespace())
    assert hub._resolve_ring(req()) == (-1, "dpop_refuse")


def test_le_hub_resout_le_jeton_echange_avant_tout_autre_chemin():
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ring")
    appels = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
              and getattr(c.func, "id", getattr(c.func, "attr", "")) == "resoudre_jeton_echange"]
    assert appels, "_resolve_ring n'appelle pas resoudre_jeton_echange"
