"""NR 6/11 : l'audit des processus, gouverne par Nokido (owner : « active l'audit d'evenements, gouverne par nokido »).

Le superviseur avait ete tue deux fois sans trace nommant le tueur. L'audit dit QUI a lance quoi : il s'active par un ordre
valide au tray puis l'UAC, et l'etat atteint se relit : une commande acceptee n'est pas un etat atteint.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_audit_processus as A  # noqa: E402
from nokido_agent.app import forge_ordres_bureau as O  # noqa: E402


def test_les_sous_categories_sont_nommees_par_guid():
    """Windows francais : « Creation du processus ». Un nom anglais echouerait ici, un GUID tient partout."""
    texte = " ".join(" ".join(c) for c in A.commandes_activation())
    assert A.GUID_CREATION in texte and A.GUID_FIN in texte
    assert "Process Creation" not in texte
    assert "ProcessCreationIncludeCmdLine_Enabled" in texte
    assert "MemberExistsException" in texte, "relancer l'activation ne doit pas echouer sur un compte deja membre"


def test_lecture_auditpol_liste_blanche():
    entete = "Machine Name,Policy Target,Subcategory,Subcategory GUID,Inclusion Setting,Exclusion Setting\n"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Succès,\n") == "OUI"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Success,\n") == "OUI"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Succès et échec,\n") == "OUI"
    # Sortie reelle du 6/11, console cp850 : l'audit etait actif, l'outil le disait NON.
    assert A.audit_actif(entete + "\nDESKTOP,Système,Création,{x},R‚ussite,\n\n") == "OUI"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Réussite,\n") == "OUI"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Valeur inconnue,\n") == "ILLISIBLE", "inconnu n'est pas NON"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Pas d'audit,\n") == "NON"
    assert A.audit_actif(entete + "PC,System,Cr,{x},Aucun audit,\n") == "NON"
    assert A.audit_actif(entete + "PC,System,Cr,{x},No Auditing,\n") == "NON"
    assert A.audit_actif(entete + "\nPC,System,Cr,{x},Succès,\n") == "OUI", "6/11 : relecture ILLISIBLE, ligne vide suspecte"
    assert A.audit_actif("") == "ILLISIBLE", "UNKNOWN != NO"
    assert A.audit_actif("Erreur 0x00000522") == "ILLISIBLE"


def test_etat_atteint_exige_toutes_les_preuves():
    assert A.etat_global({"creation": "OUI", "fin": "OUI", "ligne_de_commande": "OUI"}) == "ACTIF"
    assert A.etat_global({"creation": "OUI", "fin": "NON", "ligne_de_commande": "OUI"}) == "PARTIEL"
    assert A.etat_global({"creation": "ILLISIBLE", "fin": "OUI", "ligne_de_commande": "OUI"}) == "ILLISIBLE"
    assert A.etat_global({"creation": "NON", "fin": "NON", "ligne_de_commande": "NON"}) == "INACTIF"


def test_la_relecture_garde_le_brut_et_cherche_un_vrai_evenement(monkeypatch):
    """Une politique activee ne prouve pas que des evenements sont ecrits. La sortie brute evite de deviner un ILLISIBLE."""
    def faux(cmd, t=30):
        texte = " ".join(cmd)
        sortie = "brut illisible" if "auditpol" in texte else ("    Value    REG_DWORD    0x1" if "reg" in cmd[0] else "2026-11-06T21:40:00")
        return type("R", (), {"stdout": sortie, "returncode": 0, "stderr": ""})()

    monkeypatch.setattr(A, "_lancer", faux)
    etat = A.relire()
    assert etat["preuves"]["creation"] == "ILLISIBLE" and "brut illisible" in etat["brut"]["creation"]
    assert etat["dernier_4688"] == "2026-11-06T21:40:00"


def test_qui_a_tue_trouve_le_lanceur_du_kill():
    evs = [
        {"id": 4688, "ts": "19:46:30", "image": "taskkill.exe", "cmd": "taskkill /F /PID 17608", "parent": "python.exe", "pid_parent": "18184"},
        {"id": 4688, "ts": "19:46:30", "image": "taskkill.exe", "cmd": "taskkill /F /PID 176081", "parent": "python.exe", "pid_parent": "1"},
        {"id": 4689, "ts": "19:46:30", "image": "deno.exe", "pid": "17608", "code": "0x1"},
        {"id": 4688, "ts": "19:40:00", "image": "notepad.exe", "cmd": "notepad 17608", "parent": "explorer.exe", "pid_parent": "2"},
    ]
    r = A.qui_a_tue(evs, "17608")
    assert [t["pid_parent"] for t in r["tueurs"]] == ["18184"], "le pid doit etre un mot entier, dans une commande qui tue"
    assert r["fin"]["code"] == "0x1"


def test_sans_trace_le_tueur_reste_inconnu():
    r = A.qui_a_tue([{"id": 4689, "ts": "1", "image": "deno.exe", "pid": "17608", "code": "0x1"}], "17608")
    assert r["tueurs"] == [] and "INCONNU" in r["verdict"], "un kill par API ne cree pas de processus : ne rien inventer"


def test_l_ordre_est_declare_dans_la_table_et_le_lanceur():
    assert "audit-processus" in O.ACTIONS
    assert "audit-processus" not in O.SANS_CONFIRMATION, "changer une politique systeme demande le Oui de l'owner"
    import nokido_launcher as L
    assert "audit-processus" in L.ACTIONS and "audit-processus" in L.ACTIONS_BUREAU_SEULEMENT
