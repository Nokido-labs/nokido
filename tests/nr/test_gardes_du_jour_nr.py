# -*- coding: utf-8 -*-
"""Non-regression — quatre contrats repares le 2026-08-28.

1. M2M : la limite de mots vise la PROSE, pas le VOLUME. Retiree entierement, elle
   laissait emballer 600 mots dans {"intent": ..., "content": ...} pour eteindre le
   garde ; appliquee a tous les champs, elle criait sur un pointer_ref legitime.

2. Capteur de vitaux : `feed(sample, now=...)`. Sans horloge injectable, le refractaire
   de 1800 s court en temps MURAL — un rejeu de 19 000 echantillons ne rend qu'UN tir
   par canal, et le capteur ne peut etre recalibre qu'en production, sur un evenement
   qu'on ne controle pas.

3. Carte du corps : le recensement ecrit `organ_map_full.json` en FUSION. Onze modules
   la LISENT et plus rien ne l'ecrivait depuis la perte de ses pieces generatrices ;
   mais l'ecraser detruirait les classements d'autorite qu'elle porte.

4. Gate de capacites : les regles dependent du COMPTE. `action=shell` est cmd.exe sous
   le defaut et PowerShell sous trusted/online — une regle qui ignore `sandbox`
   conseille l'inverse de la bonne forme une fois sur deux.

Hermetique : aucun reseau, aucune ecriture hors tmp_path, aucun service.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ─────────────────────────────────────────────────── 1. contrat M2M

def _valide(payload):
    import forge_m2m_protocol as m2m
    return m2m.validate("notify", payload)


def test_m2m_signale_la_prose_longue():
    """LE cas : de la prose emballee dans un champ structure doit rester visible."""
    r = _valide({"intent": "OK_DONE", "pointer_ref": "bb:x",
                 "content": " ".join(["mot"] * 300)})
    assert r["code"] == "M2M_WARN_PROSE", r
    assert any("content" in v for v in r.get("violations") or []), r


def test_m2m_laisse_passer_un_pointeur_volumineux():
    """Contre-epreuve : la limite vise la prose, pas la taille."""
    ref = "commits:" + ",".join("abc%04d" % i for i in range(80))
    assert _valide({"intent": "OK_DONE", "pointer_ref": ref})["code"] == "M2M_OK"


def test_m2m_laisse_passer_des_donnees_volumineuses():
    mesures = json.dumps({"ax%d" % i: {"rappel": 0.0} for i in range(40)})
    r = _valide({"intent": "OK_DONE", "pointer_ref": "bb:x", "mesures": mesures})
    assert r["code"] == "M2M_OK", r


def test_m2m_message_conforme():
    assert _valide({"intent": "OK_DONE", "pointer_ref": "bb:x", "note": "fait"})["code"] == "M2M_OK"


# ──────────────────────────────────── 2. le capteur reste rejouable

def _moniteur_repli():
    """Le repli statique suffit : il exerce le MEME refractaire, sans exiger snntorch."""
    mod = pytest.importorskip("forge_snn_monitor")
    return mod, mod.SNNMonitor(enabled=False)


def test_feed_accepte_une_horloge():
    """Sans ce parametre, rejouer un historique est impossible."""
    import inspect
    mod, _ = _moniteur_repli()
    assert "now" in inspect.signature(mod.SNNMonitor.feed).parameters, (
        "feed() n'accepte plus d'horloge : le refractaire retombe en temps mural et "
        "tout rejeu ne rendra qu'un seul tir par canal")


def test_refractaire_suit_l_horloge_fournie():
    mod, mon = _moniteur_repli()
    haut = {"ram_pct": 99.0, "cpu_pct": 1.0, "gpu_pct": 1.0}
    t0 = 1_000_000.0
    assert mon.feed(haut, now=t0)["ram"] is True, "premier depassement non signale"
    # dans la periode refractaire, meme charge : silence attendu
    assert mon.feed(haut, now=t0 + mod._REFRACTORY_S / 2)["ram"] is False
    # au-dela, le capteur doit reparler — sur l'horloge FOURNIE, pas l'horloge murale
    assert mon.feed(haut, now=t0 + mod._REFRACTORY_S + 1)["ram"] is True, (
        "le refractaire ne suit pas l'horloge passee a feed()")


def test_sous_le_seuil_le_capteur_se_tait():
    """Contre-epreuve : le garde ne doit pas rendre le capteur bavard."""
    _mod, mon = _moniteur_repli()
    assert mon.feed({"ram_pct": 10.0, "cpu_pct": 1.0, "gpu_pct": 1.0}, now=1.0)["ram"] is False


# ─────────────────────────────── 3. la carte du corps a un ecrivain

def test_le_recensement_ecrit_la_carte(tmp_path: Path):
    census = pytest.importorskip("forge_module_census")
    assert hasattr(census, "_maj_carte"), (
        "le recensement n'ecrit plus la carte : elle redeviendrait un fichier que "
        "onze modules lisent et que personne ne met a jour")
    rows = [("app/forge_neuf.py", "Memoire (hippocampe/RAG)", 10, "")]
    census._maj_carte(rows, tmp_path)
    d = json.loads((tmp_path / "organ_map_full.json").read_text(encoding="utf-8"))
    assert d["module_organ"]["forge_neuf.py"] == "Memoire (hippocampe/RAG)"
    assert d.get("generated_at"), "sans horodatage, la peremption n'est pas mesurable"


def test_la_carte_n_ecrase_jamais_une_entree(tmp_path: Path):
    """L'entree existante porte une autorite que le recensement ne sait pas reproduire."""
    census = pytest.importorskip("forge_module_census")
    (tmp_path / "organ_map_full.json").write_text(json.dumps({
        "module_organ": {"forge_x.py": "ORGANE_D_AUTORITE"},
        "provenance": {"llm": 1},
    }), encoding="utf-8")
    _n, _ajouts, divergences = census._maj_carte(
        [("app/forge_x.py", "AUTRE_ORGANE_DEVINE", 10, "")], tmp_path)
    d = json.loads((tmp_path / "organ_map_full.json").read_text(encoding="utf-8"))
    assert d["module_organ"]["forge_x.py"] == "ORGANE_D_AUTORITE", "classement ecrase"
    assert divergences == 1, "la divergence doit etre COMPTEE, pas tue"


