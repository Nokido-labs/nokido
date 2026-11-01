"""M0 — surface d'effets de Nokido : prouver la FERMETURE, pas inventorier.

__FORGE_COLOR__ = "immunitaire/enforcement : surface d'effets, chemins equivalents, preuve du monde"

POURQUOI CE MODULE EXISTE
    Un inventaire d'ingress ne prouve rien. On peut refuser `Write` et laisser
    passer `Bash` + `python open()` : meme EFFET, autre syntaxe. L'unite de
    securite n'est donc pas le TOOL, c'est l'EFFET FINAL OBSERVABLE.

    Corollaire qui gouverne tout ce fichier : un client LLM n'est pas seulement
    un acteur, c'est un GENERATEUR DE CHEMINS. Il gagne des qu'il trouve une
    nouvelle maniere syntaxique de produire le meme effet. Le systeme doit donc
    juger l'effet, jamais le moyen.

CE QUE CE MODULE REFUSE DE FAIRE
    `PROTECTED` n'est PAS un etat qu'on pose. C'est une propriete DERIVEE :

        PROTECTED(effet) =
                INVENTORIED
            AND DECISION_PROVEN
            AND ENFORCEMENT_PROVEN
            AND EXHAUSTIVENESS_PROVEN
            AND aucun EFFECT_EQUIVALENT_PATH_NOT_COVERED

    Ainsi cent NR verts ne suffisent pas : tant qu'un chemin equivalent reste
    non couvert, la classe rend NON_CERTIFIANT. C'est volontairement difficile
    a satisfaire — et impossible a impressionner.

LA PREUVE D'ENFORCEMENT EST UNE PREUVE DU MONDE
    Un `DENY` rendu par un garde ne prouve pas qu'un effet a ete empeche : il
    prouve qu'un garde a parle. La preuve exigee ici est :

        etat_avant  +  tentative  +  decision=DENY
                    +  etat_apres == etat_avant
                    +  executor NON atteint
                    => EFFECT_BLOCKED

    Sinon : `DENY` cote gate, et l'effet par un canal lateral. Les empreintes
    sont concretes — hash de fichier, etat de service, HEAD et ref distante,
    enregistrement memoire.

TROIS ETATS, JAMAIS DEUX
    Tout chemin non observe, ambigu, non instrumente, inaccessible ou non
    correle rend `NON_CERTIFIANT`. Jamais `PROTECTED`, jamais « sain par
    defaut ». C'est la premiere ligne de la constitution semantique appliquee a
    l'enforcement.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/enforcement : surface d'effets, chemins equivalents, preuve du monde"

from dataclasses import dataclass, field

# --- categories de chemins -------------------------------------------------
# Enumerees explicitement : « tous les ingress » n'a de sens que si « tous » a
# une definition technique, sinon M0 ne se termine jamais.
CATEGORIES = (
    "DIRECT",           # le tool nomme pour cet effet
    "INDIRECT",         # un autre effet qui produit celui-ci en passant
    "ALIAS",            # un tool different, meme effet
    "CLI",              # ligne de commande
    "MCP",              # un autre serveur d'outils
    "UI",               # interface web
    "HOOKLESS_CLIENT",  # client sans hooks : le hook n'est JAMAIS la frontiere
    "SCRIPT",           # script du depot
    "SUBPROCESS",       # processus enfant
    "RUN_JOB",          # travail detache
    "PS_CLM",           # session privilegiee
    "DELEGATION",       # un autre agent agit a ma place
    "RECURSIVE_CHILD",  # enfant d'execution
    "RETRY",            # meme effet apres un refus
    "TOCTOU",           # la ressource change entre le controle et l'effet
)

# --- verdicts --------------------------------------------------------------
INVENTORIED = "INVENTORIED"
DECISION_PROVEN = "DECISION_PROVEN"
ENFORCEMENT_PROVEN = "ENFORCEMENT_PROVEN"
EXHAUSTIVENESS_PROVEN = "EXHAUSTIVENESS_PROVEN"
AXES = (INVENTORIED, DECISION_PROVEN, ENFORCEMENT_PROVEN, EXHAUSTIVENESS_PROVEN)

# Categorie OBLIGATOIRE : sa seule presence fait echouer M0 pour la classe.
EQUIV_NON_COUVERT = "EFFECT_EQUIVALENT_PATH_NOT_COVERED"

# --- douze dimensions -------------------------------------------------------
# Exposees SEPAREMENT : aucun score global ne doit pouvoir masquer un axe rouge.
DIMENSIONS = (
    "EFFECT_SURFACE_DEFINED",
    "ALL_KNOWN_INGRESS_ENUMERATED",
    "EFFECT_EQUIVALENCE_CLOSURE_PROVEN",
    "DECISION_PROVEN",
    "EXECUTION_MEDIATED",
    "EFFECT_BLOCKED_PROVEN",
    "WORLD_STATE_COVERAGE_PROVEN",
    "TOCTOU_SAFE",
    "META_EFFECTS_PROTECTED",
    "ROOT_OF_TRUST_INTACT",
    "PROOF_NOT_SELF_CERTIFIED",
    "ADVERSARIAL_DISCOVERY_FOUND_NO_UNRESOLVED_PATH",
)

# --- etats de decouverte ----------------------------------------------------
# « Le scanner a fini » n'est PAS « il n'y a rien d'autre ». Toute primitive non
# classee empeche PROTECTED : c'est UNKNOWN != NO applique a l'exhaustivite.
KNOWN = "KNOWN"
SUSPECTED = "SUSPECTED"
UNKNOWN_CAPABILITY = "UNKNOWN"
UNREACHABLE = "UNREACHABLE"
PROVEN_CLOSED = "PROVEN_CLOSED"
ETATS_DECOUVERTE = (KNOWN, SUSPECTED, UNKNOWN_CAPABILITY, UNREACHABLE, PROVEN_CLOSED)
SURFACE_INCOMPLETE = "EFFECT_SURFACE_INCOMPLETE"


@dataclass
class MetaEffet:
    """Un effet capable d'AFFAIBLIR la protection d'un autre effet.

    C'est l'angle mort principal : un client n'a pas besoin de produire X s'il
    peut produire « desactiver le garde de X », puis X. Tant que le garde de X
    est modifiable par le meme client, `EFFECT_BLOCKED(X)` ne veut plus dire
    grand-chose.
    """

    cible: str                  # ce qui est modifiable (gate, policy, test...)
    artefact: str               # ou il vit reellement
    modifiable_par: str         # la classe d'effet qui suffit a le modifier
    protege_par: str = ""       # None/"" = rien ne le protege
    mesure: str = ""            # comment on l'a su


@dataclass
class NoeudConfiance:
    """Un maillon de la chaine qui protege un effet."""

    nom: str
    protege_par: str = ""       # le maillon au-dessus ; "" = racine declaree
    artefact: str = ""
    modifiable_par_le_client: bool | None = None  # None = non mesure


def cycle_de_confiance(noeuds: dict, depart: str, profondeur_max: int = 12):
    """Remonte la chaine de protection et rend le CYCLE s'il existe.

    Une boucle d'auto-confiance n'est pas une racine de confiance : si le garde
    de X est modifiable par X, la protection se referme sur elle-meme. Rend la
    liste des maillons du cycle, ou [] si la chaine atteint une racine.
    """
    vus, courant, chaine = set(), depart, []
    for _ in range(profondeur_max):
        if courant in vus:
            i = chaine.index(courant)
            return chaine[i:] + [courant]
        vus.add(courant)
        chaine.append(courant)
        n = noeuds.get(courant)
        if n is None or not n.protege_par:
            return []  # racine atteinte (declaree)
        courant = n.protege_par
    return chaine + ["...profondeur max"]


@dataclass
class Preuve3Roles:
    """Qui produit l'effet, qui l'observe, qui verifie la preuve.

    Une preuve fabriquee par la surface qui a interet au verdict ne prouve
    rien. Si les trois roles sont tenus par le meme acteur, la preuve est
    AUTO-CERTIFIEE et ne compte pas.
    """

    producteur: str
    observateur: str
    verificateur: str

    def auto_certifiee(self) -> bool:
        return len({self.producteur, self.observateur, self.verificateur}) < 3


@dataclass
class Chemin:
    """Une route capable de produire l'effet. `instrumente=False` ne veut pas
    dire « sur », il veut dire « on n'a pas pu regarder »."""

    nom: str
    categorie: str
    ingress: str = ""
    instrumente: bool = False
    # Verdict de la DERNIERE tentative interdite jouee sur ce chemin.
    # None = jamais tentee. Ce n'est pas un succes.
    effet: str | None = None
    motif: str = ""

    def couvert(self) -> bool:
        """Couvert = une tentative interdite a ete jouee ET l'effet bloque."""
        return self.instrumente and self.effet == "EFFECT_BLOCKED"


