"""Un silence VOULU n'est pas une panne, et « pas vu » n'est pas « rien a voir ».

Gardes d'effet pour l'audit de liveness de `forge_health_diagnostic`, tel que
refondu le 2026-09-04. Trois mesures ont motive ce travail :

1. **48 heartbeats sur le disque, 8 audites.** Quarante organes battaient hors de
   tout regard, et le score de sante — annonce comme global — portait sur 17 % de
   la flotte. Le commentaire de la liste en dur enoncait pourtant le defaut :
   « un organe absent du capteur ne peut pas mourir bruyamment : sa mort n'est pas
   silencieuse par hasard, elle l'est par construction ». Il avait ete soigne DEUX
   fois en ajoutant une entree a la main.
2. **40 des 43 decouverts sont declares dans `services.toml`.** Ce ne sont donc pas
   des residus d'anciens services — le piege que `forge_sensor_fusion_probe`
   documente (24-07 : un heartbeat orphelin de 20,6 jours attribue a un service qui
   n'en declare aucun). La provenance se DEMANDE au registre, elle ne se devine pas
   par convention de nom.
3. **La moitie des organes silencieux se taisent volontairement.** Sur 8 stale,
   4 portent `disabled = true` — dont les embedders, eteints par la directive owner
   du 01/09 qui route l'embedding vers Modal. Les rapporter comme morts fabriquerait
   quatre pannes et noierait les vraies.

Ce que ces tests figent n'est pas un chiffre (il bouge avec le corps) mais les
INVARIANTS de lecture : trois etats jamais deux, et jamais de verdict sur une
provenance inconnue.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _audit():
    import forge_health_diagnostic as fhd  # noqa: PLC0415

    return fhd.audit_workers_heartbeat()


def _exiger_un_disque_peuple():
    """Skip quand il n'y a RIEN a enumerer — « pas vu » n'est pas « rien a voir ».

    Mesure 2026-09-04 : ces tests mesurent une CAPACITE D'ENUMERATION, donc il
    leur faut un disque peuple. Sur un clone frais — le runner CI — `sandbox/`
    est gitignore et ne porte AUCUN `*.heartbeat` : l'audit retombe legitimement
    sur la liste en dur, et l'assertion accusait « l'enumeration a casse » alors
    qu'elle n'avait rien a lire. Resultat : vert en local, ROUGE sur cinq runs
    GitHub d'affilee.

    On interroge donc la CAUSE (le disque porte-t-il des heartbeats ?) et non le
    symptome (peu de resultats). Le defaut etait d'autant plus penible que tout
    ce fichier est ecrit pour tenir cette distinction-la.
    """
    import pytest  # noqa: PLC0415

    import forge_health_diagnostic as fhd  # noqa: PLC0415

    try:
        presents = list(fhd.SANDBOX.glob("*.heartbeat"))
    except OSError as exc:
        pytest.skip("%s illisible (%s) : ni « vide » ni « peuple » — on ne conclut pas"
                    % (fhd.SANDBOX, type(exc).__name__))
    if not presents:
        pytest.skip("aucun *.heartbeat dans %s (clone frais ?) : l'enumeration n'a "
                    "rien a enumerer, ce n'est pas une panne du capteur" % fhd.SANDBOX)
    # PEUPLE, pas juste NON VIDE (mesure 2026-09-30). Le renommage du depot a cree un
    # dossier runner NEUF `_work/nokido-private/sandbox` ou 10 heartbeats TRANSITOIRES
    # (ecrits par un autre job), aucun adosse a services.toml, etaient presents. L'audit
    # ne DEPASSAIT alors pas la liste en dur (test 1) et aucune decision n'etait resoluble
    # (test 2) : deux ROUGES sur un disque simplement PARTIEL, pas sur une panne du capteur.
    # Le garde exige donc ce que les tests mesurent vraiment : assez de heartbeats HORS liste
    # en dur pour que l'enumeration la depasse, ET au moins un heartbeat DECLARE (sinon
    # `eteint_par_decision` est None partout). En deca -> skip, jamais un faux echec.
    en_dur = set(fhd._WORKER_HEARTBEATS.values())
    seuil = 2 * len(en_dur)
    decouverts = [p for p in presents if p.name not in en_dur]
    if len(decouverts) <= seuil:
        pytest.skip("sandbox PARTIEL : %d heartbeat(s) hors liste en dur (seuil %d) — dossier "
                    "runner frais / etat transitoire, l'enumeration ne peut pas depasser la "
                    "liste en dur ; ce n'est pas une panne du capteur" % (len(decouverts), seuil))
    try:
        declares = {Path(v).name for v in fhd._hb_declares_par_services_toml().values()}
    except Exception:  # noqa: BLE001 - registre illisible : on ne pretend pas a une provenance
        declares = set()
    if not any(p.name in declares for p in presents):
        pytest.skip("aucun heartbeat present n'est adosse a services.toml : aucune decision "
                    "resoluble (etat transitoire) — ce n'est pas une panne du registre")
    return presents


def test_l_audit_depasse_largement_la_liste_en_dur():
    """La zone d'ombre reste fermee : on audite le disque, pas 8 entrees choisies."""
    import forge_health_diagnostic as fhd  # noqa: PLC0415

    _exiger_un_disque_peuple()
    w = _audit()
    assert len(w) > 2 * len(fhd._WORKER_HEARTBEATS), (
        "l'audit ne couvre que %d workers pour %d declares en dur — l'enumeration du "
        "disque a du casser, et la mort des organes non listes redevient silencieuse "
        "par construction" % (len(w), len(fhd._WORKER_HEARTBEATS)))


