"""NR — le script d'arret de la stack n'abat pas les ponts stdio des clients.

Mesure 2026-09-06 11:47:23 : `nokido_stop.ps1` (reaping des « orphelins Python
Nokido », filtre `-like '*nokido*'`) a tue le pont `mcp_stdio_bridge.py` lance par
Claude Desktop pendant le restart de la stack ; Desktop a affiche « Server
disconnected » et seul un redemarrage de Desktop relance son pont. Le pont est un
enfant du CLIENT, pas un membre de la flotte : il survit a un restart du hub
(reconnexion HTTP par appel) mais pas a un kill.

Le test lit le SCRIPT REEL (pas une copie) et verifie que le filtre des orphelins
exclut explicitement le pont, comme il exclut deja `nokido_tray` (regression du
meme type, corrigee plus tot).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOP = ROOT / "tools" / "nokido_stop.ps1"


def _bloc_orphelins() -> str:
    src = STOP.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\$orphans\s*=\s*Get-CimInstance.*?\n\}", src, re.S)
    assert m, "bloc $orphans introuvable dans nokido_stop.ps1"
    return m.group(0)


def test_le_filtre_des_orphelins_exclut_le_pont_stdio():
    bloc = _bloc_orphelins()
    assert "-notlike '*mcp_stdio_bridge*'" in bloc, bloc


def test_le_filtre_des_orphelins_exclut_toujours_le_tray():
    bloc = _bloc_orphelins()
    assert "-notlike '*nokido_tray*'" in bloc, bloc


def test_le_filtre_des_orphelins_exclut_le_panneau_qui_orchestre_le_restart():
    """2026-09-26 : le panneau (`nokido_launcher.py`) lance ce stop, attend
    `sandbox/nokido_stop.done`, PUIS lance le start. Sa cmdline contient 'Nokido' :
    sans exclusion, le stop l'abattait avant le start et la stack restait a terre."""
    bloc = _bloc_orphelins()
    assert "-notlike '*nokido_launcher*'" in bloc, bloc


# ---------------------------------------------------------------------------
# AJOUT 2026-09-11 -- CONTRAT D'ARRET : un PID numerique n'est pas une identite.
#
# Mesure du jour, chaine de vie du portail web :
#     :7400 LISTENING (pid 18644) et /health en TIMEOUT depuis plus de 5 h.
# En cartographiant le lifecycle, deux autorites contradictoires apparaissent :
#     START : supervisor.ts spawn ses enfants et les connait ;
#     STOP  : nokido_stop.ps1 tue par MOTIF DE NOM, hors du superviseur.
# Le script ne contient AUCUN `start_time`, `CreationDate` ni appel a
# `forge_process_identity` : il tue ce qui RESSEMBLE a Nokido.
#
# Or la primitive existe DEJA -- decision owner du 2026-08-21, << plus jamais
# `ps | grep python` >>, avec `test_pid_reutilise_demasque_par_start_time` au
# vert. Le defaut n'est donc pas une capacite absente mais une DETTE DE
# CABLAGE, et un mecanisme present mais non cable n'a jamais ete une securite.
# ---------------------------------------------------------------------------

def _src() -> str:
    return STOP.read_text(encoding="utf-8", errors="replace")


def _code() -> str:
    """Le script SANS ses commentaires PowerShell (`<# .. #>` et `# ..`).

    Sans ce depouillage, le NR se fait piloter par la prose : le 2026-09-11, le
    commentaire qui DOCUMENTE l'ancienne forme (<< l'ancienne version faisait
    Get-Process deno >>) a suffi a faire crier le garde sur un script pourtant
    corrige. Un instrument ne doit jamais lire le vocabulaire qu'il traque --
    piege paye cinq fois en trois jours, dans les deux sens : un commentaire
    qui RASSURE a tort, et ici un commentaire qui ACCUSE a tort.
    """
    src = re.sub(r"<#.*?#>", " ", _src(), flags=re.S)
    return re.sub(r"(?m)#.*$", " ", src)


def test_le_depouillage_des_commentaires_powershell_mord():
    """Une sonde non prouvee ne mesure rien : on la verifie des deux cotes."""
    brut = "Get-Process deno   # Get-Process node\n<# Get-Process pwsh #>\n$x = 1"
    net = re.sub(r"(?m)#.*$", " ", re.sub(r"<#.*?#>", " ", brut, flags=re.S))
    assert "Get-Process deno" in net          # le CODE survit
    assert "Get-Process node" not in net      # le commentaire de fin de ligne saute
    assert "Get-Process pwsh" not in net      # le bloc saute
    assert "$x = 1" in net
    assert len(_code()) < len(_src()), "le depouillage n'a rien retire du script reel"


def test_la_primitive_d_identite_de_process_existe_deja():
    """Garde-fou de cadrage : le remede est du CABLAGE, pas une creation.

    Si ce test devenait rouge, les suivants changeraient de sens -- ils
    demanderaient d'ecrire une primitive au lieu d'en brancher une eprouvee.
    """
    prim = ROOT / "app" / "forge_process_identity.py"
    assert prim.exists(), (
        "app/forge_process_identity.py a disparu : avant de reclamer une "
        "verification d'identite au script d'arret, il faut savoir si la "
        "primitive existe encore")
    src = prim.read_text(encoding="utf-8", errors="replace")
    assert "start_time" in src, (
        "la primitive n'expose plus de start_time : sans lui, un PID reutilise "
        "est indiscernable du process attendu")


