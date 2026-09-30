"""NR — le garde d'emission de secrets mesure-t-il bien ce qu'il pretend ?

Regle posee par l'owner le 2026-09-21, et appliquee ici a l'instrument
lui-meme :

    un instrument d'audit doit avoir un NR demontrant qu'il mesure bien
    l'objet qu'il pretend mesurer

sans quoi on obtient `code vert + mesure fausse = faux sentiment de securite`.
Trois de mes instruments l'ont prouve le meme jour : un `GROUP BY "from"` lu
par SQLite comme un LITTERAL (« 1 expediteur » pour 21 923 lignes), un regex
comptant 1956 sites dont 1955 etaient des `Path(__file__).resolve()`, et un
test qui changeait `ROOT` sans vider le cache, donc ne mesurait rien.

Ce NR verifie donc les DEUX bords, parce qu'un garde ne vaut que s'il a les
deux :

    MORD          un chemin d'emission reel est vu
    NE CRIE PAS   un homonyme innocent n'est pas compte

Toutes les entrees sont du TEXTE analyse en memoire : ce NR n'ecrit aucun
fichier, ne lit aucun secret, et ne depend d'aucune machine.
"""
import importlib

import pytest

GATE = "nokido_agent.tools.forge_secret_egress_gate"


@pytest.fixture(name="gate")
def _fx_gate():
    return importlib.import_module(GATE)


# ------------------------------------------------ 1. il MORD

@pytest.mark.parametrize("code,attendu", [
    # La faute reellement commise le 2026-09-21.
    ("print(resolve(NOM))", "resolve"),
    ("print(get_secret('X'))", "get_secret"),
    ("logger.error(vault_get(k))", "vault_get"),
    ("log.info('cle=%s', get_secret(k))", "get_secret"),
    ("print('a', healthy_key(e), 'b')", "healthy_key"),
    # f-string PASSEE A UNE SORTIE : la valeur part bien.
    ("print(f'cle={get_secret(k)}')", "get_secret"),
    ("logger.info(f'tok={vault_get(k)}')", "vault_get"),
    # La branche d'un ternaire sort, elle.
    ("print(x if cond else get_secret(k))", "get_secret"),
    # imbrication : l'appel n'est pas au premier niveau de l'argument.
    ("print(str(list(get_secret(k))))", "get_secret"),
    # argument nomme, pas positionnel.
    ("logger.warning(msg=vault_get(k))", "vault_get"),
])
def test_le_garde_VOIT_un_chemin_d_emission(gate, code, attendu):
    vus = gate.analyser_source(code)
    assert vus, "AVEUGLE sur %r" % code
    assert vus[0][2] == attendu, "a vu %r au lieu de %r" % (vus[0][2], attendu)


# ------------------------------------------------ 2. il NE CRIE PAS a faux

@pytest.mark.parametrize("code", [
    # L'homonyme qui m'a coute 1955 faux positifs le meme jour.
    "ROOT = Path(__file__).resolve().parent.parent",
    "print(Path(p).resolve())",
    "print(self.resolve(x))",
    "print(dns.resolve(host))",
    # Sortir une EMPREINTE est precisement le remede, pas la faute.
    "print(_fp(get_secret(k)))",
    # Un booleen de presence ne revele rien.
    "print(bool(get_secret(k)))",
    # Aucun appel de sortie.
    "v = get_secret(k)",
    # Un nom qui ressemble mais n'est pas dans la liste.
    "print(get_setting(k))",
])
def test_le_garde_NE_CRIE_PAS_sur_un_homonyme_ou_un_remede(gate, code):
    assert gate.analyser_source(code) == [], "FAUX POSITIF sur %r" % code


# ---- Les trois faux positifs du PREMIER passage sur le depot (2026-09-21).
# Ils valent mieux que des exemples inventes : ce sont les formes que le code
# reel emploie, et chacun aurait fait desarmer le garde.

@pytest.mark.parametrize("code,origine", [
    # forge_modal_deploy_embed.py:181 -- la valeur est un COMPARANDE ; ce qui
    # sort est "CONFORME" ou "DIVERGENTE".
    ("print('relecture %s' % ('CONFORME' if get_secret(k) == url else 'NON'))",
     "forge_modal_deploy_embed:181"),
    # idle_watchdog.py:206 -- une f-string qui BATIT un en-tete HTTP n'est pas
    # une sortie. C'est l'usage prevu du jeton.
    ("h = {'Authorization': f\"Bearer {get_secret('FORGE_MCP_TOKEN') or ''}\"}",
     "idle_watchdog:206"),
    # forge_persona_engine.py:219 -- `sign_identity` rend une SIGNATURE, faite
    # pour etre publiee. C'est `_hmac_key` qui est le secret.
    ("prompt += f'[ANCHOR_SIG:{sign_identity(prompt)}]'",
     "forge_persona_engine:219"),
])
def test_les_faux_positifs_du_premier_passage_restent_muets(gate, code, origine):
    assert gate.analyser_source(code) == [], (
        "%s redevient un faux positif : le garde serait desarme" % origine
    )