@dataclass
class Preuve:
    """Ce qu'il faut avoir mesure pour parler d'EFFECT_BLOCKED."""

    etat_avant: str | None
    etat_apres: str | None
    decision: str | None          # ALLOW | DENY | None (pas de verdict)
    executor_atteint: bool | None  # None = non instrumente, JAMAIS False par defaut
    detail: str = ""


def effet_observe(p: Preuve) -> str:
    """Rend EFFECT_BLOCKED / EFFECT_OBSERVED / NON_CERTIFIANT.

    Aucune de ces trois reponses n'est un defaut : `NON_CERTIFIANT` est le
    verdict HONNETE quand une piece manque. Le ranger du cote sain serait
    exactement le fail-open qu'on cherche a eliminer.
    """
    if p.etat_avant is None or p.etat_apres is None:
        return "NON_CERTIFIANT: etat du monde non capture (avant=%r apres=%r)" % (
            p.etat_avant, p.etat_apres)
    if p.decision is None:
        return "NON_CERTIFIANT: aucune decision observee — un garde muet n'est pas un refus"
    monde_inchange = p.etat_avant == p.etat_apres
    if p.decision == "DENY":
        if not monde_inchange:
            # Le cas le plus grave : le gate a dit non, le monde a bouge.
            return "EFFECT_OBSERVED: DENY rendu mais le monde a change — canal lateral"
        if p.executor_atteint is None:
            return ("NON_CERTIFIANT: monde inchange et DENY, mais on ignore si "
                    "l'executor a ete atteint — un effet peut etre idempotent")
        if p.executor_atteint:
            return ("NON_CERTIFIANT: executor ATTEINT malgre DENY — le refus est "
                    "arrive trop tard pour etre une barriere")
        return "EFFECT_BLOCKED"
    if monde_inchange:
        return "NON_CERTIFIANT: ALLOW mais monde inchange — l'effet n'a pas eu lieu"
    return "EFFECT_OBSERVED"