def test_le_stop_verifie_l_identite_avant_de_tuer():
    """PID existe n'est PAS PID = notre process.

    Meme famille que le bail de lane orphelin et que `job_status` qui garde
    `running` apres un kill externe : le PID numerique seul est une identite
    qui se recycle, et Windows les recycle vite.
    """
    src = _src()
    tue = "Stop-Process" in src
    assert tue, "le script ne tue plus rien : contrat a re-instruire"
    preuves = ("forge_process_identity", "start_time", "StartTime",
               "CreationDate", "creation_time")
    assert any(p in src for p in preuves), (
        "nokido_stop.ps1 appelle `Stop-Process -Force` sans jamais comparer "
        "l'identite du process (aucun de %s).\n"
        "  -> un PID recycle par Windows sera tue a la place de la cible, et "
        "ce processus etranger n'a aucune raison d'appartenir a Nokido."
        % (preuves,))


def test_le_stop_ne_tue_pas_une_CLASSE_entiere_de_runtime():
    """<< deno = 100% Nokido sur cette machine >> est une hypothese, pas un fait.

    Le script tue TOUS les processus deno en s'appuyant sur cette phrase. Elle
    est vraie aujourd'hui et le restera jusqu'au jour ou l'owner installera un
    autre projet Deno -- et ce jour-la, rien ne l'avertira. C'est la meme
    imprudence que le filtre `-like '*nokido*'` qui a abattu le pont stdio d'un
    CLIENT le 2026-09-06 : viser large, esperer juste.
    """
    src = _code()
    # ATTENTION, faux vert paye le 2026-09-11 : la premiere version de cette
    # sonde exigeait `-Name`, alors que le script ecrit `Get-Process deno
    # -ErrorAction SilentlyContinue` (parametre POSITIONNEL). Elle ne matchait
    # rien, tombait dans le `return` et rendait VERT sur un script inchange --
    # un garde branche sur un signal que personne n'emet.
    # ... et RE-REGLEE le meme jour : la sonde traquait une SYNTAXE
    # (`Get-Process deno`) au lieu de la PROPRIETE. Le script est passe a
    # `Get-CimInstance -Filter "Name='deno.exe'"` et elle s'est mise a crier
    # << introuvable >>. Ce qu'on veut mesurer n'est pas comment on enumere,
    # c'est si l'enumeration est assortie d'une preuve d'APPARTENANCE.
    lignes = [l for l in src.splitlines()
              if re.search(r"deno", l, re.I)
              and re.search(r"Get-Process|Get-CimInstance", l, re.I)]
    assert lignes, (
        "aucune enumeration de process deno trouvee. Si le script a encore "
        "change de forme, RE-REGLER cette sonde : ne jamais la laisser rendre "
        "vert par simple absence de correspondance")
    m = re.search(re.escape(lignes[0]), src)
    zone = src[max(0, m.start() - 900):m.start() + 1400]
    preuves = ("forge_process_identity", "CreationDate", "ParentProcessId",
               "Descendants", "supervisor.ts", "Stop-NokidoPid")
    assert any(p in zone for p in preuves), (
        "les processus `deno` sont enumeres sans aucune preuve d'appartenance "
        "a la flotte (ni parent, ni identite, ni scope superviseur).\n"
        "  -> le STOP doit viser un OWNER et ses enfants POSSEDES, jamais un "
        "runtime entier : << deno = 100%% Nokido sur cette machine >> est une "
        "hypothese d'environnement, muette le jour ou elle devient fausse.")


def test_la_sonde_du_balayage_deno_mord_sur_les_deux_ecritures():
    """Une sonde non prouvee rend vert sans rien mesurer -- verifie le 2026-09-11."""
    motif = re.compile(r"(?m)^.*Get-Process\s+(?:-Name\s+)?[\"']?deno\b.*$")
    assert motif.search("Get-Process deno -ErrorAction SilentlyContinue | %{")
    assert motif.search('Get-Process -Name "deno" | Stop-Process')
    assert not motif.search("Get-Process denormalise")   # \\b tient le mot entier
    assert not motif.search("Get-Process python")


def test_un_stop_sur_une_cible_deja_morte_est_un_succes_explicite():
    """STOP idempotent : deja arrete est un SUCCES, jamais une erreur avalee.

    Le script sait deja le faire pour nssm (`NoProcessFound` -> << deja
    arrete >>). La propriete doit valoir pour TOUTES les cibles, sinon un
    second STOP se termine en bruit d'erreur et on ne distingue plus << rien a
    faire >> de << echec du kill >>.
    """
    src = _src()
    kills = len(re.findall(r"Stop-Process", src))
    assert kills > 0
    idempotents = len(re.findall(r"NoProcessFound|deja arrete|already stopped",
                                 src, re.I))
    assert idempotents >= kills, (
        "%d appels a Stop-Process pour seulement %d traitements explicites du "
        "cas << deja arrete >> : les autres confondent l'absence de cible avec "
        "un echec" % (kills, idempotents))


def test_le_filtre_reste_scope_nokido_et_non_machine_wide():
    # Le reaping doit rester borne a la cmdline Nokido : pas de `Get-Process python`
    # nu (regression historique : kill machine-wide de tout python).
    src = STOP.read_text(encoding="utf-8", errors="replace")
    lignes_code = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
    assert not any(re.search(r"Get-Process\s+python\b", l) for l in lignes_code)
