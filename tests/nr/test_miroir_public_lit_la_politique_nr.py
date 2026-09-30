"""NR — le miroir public doit CONSOMMER la politique, et son audit ne doit jamais
certifier ce qu'il n'a pas regardé.

Trois défauts mesurés le 2026-09-15 sur l'artefact réel (tree `e8c86a6d3889`) :

  1. `tools/forge_public_mirror` ne lisait PAS `.git-publish-rules.json` : il portait
     sa propre liste de 7 chemins. Résultat : **72 puis 94 chemins interdits par la
     politique sortaient quand même** — dont l'inventaire des candidats IP.
  2. L'audit de secrets écartait les blobs > 4 Mo **avant** comptage : ils
     n'apparaissaient ni dans `blobs`, ni dans `non_inspectes`. Il rendait « vert »
     en ayant omis 4 blobs. Un vert obtenu sans avoir regardé n'est pas un vert.
  3. `scrub: true` ne masquait rien : le contrôle de fuite vit dans le gate egress
     et n'y rend qu'un AVERTISSEMENT non bloquant, tandis que le masqueur
     (`forge_sovereign_membrane`) n'est importé par aucun chemin d'export.

Ce NR verrouille les trois, plus la séparation des deux familles d'exclusion.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

# import DUR, jamais importorskip : un skip rendrait la CI verte sans rien prouver.
import forge_public_mirror as M  # noqa: E402


def test_le_miroir_lit_la_politique_et_elle_est_armee():
    profil, eg, err = M._politique_publique()
    assert err is None, f"politique illisible : {err}"
    assert profil.get("blocked_paths"), (
        "le profil public ne porte aucun chemin bloqué : le miroir ne filtrerait rien"
    )
    assert callable(getattr(eg, "_path_blocked", None)), (
        "le miroir doit juger avec le MÊME `_path_blocked` que le gate egress, "
        "jamais avec un filtre parallèle"
    )


def test_construire_est_fail_closed_si_la_politique_est_illisible(monkeypatch):
    # Produire un snapshot sans avoir pu lire la politique serait le repli
    # silencieux que toute la chaîne de preuve interdit.
    monkeypatch.setattr(M, "_politique_publique",
                        lambda: (None, None, "manifeste illisible (test)"))
    r = M.construire(source="HEAD", apply=False)
    assert r.get("ok") is False, "un snapshot a été produit sans politique lisible"
    assert "politique" in (r.get("raison") or "").lower()
    assert "tree" not in r, "aucun arbre ne doit être écrit quand la politique manque"


def test_la_politique_s_applique_a_l_arbre_complet_avant_l_editorial(monkeypatch):
    # Première écriture de ce NR : j'avais exigé que les deux listes soient
    # DISJOINTES. Le test est sorti rouge sur `sandbox/secrets/**` et
    # `RAG_plain_bak/**` — et l'assertion visait à côté : un recouvrement est de
    # la défense en profondeur, pas un défaut.
    #
    # Le vrai défaut était l'ORDRE. L'éditorial passait en premier, donc la
    # politique ne voyait que le RELIQUAT : un chemin éditorial trop large aurait
    # masqué son travail sans que personne ne le voie, et son compte aurait été
    # faux. La sécurité s'applique donc à l'arbre COMPLET, l'éditorial ensuite.
    sequence = []

    def faux_git(*args, **kwargs):
        sequence.append(tuple(args))
        if args and args[0] == "ls-files":
            return 0, "sandbox/secrets/jeton.json\napp/forge_videur.py", ""
        if args and args[0] == "write-tree":
            return 0, "c0ffee" * 6 + "abcd", ""
        return 0, "", ""

    monkeypatch.setattr(M, "_git", faux_git)
    _profil_reel, eg, err = M._politique_publique()
    assert err is None
    profil = {"blocked_paths": ["sandbox/secrets/**"], "scrub": True}

    _tree, _optionnelles, bloques, _env = M._index_temporaire("HEAD", profil, eg)

    i_politique = next((i for i, a in enumerate(sequence) if a and a[0] == "ls-files"), None)
    i_editorial = next((i for i, a in enumerate(sequence)
                        if a and a[0] == "rm" and "-r" in a), None)
    assert i_politique is not None, "la politique n'a jamais énuméré l'arbre"
    assert i_editorial is not None, "les exclusions éditoriales n'ont pas été appliquées"
    assert i_politique < i_editorial, (
        "l'éditorial s'applique AVANT la politique : celle-ci ne juge plus que le "
        "reliquat, et son compte de fichiers retirés est faux"
    )
    assert bloques["fichiers"] == 1, (
        f"la politique devait retirer 1 fichier de l'arbre complet, elle en a compté "
        f"{bloques['fichiers']}"
    )
    assert "arbre complet" in bloques.get("applique_sur", "")


def test_toute_exclusion_optionnelle_porte_un_motif():
    # La structure est un dict pour rendre l'omission IMPOSSIBLE, pas seulement
    # déconseillée. Ce test verrouille la propriété même si quelqu'un revient
    # un jour à une liste.
    sans_motif = [c for c in M.OPTIONAL_EXPORT_EXCLUSIONS
                  if not (M.EXCLUSIONS_MOTIFS.get(c) or "").strip()]
    assert not sans_motif, (
        f"exclusion(s) éditoriale(s) sans motif déclaré : {sans_motif}. Une "
        "exclusion non motivée est indistinguable d'une erreur."
    )


def test_aucune_exclusion_n_attrape_le_coeur_publiable():
    # Garde anti « export propre et VIDE » : `exclude('*.py')` produirait un
    # snapshot qui passe tous les contrôles et ne contient plus le produit.
    # Les exclusions sont appliquées par `git rm -r -- <chemin>`, donc le test
    # raisonne par préfixe de chemin, comme git.
    SENTINELLES = [
        "app/forge_videur.py",                       # régulation / autorité
        "app/forge_resource_manager.py",
        "tools/ci_local.py",                         # preuve
        "tools/forge_worktree.py",
        "tests/nr/test_egress_profil_public_atteignable_nr.py",
        "docs/skills/nokido/SKILL.md",               # savoir-faire produit
        "docs/internal/cartographie_autopoietique_organes_computationnels.md",
        "design_handoff_nokido/SKILL.md",            # design system
        "seed/manifest.json",                        # amorçage d'un clone
        "seed/system_rules.jsonl",
        "README.md",
        "docs/launch/media/demo_feed_real.webm",     # la démonstration qui RESTE
    ]
    captures = []
    for excl in M.OPTIONAL_EXPORT_EXCLUSIONS:
        e = str(excl).rstrip("/")
        for s in SENTINELLES:
            if s == e or s.startswith(e + "/"):
                captures.append((excl, s))
    assert not captures, (
        f"une exclusion éditoriale attrape le cœur publiable : {captures}. "
        "Un export « propre » mais vide est un échec déguisé en succès."
    )


def test_les_quatre_gif_hors_borne_sont_exclus_et_leur_equivalent_reste():
    # Décision owner 2026-09-15 : on n'élève PAS le plafond de 5 Mo pour sauver un
    # format alors qu'un équivalent publiable existe. Substitution, pas perte.
    for gif in ("demo_feed_real", "demo_graph_real", "demo_recon_real", "demo_netcfg_real"):
        chemin = f"docs/launch/media/{gif}.gif"
        assert chemin in M.OPTIONAL_EXPORT_EXCLUSIONS, f"{chemin} n'est plus exclu"
        assert "webm" in M.EXCLUSIONS_MOTIFS[chemin], (
            f"le motif de {chemin} doit nommer la représentation de remplacement"
        )
    # et le remplaçant ne doit surtout pas être exclu lui aussi
    for excl in M.OPTIONAL_EXPORT_EXCLUSIONS:
        assert not str(excl).endswith(".webm"), (
            f"{excl} : exclure le remplaçant reviendrait à perdre la démonstration"
        )


def test_la_classification_distingue_fuite_reelle_et_ressemblance():
    # Mesure du 2026-09-15 : 827 fichiers signalés, dont 748 ne portaient que du
    # loopback — la doc d'un système local-first en est faite. Et `babel.min.js`
    # exposait 112 « IP » qui sont des numéros de VERSION, tandis que
    # `threading.local` (Python standard) passait pour un hôte interne.
    C = M
    cas = [
        # (valeur, chemin, classe attendue, pourquoi)
        ("127.0.0.1", "README.md", C.BENIGN_LOCALHOST, "local-first documenté"),
        ("127.0.0.53", "docs/x.md", C.BENIGN_LOCALHOST, "loopback"),
        ("threading.local", "app/forge_bge_m3_shared.py", C.BENIGN_LITERAL, "Python standard"),
        ("settings.local", "tools/x.py", C.BENIGN_LITERAL, "nom de fichier"),
        ("host.docker.internal", "docker/compose.yml", C.BENIGN_LITERAL, "hôte standard"),
        ("localhost", "app/web_hub/static/babel.min.js", C.BENIGN_LITERAL, "version, bundle tiers"),
        ("localhost", "tools/nokido_netmap.py", C.INDETERMINE, "hors bundle : NE PAS conclure"),
        ("localhost", "docs/guide.md", C.INDETERMINE, "IP LAN : à instruire"),
        ("%USERPROFILE%\\miniforge3", "tools/x.py", C.SENSITIVE_CONFIRMED, "chemin réel"),
        ("/home/user/bin", "deploy/x.sh", C.SENSITIVE_CONFIRMED, "chemin réel"),
        ("C:\\Users\\Default\\Python", "tools/x.py", C.BENIGN_LITERAL, "placeholder"),
        ("C:\\Users\\<owner>\\x", "docs/x.md", C.BENIGN_LITERAL, "placeholder"),
        ("machine-inconnue.corp", "docs/x.md", C.INDETERMINE, "hôte non listé"),
    ]
    faux = []
    for valeur, chemin, attendu, pourquoi in cas:
        obtenu = C.classer_fuite(valeur, chemin)
        if obtenu != attendu:
            faux.append(f"{valeur!r} dans {chemin} -> {obtenu} (attendu {attendu} : {pourquoi})")
    assert not faux, "classification erronée :\n  " + "\n  ".join(faux)


def test_l_inconnu_ne_devient_jamais_sain():
    # La propriété qui compte. Un détecteur qui bascule l'inconnu vers « sain »
    # fabrique un vert sans mesure — c'est le défaut que toute cette chaîne
    # traque depuis le début.
    exotiques = ["2001:db8::1", "truc.machin.invalid", "localhost",
                 "\\\\serveur\\partage", "user@hote-interne", ""]
    for v in exotiques:
        c = M.classer_fuite(v, "app/module.py")
        assert c in (M.INDETERMINE, M.SENSITIVE_CONFIRMED), (
            f"{v!r} classé {c} : une valeur non reconnue doit rester UNKNOWN, "
            "jamais être déclarée bénigne"
        )


def test_la_porte_de_scrub_traite_des_octets_et_refuse_une_fuite(monkeypatch):
    # Défaut trouvé à la PREMIÈRE exécution réelle de cette porte, le 2026-09-15 :
    # `TypeError: cannot use a string pattern on a bytes-like object`. `lire_blobs`
    # rend des octets (les motifs de secrets sont compilés sur bytes) tandis que
    # `_LEAK_RX` est compilé sur du texte. Le code n'avait jamais tourné — l'audit
    # s'arrêtait toujours avant, sur les blobs hors borne.
    import importlib

    aud = importlib.import_module("nokido_agent.tools.forge_history_secret_audit")

    def faux_lire_blobs(shas):
        for s in shas:
            # OCTETS, comme la vraie fonction. Fuite : chemin owner + IP privée.
            yield s, b"chemin %USERPROFILE%\\x et hote localhost\n", 44

    monkeypatch.setattr(aud, "lire_blobs", faux_lire_blobs)
    monkeypatch.setattr(aud, "MOTIFS", {})        # on isole la FUITE, pas le secret
    monkeypatch.setattr(aud, "EXCEPTIONS", set())

    def faux_git(*args, **kwargs):
        if args and args[0] == "ls-tree":
            return 0, "100644 blob " + "b" * 40 + "\t44\tapp/module.py", ""
        return 0, "", ""

    monkeypatch.setattr(M, "_git", faux_git)
    _profil_reel, eg, err = M._politique_publique()
    assert err is None

    r = M._audit_du_tree("deadbeef",
                         {"scrub": True, "max_file_bytes": 0, "blocked_paths": []}, eg)

    assert r["etat"] == "rouge", (
        "scrub demandé et fuite CONFIRMÉE présente : l'audit doit REFUSER, pas "
        f"avertir. état obtenu : {r['etat']}"
    )
    assert r.get("sensibles_confirmes"), "la fuite confirmée n'est pas rapportée"
    assert r["sensibles_confirmes"][0]["fichier"] == "app/module.py"
    assert "montre" in r.get("sensibles_note", ""), (
        "une borne d'affichage doit dire COMBIEN, pas seulement montrer un extrait"
    )
    # Le chemin owner est CONFIRMÉ ; l'IP privée du même blob reste INDÉTERMINÉE.
    # Les deux coexistent, et c'est le confirmé qui décide de l'état.
    assert r["detections"][M.SENSITIVE_CONFIRMED] == 1
    assert r["detections"][M.INDETERMINE] == 1, (
        "l'IP privée hors bundle doit rester UNKNOWN, ni bénigne ni confirmée"
    )


def test_un_blob_hors_borne_empeche_le_vert(monkeypatch):
    # Le défaut n°2, reproduit : un arbre dont le seul blob dépasse la borne
    # d'audit. Avant correction il sortait « vert, 0 blob ». Il doit maintenant
    # être NOMMÉ et refuser la certification.
    gros = 11_830_000

    def faux_git(*args, **kwargs):
        if args and args[0] == "ls-tree":
            return 0, f"100644 blob {'a' * 40}\t{gros}\tdocs/launch/media/demo.gif", ""
        return 0, "", ""

    monkeypatch.setattr(M, "_git", faux_git)
    profil = {"scrub": True, "max_file_bytes": 5_000_000, "blocked_paths": []}
    r = M._audit_du_tree("deadbeef", profil, None)

    assert r["etat"] != "vert", (
        "l'audit certifie un arbre dont un blob n'a jamais été inspecté"
    )
    assert r.get("hors_borne"), "le blob hors borne n'est pas signalé"
    assert r["hors_borne"][0]["fichier"].endswith("demo.gif")
    assert r["hors_borne"][0]["etat"] == "OVER_LIMIT"
    # le cap du PROFIL est une seconde dimension, distincte de la borne d'audit
    assert r.get("depassent_le_cap"), "le dépassement du cap public n'est pas signalé"
    # une borne doit dire COMBIEN, pas seulement TROP
    assert "couverture" in r and "/" in r["couverture"]