def test_un_module_non_classe_reste_hors_carte(tmp_path: Path):
    """L'absence EST le signal : inventer une etiquette la propagerait en RAG."""
    census = pytest.importorskip("forge_module_census")
    census._maj_carte([("app/forge_y.py", "? non classe", 10, "")], tmp_path)
    d = json.loads((tmp_path / "organ_map_full.json").read_text(encoding="utf-8"))
    assert "forge_y.py" not in d["module_organ"]


# ──────────────────────────── 4. le gate connait le shell de chaque compte

def test_gate_choisit_les_regles_du_compte():
    gate = pytest.importorskip("hook_capability_gate")
    cmd = gate._regles_du_shell({"action": "shell", "sandbox": "local"})
    ps = gate._regles_du_shell({"action": "shell", "sandbox": "trusted"})
    assert cmd != ps, "le gate donne les memes conseils quel que soit le compte"

    def _tire(regles, texte):
        return [m for rx, m in regles if rx.search(texte)]

    assert _tire(ps, "if exist C:\\x (echo a)"), "syntaxe cmd non signalee sous PowerShell"
    assert not _tire(cmd, "if exist C:\\x (echo a)"), "syntaxe cmd signalee a tort sous cmd.exe"


def test_gate_ignore_les_commandes_seulement_citees():
    """Un message de commit CITE des commandes ; il n'en execute aucune."""
    gate = pytest.importorskip("hook_capability_gate")
    txt = gate._texte_commande({"command": 'git commit -m "on cite dock' + 'er ps -a ici"'})
    assert "ps -a" not in txt, "le contenu d'un -m est encore scanne : nudges a faux"


