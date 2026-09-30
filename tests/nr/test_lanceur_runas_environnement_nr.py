"""NR -- jeton court injecte par le superviseur (decision owner 2026-09-28), etape D : le
LANCEUR runAs ne transmet plus les secrets du superviseur.

Mesure du jour : `supervisor.ts` passe tout son environnement a chaque enfant ; pour les
services `runAs`, `tools/forge_runas_launcher.py` (sous SYSTEM) le recopie dans
l'environnement du service lance sous un AUTRE compte (`spawn_as_*_jobbed` : bloc du compte
+ `os.environ` du lanceur). Le jeton maitre et le secret JWT, poses dans l'environnement NSSM
du superviseur, atteignaient ainsi les comptes bac a sable.

Contrats :
  1. le lanceur retire, AVANT de lancer : les noms reserves, tout `FORGE_TOKEN_*`, les jetons
     du pont et du hub, la cle d'integrite, et tout `NOKIDO_JETON_COURT` HERITE ; le reste
     de l'environnement passe inchange ;
  2. un service qui declare `NOKIDO_IDENTITE` recoit le jeton court de CETTE identite, obtenu
     par l'auxiliaire du lanceur (TPM d'abord) ; aucune valeur dans les messages ;
  3. refus de l'auxiliaire : aucun jeton injecte, et c'est dit ;
  4. le service lance voit l'environnement PREPARE (chemin reel : `main` -> lancement).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRETS_HERITES = ("FORGE_MCP_TOKEN", "LAFORGE_JWT_SECRET", "LAFORGE_SUPERVISOR_TOKEN",
                   "FORGE_TOKEN_SERVICES", "FORGE_TOKEN_CLAUDE", "FORGE_BRIDGE_TOKEN",
                   "LAFORGE_HUB_TOKEN", "HUB_TOKEN", "NOKIDO_HMAC_KEY", "NOKIDO_JETON_COURT")
ORDINAIRES = {"PYTHONNOUSERSITE": "1", "NOKIDO_NR_ORDINAIRE": "garde"}


def _lanceur():
    spec = importlib.util.spec_from_file_location("nr_runas_launcher", ROOT / "tools/forge_runas_launcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(monkeypatch):
    for k in SECRETS_HERITES:
        monkeypatch.setenv(k, "herite-de-test")
    for k, v in ORDINAIRES.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NOKIDO_IDENTITE", raising=False)
    # Le code pose NOKIDO_JETON_FICHIER lui-meme : l'enregistrer ici pour qu'il soit retire
    # apres le test (hermetique, quel que soit l'etat de la machine).
    monkeypatch.setenv("NOKIDO_JETON_FICHIER", "x")
    monkeypatch.delenv("NOKIDO_JETON_FICHIER")
    return monkeypatch


def test_les_secrets_herites_ne_passent_pas_le_reste_si(env):
    m = _lanceur()
    m._preparer_environnement(os.environ)
    restes = [k for k in SECRETS_HERITES if k in os.environ]
    ok = (restes, {k: os.environ.get(k) for k in ORDINAIRES} == ORDINAIRES)
    assert ok == ([], True)


def test_une_identite_declaree_recoit_son_jeton_court(env, capsys):
    m = _lanceur()
    appels: list = []
    env.setattr(m, "_emettre_jeton", lambda ident: appels.append(ident) or (0, "jeton-court-de-test", "TPM"))
    env.setattr(m, "_racine_sure", lambda racine: "racine de test absente")
    env.setenv("NOKIDO_IDENTITE", "services")
    message = m._preparer_environnement(os.environ)
    ok = (appels, os.environ.get("NOKIDO_JETON_COURT"), "jeton-court-de-test" in message,
          "herite-de-test" in message)
    assert ok == (["SERVICES"], "jeton-court-de-test", False, False)


def test_un_refus_de_l_auxiliaire_n_injecte_rien_et_le_dit(env):
    m = _lanceur()
    env.setattr(m, "_emettre_jeton", lambda ident: (3, "", "ring <= DEV"))
    env.setenv("NOKIDO_IDENTITE", "UNE_IDENTITE_OWNER")
    message = m._preparer_environnement(os.environ)
    ok = ("NOKIDO_JETON_COURT" in os.environ, "REFUS" in message)
    assert ok == (False, True)


@pytest.mark.skipif(sys.platform != "win32", reason="lanceur runAs : Windows")
def test_le_service_lance_voit_l_environnement_prepare(env):
    m = _lanceur()
    vus: dict = {}

    def _faux_lancement(command, online=False, cwd=None):
        vus.update(os.environ)
        raise m.SandboxError("arret du test apres capture")

    env.setattr(m, "spawn_as_sandbox_jobbed", _faux_lancement)
    env.setattr(m, "_emettre_jeton", lambda ident: (4, "", "aucun chemin"))
    env.setattr(sys, "argv", ["forge_runas_launcher.py", "sandbox-online", "cmd.exe", "/c", "echo"])
    rc = m.main()
    restes = [k for k in SECRETS_HERITES if k in vus]
    assert (rc, restes, vus.get("NOKIDO_NR_ORDINAIRE")) == (1, [], "garde")