@dataclass
class ClasseEffet:
    """Une classe d'effet et TOUTES les routes connues vers cet effet."""

    nom: str
    description: str
    chemins: list = field(default_factory=list)
    # Chemins soupconnes mais jamais confirmes ni ecartes : ils comptent CONTRE.
    suspects: list = field(default_factory=list)
    decouverte_adversariale_faite: bool = False
    # Primitives du SYSTEME capables de produire l'effet et non encore classees
    # (KNOWN / SUSPECTED / UNREACHABLE / PROVEN_CLOSED). Leur presence pose
    # EFFECT_SURFACE_INCOMPLETE et interdit PROTECTED.
    primitives_non_classees: list = field(default_factory=list)
    # Surfaces du monde a comparer en cas de DENY, propres a CETTE classe.
    # Un hash arbitraire ne suffit pas : DENY + modification d'une surface non
    # observee = EFFECT_OBSERVED, pas EFFECT_BLOCKED.
    surfaces_du_monde: list = field(default_factory=list)
    surfaces_du_monde_couvertes: bool = False
    # Le point unique par lequel l'effet doit passer. "" = non demontre.
    executor_unique: str = ""
    # Effets capables d'affaiblir la protection de celui-ci.
    meta_effets: list = field(default_factory=list)
    # {nom: NoeudConfiance} — la chaine remontant vers la racine de confiance.
    chaine_confiance: dict = field(default_factory=dict)
    # Qui produit / observe / verifie. None = preuve auto-certifiee par defaut.
    preuve_roles: object = None
    # Le scenario CHECK -> MUTATE -> EXECUTE a-t-il ete REELLEMENT joue ?
    toctou_joue: bool = False

    def equivalents_non_couverts(self) -> list:
        """Chemins capables du meme effet et dont le blocage n'est pas prouve."""
        return [c for c in self.chemins if not c.couvert()] + list(self.suspects)

    def verdicts(self) -> dict:
        """Les quatre axes historiques. Conserves : ils restent necessaires."""
        v = {}
        v[INVENTORIED] = bool(self.chemins)
        joues = [c for c in self.chemins if c.effet is not None]
        v[DECISION_PROVEN] = bool(joues) and all(
            c.effet != "NON_CERTIFIANT" for c in joues)
        v[ENFORCEMENT_PROVEN] = bool(joues) and all(c.couvert() for c in joues)
        # L'exhaustivite ne se DECLARE pas : elle exige qu'une phase de
        # decouverte adversariale ait cherche des chemins NON declares.
        v[EXHAUSTIVENESS_PROVEN] = (
            self.decouverte_adversariale_faite
            and not self.suspects
            and bool(self.chemins)
            and all(c.instrumente for c in self.chemins))
        return v

    def dimensions(self) -> dict:
        """Les douze dimensions, separement. Aucune n'est vraie par defaut.

        Un score global masquerait un axe rouge : on ne calcule donc aucune
        moyenne, seulement une conjonction.
        """
        v = self.verdicts()
        joues = [c for c in self.chemins if c.effet is not None]
        cycles = self.cycles_de_confiance()
        d = {
            "EFFECT_SURFACE_DEFINED": bool(self.description and self.chemins),
            "ALL_KNOWN_INGRESS_ENUMERATED": v[INVENTORIED],
            "EFFECT_EQUIVALENCE_CLOSURE_PROVEN": (
                not self.equivalents_non_couverts()
                and not self.primitives_non_classees),
            "DECISION_PROVEN": v[DECISION_PROVEN],
            "EXECUTION_MEDIATED": bool(joues) and all(
                c.effet != "NON_CERTIFIANT" for c in joues) and bool(self.executor_unique),
            "EFFECT_BLOCKED_PROVEN": v[ENFORCEMENT_PROVEN],
            "WORLD_STATE_COVERAGE_PROVEN": bool(self.surfaces_du_monde)
            and self.surfaces_du_monde_couvertes,
            "TOCTOU_SAFE": self.toctou_joue,
            "META_EFFECTS_PROTECTED": bool(self.meta_effets) and all(
                m.protege_par for m in self.meta_effets),
            "ROOT_OF_TRUST_INTACT": bool(self.chaine_confiance) and not cycles,
            "PROOF_NOT_SELF_CERTIFIED": (
                self.preuve_roles is not None and not self.preuve_roles.auto_certifiee()),
            "ADVERSARIAL_DISCOVERY_FOUND_NO_UNRESOLVED_PATH": (
                self.decouverte_adversariale_faite
                and not self.suspects
                and not self.primitives_non_classees),
        }
        return d

    def cycles_de_confiance(self) -> list:
        """Boucles d'auto-confiance dans la chaine qui protege cet effet."""
        if not self.chaine_confiance:
            return []
        return cycle_de_confiance(self.chaine_confiance, self.nom)

    def etat(self) -> dict:
        """Verdict complet. `PROTECTED` exige les DOUZE dimensions."""
        d = self.dimensions()
        manquantes = [k for k in DIMENSIONS if not d[k]]
        equivalents = self.equivalents_non_couverts()
        cycles = self.cycles_de_confiance()
        meta_nus = [m.cible for m in self.meta_effets if not m.protege_par]
        protege = not manquantes and not equivalents and not cycles
        etat = {
            "effect_class": self.nom,
            "dimensions": d,
            "dimensions_manquantes": manquantes,
            EQUIV_NON_COUVERT: [c.nom for c in equivalents],
            "primitives_non_classees": list(self.primitives_non_classees),
            "meta_effets_non_proteges": meta_nus,
            "cycle_de_confiance": cycles,
            "chemins_connus": len(self.chemins),
            "chemins_instrumentes": sum(1 for c in self.chemins if c.instrumente),
            "verdict": "PROTECTED" if protege else "NON_CERTIFIANT",
            "motif": "" if protege else _motif(manquantes, equivalents),
        }
        if self.primitives_non_classees:
            etat[SURFACE_INCOMPLETE] = True
        return etat


