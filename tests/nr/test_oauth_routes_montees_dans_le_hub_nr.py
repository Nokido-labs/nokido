"""NR 3/11 — E3 : les routes OAuth des clients sont MONTEES dans le hub, AVANT l'attrape-tout /.well-known.

Starlette sert la PREMIERE route qui correspond : montees apres `/.well-known/{wk_path:path}`, les metadonnees
RFC 9728/8414 ne seraient jamais servies (404 « Bearer only » meme interrupteur arme). Et `/oauth/token` doit
deleguer au flot RFC 8693 existant (`_oauth_token_route`) : les jetons de job ne changent pas.
Verification dans la SOURCE (importer nokido_hub dans un test demarrerait le hub).
"""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(encoding="utf-8")


def test_routes_oauth_montees_avant_l_attrape_tout():
    i_oauth = SRC.find("*_routes_oauth_clients()")
    i_tout = SRC.find('Route("/.well-known/{wk_path:path}"')
    assert i_oauth != -1, "routes OAuth des clients non montees dans le hub"
    assert i_tout != -1 and i_oauth < i_tout, "routes OAuth montees APRES l'attrape-tout /.well-known"


def test_jeton_delegue_au_flot_rfc8693_existant():
    assert "delegue_jeton=_oauth_token_route" in SRC


def test_le_bloc_oauth_n_utilise_que_le_journal_du_hub():
    # 3/11 : la premiere version appelait `log.warning` -- nom NON DEFINI dans nokido_hub (le journal est `logger`) :
    # NameError dans la branche d'erreur et a la premiere requete armee. Le controle de governed_edit l'a vu.
    debut = SRC.find("def _routes_oauth_clients")
    fin = SRC.find("app = Starlette(", debut)
    bloc = SRC[debut:fin]
    assert "log.warning" not in bloc.replace("logger.warning", "")
    assert "\nlogger = logging.getLogger" in SRC


def test_consentement_branche_au_tray():
    # 3/11 E4 : chaque demande d'autorisation DEPOSE un ordre oauth-consentement (a_valider) ; le decideur enregistre
    # applique la decision du tray : identite OAUTH_<client_id>, ring 3 (le plus bas).
    debut = SRC.find("def _routes_oauth_clients")
    bloc = SRC[debut:SRC.find("app = Starlette(", debut)]
    assert 'deposer("oauth-consentement"' in bloc and "a_valider=True" in bloc
    assert 'enregistrer_decideur("oauth-consentement"' in bloc
    assert "notifier=_notifier" in bloc
    assert '"OAUTH_"' in bloc
    # 3/11 (decision owner « declarer CE client ring 1 au registre ») : le ring emis vient du REGISTRE des identites
    # (lie a l'identifiant OAUTH_<client_id>, jamais au nom), 3 par defaut ; plus de ring fige.
    assert "_agent_ring(" in bloc and ", 3)" in bloc and "ring=3)" not in bloc
    # 3/11 (decision owner « ring choisi au tray + inscrit au registre ») : le ring choisi a la 2e fenetre du tray est
    # INSCRIT au registre pour CE client (le registre reste l'autorite) avant d'emettre le jeton
    assert "def _decideur(cible, oui, ring=None)" in bloc
    assert "import inscrire_client_oauth as _inscrire" in bloc and "_inscrire(_identite, ring," in bloc
    # aucun import hors du try du montage : un module illisible ne doit JAMAIS empecher le hub de demarrer
    essai = bloc[bloc.find("try:"):bloc.find("except Exception")]
    assert "forge_ordres_bureau" in essai and "forge_oauth_http" in essai
    reste = bloc[bloc.find("except Exception"):]
    assert "\n        from " not in reste and "\n        import " not in reste


def test_revocation_branchee_au_tray():
    # 3/11 (owner « fais revoquer_client ») : decideur oauth-revocation = revoquer_client + retirer_client_oauth
    debut = SRC.find("def _routes_oauth_clients")
    bloc = SRC[debut:SRC.find("app = Starlette(", debut)]
    assert 'enregistrer_decideur("oauth-revocation"' in bloc
    assert ".revoquer_client(" in bloc and "retirer_client_oauth" in bloc


def test_autorite_construite_par_l_identite_hub():
    assert 'obtenir_signataire(identite="HUB")' in SRC
    assert "dossier_defaut()" in SRC