# ------------------------------- le capteur spiking DIT sous quel backend il tourne

def test_snn_etat_distingue_le_backend_du_repli(monkeypatch):
    """Mesure 2026-08-29 : aucun journal vivant ne portait la moindre trace « snn ».
    `available()` ne rend qu'un booleen, qui ne separe pas « LIF snntorch » de
    « seuils statiques » — la difference meme qui s'est perdue le 28/08, quand
    503 tirs sont partis en repli sans que personne ne le voie."""
    mon = pytest.importorskip("forge_snn_monitor")
    monkeypatch.setattr(mon, "_SNN_OK", True)
    assert mon.etat()["backend"] == "snntorch"
    monkeypatch.setattr(mon, "_SNN_OK", False)
    e = mon.etat()
    assert e["backend"] == "repli-statique" and e["snntorch"] is False
    assert "seuils" in e and "refractaire_s" in e, "un etat sans reglages n'est pas auditable"


def test_snn_annonce_son_backend_une_seule_fois(monkeypatch, caplog):
    """Une ligne au demarrage, pas une par tick : un capteur qui inonde le journal
    se fait filtrer, et redevient muet."""
    mon = pytest.importorskip("forge_snn_monitor")
    monkeypatch.setattr(mon, "_ETAT_DIT", False)
    monkeypatch.setattr(mon, "_INSTANCE", None)
    monkeypatch.setattr(mon, "SNNMonitor", lambda *a, **k: object())
    with caplog.at_level("WARNING", logger="forge_snn_monitor"):
        mon.get_monitor()
        mon.get_monitor()
        mon.get_monitor()
    dits = [r for r in caplog.records if "[snn] backend=" in r.getMessage()]
    assert len(dits) == 1, "annonce absente ou repetee : %d" % len(dits)


# --------------------- le webhub arme la sentinelle de boucle, comme le hub

def test_le_webhub_enregistre_l_armement_de_la_sentinelle():
    """`forge_loop_sentinel` detecte le gel de la boucle asyncio et dumpe la
    traceback du bloqueur. `start()` n'etait appelee QUE dans nokido_hub.py : le
    hub :8766 etait couvert, et le webhub :7400 — celui qui sert les flux SSE et
    reste en LISTENING muet — ne l'etait pas. Un garde juste, branche sur un seul
    organe.

    On verifie l'ENREGISTREMENT du handler, pas son execution : c'est ce qui se
    perd silencieusement quand quelqu'un remplace les evenements de demarrage par
    un lifespan (Starlette ignore alors on_startup, « use one or the other »)."""
    wr = pytest.importorskip("app.web_hub.wired_routes")
    noms = [getattr(h, "__name__", "") for h in wr.router.on_startup]
    assert "_armer_sentinelle_de_boucle" in noms, (
        "handler de demarrage absent : la sentinelle ne s'armera jamais cote webhub")


def test_le_webhub_n_arme_pas_le_kill_sans_qu_on_le_demande():
    """Le volet KILL de la sentinelle fait `os._exit` sur gel prolonge. Redemarrer
    d'autorite une interface que l'owner regarde est une decision qui se prend :
    elle ne doit pas s'obtenir en effet de bord d'un correctif de diagnostic."""
    import inspect

    wr = pytest.importorskip("app.web_hub.wired_routes")
    src = inspect.getsource(wr._armer_sentinelle_de_boucle)
    assert 'setdefault("LAFORGE_LOOP_KILL_S", "0")' in src, (
        "le kill automatique doit rester desarme par defaut cote webhub")