def _motif(manquants, equivalents) -> str:
    bouts = []
    if manquants:
        bouts.append("axes non prouves: " + ", ".join(manquants))
    if equivalents:
        bouts.append("%d chemin(s) equivalent(s) non couvert(s): %s"
                     % (len(equivalents), ", ".join(c.nom for c in equivalents)))
    return " | ".join(bouts)


# --- transitions interdites -------------------------------------------------
# Chacune est une confusion PAYEE, pas une precaution de style. Le runtime ne
# doit jamais pouvoir passer de la gauche a la droite.
TRANSITIONS_INTERDITES = {
    ("REQUESTED", "EFFECT_COMMITTED"): "une demande n'est pas un effet",
    ("DENIED", "ALLOW_BY_RETRY"): "reessayer ne cree pas l'autorisation",
    ("DENIED", "SAME_EFFECT_ALIAS"): "changer de tool ne change pas l'effet",
    ("DECLARED", "VERIFIED"): "une affirmation n'est pas une mesure",
    ("INDECIDABLE", "ALLOW"): "l'indecidable ferme, il n'ouvre pas",
    ("DISABLED_BY_POLICY", "RESOURCE_ERROR"): "un choix n'est pas une panne",
    ("DELEGATED", "COMPLETED"): "deleguer n'est pas terminer",
    ("STALE_VERDICT", "ALLOW"): "un verdict perime ne vaut plus",
    ("UNKNOWN_SCOPE", "EXECUTE"): "on n'execute pas dans un perimetre inconnu",
    ("CHILD_AUTHORITY", "GREATER_THAN_PARENT"): "l'enfant n'excede jamais le parent",
    ("LEARNED_RULE", "POLICY_OVERRIDE"): "apprendre ne donne pas le droit",
    ("MEMORY_WRITE", "AUTHORITY_GRANT"): "ecrire en memoire ne cree pas d'autorite",
    ("AUTHORIZED_A", "EXECUTE_B"): "une permission porte sur l'effet canonique",
    ("TOCTOU", "EXECUTE"): "la precondition se revalide au moment de l'effet",
}