def test_chaque_worker_porte_les_trois_qualificateurs():
    """`declare`, `adosse_registre`, `eteint_par_decision` : sans eux, un lecteur ne
    peut pas distinguer un organe mort d'un organe eteint ni d'un residu."""
    for nom, h in _audit().items():
        assert "declare" in h, "%s sans champ `declare`" % nom
        if h.get("present"):
            assert "adosse_registre" in h, "%s sans provenance" % nom
            assert "eteint_par_decision" in h, "%s sans etat de decision" % nom


def test_les_trois_qualificateurs_admettent_l_inconnu():
    """TROIS etats, jamais deux. `None` doit rester possible : un registre illisible
    ne doit pas se lire « ce service est actif », sinon une extinction voulue devient
    une panne — et c'est precisement ce qui est arrive le 2026-09-04, quand un `re`
    non importe, avale par un `except`, rendait la table vide."""
    for nom, h in _audit().items():
        for champ in ("adosse_registre", "eteint_par_decision"):
            v = h.get(champ)
            assert v is None or isinstance(v, bool), (
                "%s.%s = %r : ce champ doit valoir True, False ou None (inconnu)"
                % (nom, champ, v))


def test_le_registre_des_services_est_lisible_et_non_vide():
    """Si cette table est vide, TOUT devient `None` et la distinction disparait.

    C'est le mode de panne exact du 2026-09-04 : `eteint_par_decision` valait None
    pour les 50 workers, dans la fonction ecrite pour etablir la distinction. Le
    defaut etait un import manquant masque par un `except`.
    """
    import forge_health_diagnostic as fhd  # noqa: PLC0415

    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    if not toml.exists():
        import pytest  # noqa: PLC0415

        pytest.skip("services.toml absent de cet arbre")
    # `services.toml` est versionne, donc TOUJOURS present sur un clone frais —
    # mais les heartbeats qu'on lui confronte, non. Sans ce garde, l'assertion
    # « aucun worker n'a d'etat de decision connu » accuse un import manquant
    # la ou il n'y a simplement aucun worker a qualifier.
    _exiger_un_disque_peuple()
    connus = [n for n, h in _audit().items()
              if h.get("eteint_par_decision") is not None]
    assert connus, (
        "AUCUN worker n'a d'etat de decision connu alors que services.toml existe : "
        "le registre n'a pas ete lu (import manquant ? exception avalee ?), et toute "
        "extinction voulue sera desormais rapportee comme une panne")
    assert fhd._service_desactive("il_n_existe_pas.heartbeat") is None, (
        "un heartbeat inconnu du registre doit rendre None, jamais False : False "
        "affirmerait « ce service est actif » sans l'avoir verifie")


def test_un_organe_eteint_par_decision_n_est_pas_compte_comme_mort():
    """Le garde central : `disabled = true` explique un silence, il ne l'accuse pas."""
    w = _audit()
    tus = [n for n, h in w.items()
           if h.get("alive") is False and h.get("eteint_par_decision") is True]
    for nom in tus:
        assert w[nom].get("eteint_par_decision") is True
    # Et l'inverse : un organe frais ne doit jamais etre range parmi les silences.
    for nom, h in w.items():
        if h.get("alive") is True:
            assert not (h.get("eteint_par_decision") is True and h.get("alive") is False)


def _sandbox_avec(tmp_path, monkeypatch, noms):
    import forge_health_diagnostic as fhd  # noqa: PLC0415

    monkeypatch.setattr(fhd, "SANDBOX", tmp_path)
    for nom in noms:
        (tmp_path / nom).write_text('{"ts": 1790000000.0}', encoding="utf-8")
    return fhd


def test_le_garde_SKIP_sur_un_dossier_runner_partiel(tmp_path, monkeypatch):
    """Le cas ROUGE du 2026-09-30 : quelques heartbeats transitoires, hors registre."""
    import pytest  # noqa: PLC0415

    _sandbox_avec(tmp_path, monkeypatch,
                  ["transitoire_1.heartbeat", "transitoire_2.heartbeat", "transitoire_3.heartbeat"])
    with pytest.raises(pytest.skip.Exception):
        _exiger_un_disque_peuple()


def test_le_garde_PASSE_sur_un_disque_reellement_peuple(tmp_path, monkeypatch):
    import forge_health_diagnostic as fhd  # noqa: PLC0415

    en_dur = set(fhd._WORKER_HEARTBEATS.values())
    faux = ["organe_%d.heartbeat" % i for i in range(3 * len(en_dur))]
    fhd_mod = _sandbox_avec(tmp_path, monkeypatch, faux + ["declare.heartbeat"])
    # un heartbeat DECLARE par services.toml, sans dependre de sa lisibilite reelle
    monkeypatch.setattr(fhd_mod, "_hb_declares_par_services_toml",
                        lambda: {"svc": tmp_path / "declare.heartbeat"})
    presents = _exiger_un_disque_peuple()
    assert len(presents) >= 3 * len(en_dur)


def test_le_garde_SKIP_si_aucun_heartbeat_n_est_declare(tmp_path, monkeypatch):
    import pytest  # noqa: PLC0415

    import forge_health_diagnostic as fhd  # noqa: PLC0415

    en_dur = set(fhd._WORKER_HEARTBEATS.values())
    faux = ["inconnu_%d.heartbeat" % i for i in range(3 * len(en_dur))]
    _sandbox_avec(tmp_path, monkeypatch, faux)
    monkeypatch.setattr(fhd, "_hb_declares_par_services_toml", lambda: {})
    with pytest.raises(pytest.skip.Exception):
        _exiger_un_disque_peuple()