def test_l_armement_de_la_sentinelle_est_idempotent():
    """Mesure 2026-08-29, premier vrai demarrage : la trace d'armement est apparue
    DEUX fois, meme horodatage et meme pid (pid 20900 -> 2 armements). Le handler
    est enregistre deux fois — module atteint par deux chemins d'import, ou router
    inclus deux fois. Deux `start()` = DEUX monitors sur la meme boucle, donc deux
    dumps par gel et deux fois le cout de surveillance.

    Le drapeau doit vivre dans l'environnement du PROCESS : une globale de module
    ne protege pas d'un module charge sous deux noms. Apres correctif : pid 19556
    -> 1 armement."""
    import inspect

    wr = pytest.importorskip("app.web_hub.wired_routes")
    src = inspect.getsource(wr._armer_sentinelle_de_boucle)
    assert "LAFORGE_WEBHUB_SENTINELLE_PID" in src, "garde d'idempotence absent"
    assert "os.environ.get(_cle) == str(os.getpid())" in src, (
        "le garde doit comparer le PID courant, pas une globale de module")


# ------------------- un bouton accentue est un bouton comme un autre

def test_l_accent_ne_fait_plus_manquer_un_verbe():
    """Mesure 2026-08-29 : « Executer tool_scope » ne contenait pas « exec » a cause
    de l'accent, et tombait en « inconnu » — ni clique, ni compte comme saute par
    surete. Le rapport disait « on ne sait pas » la ou on savait tres bien."""
    camp = pytest.importorskip("forge_ui_campaign")
    assert camp._classify_btn("Exécuter tool_scope") == "destructive"
    assert camp._classify_btn("Générer") == "destructive"
    assert camp._classify_btn("Executer") == "destructive", "sans accent aussi"


def test_les_boutons_qui_ECRIVENT_ne_sont_pas_des_inconnus():
    """`Save` apparaissait QUATORZE fois sur /rbac — il enregistre une politique
    RBAC. Le cout des deux erreurs n'est pas symetrique : sauter a tort coute une
    couverture, cliquer a tort coute un effet."""
    camp = pytest.importorskip("forge_ui_campaign")
    for texte in ("Save", "Enregistrer", "🖥 Shell", "📸 Screenshot",
                  "Régen 20c", "Temp-Mail", "▶ Invoquer"):
        assert camp._classify_btn(texte) == "destructive", texte


def test_l_affichage_pur_reste_cliquable():
    camp = pytest.importorskip("forge_ui_campaign")
    for texte in ("Logs", "Live", "Chercher", "Rafraichir"):
        assert camp._classify_btn(texte) == "safe", texte


def test_le_gate_signale_un_backtick_dans_un_message_de_commit():
    """Sous bash, un backtick dans un `-m` ouvre une SUBSTITUTION : le shell
    execute le mot, il DISPARAIT du message, et le commit passe quand meme. Paye
    QUATRE fois le 2026-08-29, dont deux le meme soir (`argv` et `cible()` avales
    d'un message qui les expliquait). Une lecon qui ne devient pas un garde se
    repaye."""
    gate = pytest.importorskip("hook_capability_gate")
    avec = {"command": 'git commit -m "voir ` + "`argv`" + ` pour le mode local"'}
    assert any("`" in m for m in gate._messages_de_commit(avec)), gate._messages_de_commit(avec)


def test_le_gate_ne_crie_pas_sur_un_message_SAIN():
    """Un garde qui crie a faux se fait desarmer : un message sans backtick, ou une
    commande sans commit, ne doit rien declencher."""
    gate = pytest.importorskip("hook_capability_gate")
    assert gate._messages_de_commit({"command": 'git commit -m "message propre"'}) == [] or all(
        "`" not in m for m in gate._messages_de_commit({"command": 'git commit -m "message propre"'}))
    assert gate._messages_de_commit({"command": "ls -la"}) == []


def test_un_texte_vide_reste_inconnu():
    """Un bouton sans nom ne se devine pas : il ne doit surtout pas passer pour sur."""
    camp = pytest.importorskip("forge_ui_campaign")
    assert camp._classify_btn("") == "unknown"
    assert camp._classify_btn("   ") == "unknown"