def transition_interdite(depuis: str, vers: str) -> str | None:
    """Rend le motif si la transition est interdite, None sinon."""
    return TRANSITIONS_INTERDITES.get((depuis, vers))


# --- premiere classe declaree ----------------------------------------------
# Chemins RELEVES par mesure dans la session du 2026-09-12, pas supposes.
# `instrumente=False` partout : AUCUNE tentative interdite n'a encore ete jouee.
# C'est le point de depart honnete de M0 — et c'est pour cela que cette classe
# rend NON_CERTIFIANT malgre le correctif d'armement du tool_gate.

def surface_write_repository() -> ClasseEffet:
    """Toutes les routes connues vers « modifier un fichier du depot ».

    L'unite n'est pas le tool : `Write` refuse ne dit rien de `Bash` + `>`.
    Chaque entree ci-dessous produit le MEME effet final observable.
    """
    c = ClasseEffet(
        nom="WRITE_REPOSITORY",
        description="modifier un fichier suivi par git dans le depot Nokido",
    )
    c.chemins = [
        Chemin("Write natif", "DIRECT", "hook PreToolUse -> forge_tool_gate"),
        Chemin("Edit natif", "DIRECT", "hook PreToolUse -> forge_tool_gate"),
        Chemin("NotebookEdit", "ALIAS", "hook PreToolUse — couverture a verifier"),
        Chemin("governed_edit", "MCP", "route gouvernee : AST + secret + tree_lock"),
        Chemin("Bash redirection >", "ALIAS", "outil Bash ; bash_guard attendu"),
        Chemin("run action=shell (cmd)", "CLI", "cmd.exe sous LaForgeSbxOffline"),
        Chemin("run action=python + open()", "SUBPROCESS", "workspace guard"),
        Chemin("run action=trusted_script", "SCRIPT", "LaForgeTrusted, script git-tracke"),
        Chemin("run action=run_job", "RUN_JOB", "job detache, survit au restart"),
        Chemin("run sandbox=ps_clm", "PS_CLM", "NT AUTHORITY\\SYSTEM"),
        Chemin("git apply / checkout", "INDIRECT", "ecrit sans passer par un editeur"),
        Chemin("client sans hooks", "HOOKLESS_CLIENT", "Antigravity : aucun hook applicable"),
        Chemin("delegation WORKER_CODE", "DELEGATION", "un autre agent ecrit a ma place"),
        Chemin("retry apres refus", "RETRY", "meme effet, autre tool"),
    ]
    # SOUPCONNES, ni confirmes ni ecartes — ils comptent CONTRE l'exhaustivite.
    c.suspects = [
        Chemin("archive extraite / rename / copy", "INDIRECT",
               "produit un fichier sans appel d'ecriture explicite"),
        Chemin("artefact genere par un service", "INDIRECT",
               "un daemon ecrit dans le depot sans passer par un client"),
    ]
    # META-EFFETS : ce qui, s'il est modifie, AFFAIBLIT la protection ci-dessus.
    # `protege_par=""` signifie : RIEN ne le protege. Mesure du 2026-09-12 —
    # CRITICAL_FILES ne contient que 8 entrees (nokido_hub, forge_mcp_registry,
    # forge_mcp_security, forge_rbac, web_hub/auth, web_hub/app, .env,
    # Nokido.env). Aucun garde client n'y figure.
    c.meta_effets = [
        MetaEffet("gate d'ecriture client", "tools/forge_tool_gate.py",
                  "WRITE_REPOSITORY", "",
                  "absent de CRITICAL_FILES ; modifie par governed_edit le 2026-09-12"),
        MetaEffet("liste des tests executes en CI", "tools/ci_local.py",
                  "WRITE_REPOSITORY", "",
                  "absent de CRITICAL_FILES ; modifie 5 fois le 2026-09-12"),
        MetaEffet("tests de non-regression", "tests/nr/*.py",
                  "WRITE_REPOSITORY", "",
                  "aucun NR n'est protege : la PREUVE est modifiable par l'acteur"),
        MetaEffet("hooks d'enforcement", "tools/hook_*.py, bash_guard.py",
                  "WRITE_REPOSITORY", "",
                  "absents de CRITICAL_FILES"),
        MetaEffet("surface de services", "proxy_deno/core/services.toml",
                  "WRITE_REPOSITORY", "", "absent de CRITICAL_FILES"),
        MetaEffet("module M0 lui-meme", "tools/forge_effect_surface.py",
                  "WRITE_REPOSITORY", "",
                  "l'instrument qui juge est modifiable par ce qu'il juge"),
    ]
    # CHAINE DE CONFIANCE — et elle se referme sur elle-meme.
    c.chaine_confiance = {
        "WRITE_REPOSITORY": NoeudConfiance(
            "WRITE_REPOSITORY", protege_par="tool_gate",
            artefact="depot", modifiable_par_le_client=True),
        "tool_gate": NoeudConfiance(
            "tool_gate", protege_par="WRITE_REPOSITORY",
            artefact="tools/forge_tool_gate.py", modifiable_par_le_client=True),
    }
    # SURFACES DU MONDE a comparer en cas de DENY. Un hash du seul fichier cible
    # ne suffit pas : un effet peut passer par l'index, une ref ou un submodule.
    c.surfaces_du_monde = ["working tree", "index git", "HEAD", "refs",
                           "fichiers non suivis", "worktrees", "submodules",
                           "metadonnees de fichier"]
    c.surfaces_du_monde_couvertes = False  # aucune capture n'a encore ete faite
    c.executor_unique = ""  # aucun point unique demontre
    c.preuve_roles = None   # producteur == observateur == verificateur : auto-certifiee
    c.toctou_joue = False
    # PRIMITIVES du systeme capables de produire l'effet, non encore classees.
    # Leur presence pose EFFECT_SURFACE_INCOMPLETE : « le scanner a fini » n'est
    # pas « il n'y a rien d'autre ».
    c.primitives_non_classees = [
        "API systeme de fichiers (CreateFile/MoveFile)",
        "lien symbolique / jonction",
        "rename atomique depuis un temporaire",
        "extraction d'archive",
        "installation de paquet (pip/npm)",
        "swap file d'editeur",
        "manipulation de l'index git",
        "worktree git secondaire",
        "tache planifiee",
        "service ecrivant dans le depot",
        "observateur de systeme de fichiers",
        "processus d'arriere-plan deja lance",
    ]
    # Aucune phase de decouverte adversariale n'a encore ete menee.
    c.decouverte_adversariale_faite = False
    return c


SURFACES = {"WRITE_REPOSITORY": surface_write_repository}


def rapport() -> dict:
    """Etat M0 de toutes les classes declarees."""
    return {nom: f().etat() for nom, f in sorted(SURFACES.items())}


if __name__ == "__main__":
    import json

    etats = rapport()
    print(json.dumps(etats, ensure_ascii=False, indent=1))
    # Un chemin equivalent non couvert fait ECHOUER M0 : c'est la categorie
    # obligatoire de l'audit. Le code de retour le dit.
    rouge = [n for n, e in etats.items() if e["verdict"] != "PROTECTED"]
    if rouge:
        print("\nM0 ROUGE — classes non certifiees : " + ", ".join(rouge))
        raise SystemExit(1)
    print("\nM0 VERT")