def test_la_cle_qui_PRODUIT_la_signature_reste_surveillee(gate):
    """Retirer `sign_identity` ne doit pas retirer la surveillance de la cle.
    La signature se publie ; `_hmac_key`, non."""
    assert gate.analyser_source("print(_hmac_key())")


def test_l_empreinte_et_la_valeur_ne_sont_pas_confondues(gate):
    """Le coeur de la distinction : meme fonction-secret, deux traitements.

    `print(get_secret(k))` sort la valeur ; `print(_fp(get_secret(k)))` sort
    une empreinte. Un garde qui les compte pareil rendrait le remede
    impossible a appliquer, et se ferait desarmer dans la semaine.
    """
    assert gate.analyser_source("print(get_secret(k))")
    assert gate.analyser_source("print(_fp(get_secret(k)))") == []


# ------------------------------------------------ 3. il se tient lui-meme

def test_le_garde_ne_se_lit_pas_lui_meme(gate):
    """Un instrument qui lit son propre vocabulaire se signale tout seul.

    Cinq fois paye en trois jours (audit lisant sa table INSTRUITS, DB_PATH
    pris pour la grosse base, un commentaire de migration citant l'ancien env).
    Ce fichier cite `get_secret`, `vault_get` et `print(resolve(...))` dans ses
    exemples : sans exclusion il serait son propre premier finding.
    """
    import inspect
    src = inspect.getsource(gate.analyser)
    assert "forge_secret_egress_gate.py" in src, (
        "le garde ne s'exclut pas de son propre scan"
    )


def test_le_garde_mord_sur_un_FICHIER_et_pas_seulement_sur_du_texte(gate, tmp_path,
                                                                    monkeypatch):
    """Niveau integration : `analyser` lit un vrai fichier, `analyser_source`
    non.

    Necessaire parce qu'un 0 mesure sur le depot APRES correction des faux
    positifs pose une question legitime : le garde a-t-il cesse de voir ? On
    remet donc la faute EXACTE du 2026-09-21 dans un fichier et on exige
    qu'elle soit vue par le chemin complet.
    """
    piege = tmp_path / "piege.py"
    piege.write_text("from x import resolve\nNOM = 'K'\nprint(resolve(NOM))\n",
                     encoding="utf-8")
    monkeypatch.setattr(gate, "RACINE", tmp_path, raising=True)
    vus, st = gate.analyser([piege])
    assert st["lus"] == 1 and not st["illisibles"]
    assert vus, (
        "le garde ne voit pas `print(resolve(NOM))` dans un fichier : le 0 "
        "mesure sur le depot serait un silence d'outil, pas une absence"
    )
    # `analyser` rend (rel, ligne, sortie, secret) -- l'ordre n'est pas celui
    # d'`analyser_source`, qui rend (ligne, sortie, secret).
    _rel, _ln, sortie, secret = vus[0]
    assert (sortie, secret) == ("print", "resolve")


def test_un_fichier_ILLISIBLE_est_compte_jamais_ignore(gate, tmp_path):
    """Une borne dit COMBIEN elle ecarte. Un fichier non lu laisse un etat
    INCONNU, qui n'est pas un etat SAIN."""
    import inspect
    src = inspect.getsource(gate.analyser)
    assert "illisibles" in src
    # Un chemin inexistant : la lecture echoue, et le compte doit le refleter.
    findings, st = gate.analyser([tmp_path / "absent.py"])
    assert findings == []
    assert len(st["illisibles"]) == 1, (
        "un fichier illisible n'a pas ete compte : la couverture serait "
        "surestimee en silence"
    )
    assert st["lus"] == 0


def test_la_couverture_PARTIELLE_est_annoncee(gate):
    """Le garde n'attrape que l'appel DIRECT en sortie. Une valeur passee par
    une variable intermediaire lui echappe -- et il doit le DIRE plutot que de
    laisser croire a une exhaustivite qu'il n'a pas."""
    assert gate.analyser_source("v = get_secret(k)\nprint(v)") == [], (
        "si ce cas etait attrape, la ligne ci-dessous serait a corriger"
    )
    # Meme limite pour une f-string rangee avant d'etre sortie.
    assert gate.analyser_source("x = f'{get_secret(k)}'\nprint(x)") == []
    import inspect
    src = inspect.getsource(gate.main)
    assert "PARTIELLE" in src, (
        "la limite de couverture n'est pas annoncee a l'utilisateur du garde"
    )
