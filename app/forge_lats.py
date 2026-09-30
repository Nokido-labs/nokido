"""app/forge_lats.py - Language Agent Tree Search (Hassabis, Yao 2024).

Pour SWE-bench et toute tache d edition de code ouverte :
au lieu de generer UNE solution sequentielle (DSPy-style, fragile sur
backtrack), on genere un ARBRE de patches concurrents, on les eprouve
chacun dans son sandbox isole avec un juge DETERMINISTE (pytest), et on
remonte vers le noeud "moins echoue" en cas d echec total.

Architecture :
  1. PatchProposal : un patch unidiff candidat + son rationale + provider source
  2. SandboxResult : apply + tests + score deterministe (0 fail = 1.0,
     N fail/M total = (M-N)/M)
  3. LATSNode : arbre {patch, parent, children, score, attempts}
  4. lats_search(problem, propose_fn, test_fn, budget) :
     - generate N initial proposals via propose_fn (cloud LLM)
     - eprouve chacun via sandbox (test_fn)
     - si succes pur (score=1.0) : return
     - sinon : pour les K meilleurs, demande raffinement (propose_fn avec
       error_context du parent) -> children
     - max_depth limite l explosion combinatoire

Pas de DSPy. propose_fn = callable libre (texte -> diff). test_fn =
callable (workdir, diff) -> (passed, total, error_log). Nokido le wire
sur sandbox file copy + pytest subprocess.

Le scoring deterministe = juge symbolique au sens Marcus : pas de LLM
qui valide, ce sont les tests qui parlent.
"""

from __future__ import annotations

import logging
import shutil
import threading
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("Nokido.LATS")


# === Data models =============================================================


# Sous ce taux de mutants tues, une variante n'est pas PROMOUVABLE, meme si
# elle domine le classement : ses tests verts ne prouvent rien.
SEUIL_MUTATION_PROMOTION = 0.25

# ETAT EVALUE -- trois valeurs, jamais une approximation (P0, revue du
# 2026-08-20). Le bac contenait implicitement « HEAD + modifications suivies -
# suppressions suivies + peut-etre des absents », et cette ambiguite se lisait
# seulement dans un log. Un moteur qui evalue une representation PARTIELLE du
# depot peut conclure « ce patch casse » ou « ce patch ameliore » a propos d'un
# comportement qui depend en realite d'un fichier absent du bac.
#
# NOTE D'IMPLANTATION : ces noms sont definis ICI, avant les dataclasses qui les
# prennent comme valeur par defaut. Les placer plus bas levait un NameError au
# CHARGEMENT -- exactement la faute reparee le matin meme dans
# `forge_at_dispatch`. Un nom se lie avant son usage, y compris a soi-meme.
LIVE_COMPLETE = "LIVE_COMPLETE"    # le bac porte exactement le working tree
LIVE_PARTIAL = "LIVE_PARTIAL"      # il manque des fichiers du vivant
HEAD_ONLY = "HEAD_ONLY"            # le bac ne porte que HEAD


@dataclass
class EtatVivant:
    """Ce que le bac porte VRAIMENT, et ce qu'il n'a pas pu porter.

    `complet` n'est pas une politesse : il commande la promotion. Un candidat
    evalue sur un depot partiel reste EXPERIMENTAL, quel que soit son score --
    sinon le moteur apprend a raisonner sur une realite tronquee.
    """

    base_head: str = ""
    suivis_modifies: list[str] = field(default_factory=list)
    suivis_supprimes: list[str] = field(default_factory=list)
    non_suivis_absents: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)

    @property
    def mode(self) -> str:
        if self.omissions or self.non_suivis_absents:
            return LIVE_PARTIAL
        if self.suivis_modifies or self.suivis_supprimes:
            return LIVE_COMPLETE
        return HEAD_ONLY

    @property
    def complet(self) -> bool:
        """HEAD_ONLY est COMPLET : un depot propre n'a rien de plus a porter."""
        return self.mode in (LIVE_COMPLETE, HEAD_ONLY)

    def resume(self) -> str:
        bouts = [self.mode]
        if self.suivis_modifies:
            bouts.append("%d modifies" % len(self.suivis_modifies))
        if self.suivis_supprimes:
            bouts.append("%d supprimes" % len(self.suivis_supprimes))
        if self.non_suivis_absents:
            bouts.append("%d non suivis ABSENTS" % len(self.non_suivis_absents))
        if self.omissions:
            bouts.append("%d omissions" % len(self.omissions))
        return " / ".join(bouts)


@dataclass
class PatchProposal:
    diff: str  # unidiff text
    rationale: str = ""
    provider: str = ""
    ms_to_generate: int = 0


@dataclass
class SandboxResult:
    passed: int = 0  # tests reussis
    total: int = 0  # tests executes
    apply_ok: bool = False
    error_log: str = ""  # stack trace / pytest output abreges
    elapsed_s: float = 0.0
    # Verdict du garde de mutation. TROIS etats, jamais deux :
    #   True  : la variante a ete examinee et acceptee
    #   False : elle a ete REFUSEE (troncation, classe perdue, derive)
    #   None  : le garde n'a PAS pu se prononcer -- ce n'est pas un succes,
    #           et `guard_motif` dit pourquoi.
    guard_ok: bool | None = None
    guard_motif: str = ""
    # PAS 2 -- la selection ne se contente plus de « les tests passent ».
    # `mutants_total = 0` signifie NON MESURE : le score reste alors celui des
    # tests, et personne ne pretend qu'une couverture a ete verifiee.
    mutants_tues: int = 0
    mutants_total: int = 0
    bac: str = ""  # "worktree" | "copie" -- quel substrat a servi
    etat_vivant: str = HEAD_ONLY   # LIVE_COMPLETE | LIVE_PARTIAL | HEAD_ONLY
    etat_detail: str = ""

    @property
    def score_tests(self) -> float:
        if self.guard_ok is False or not self.apply_ok or self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def score_mutation(self) -> float | None:
        """Part des mutants tues, ou None si la mesure n'a pas eu lieu."""
        if self.mutants_total <= 0:
            return None
        return self.mutants_tues / self.mutants_total

    @property
    def promouvable(self) -> tuple[bool, str]:
        """Le score CLASSE ; ceci AUTORISE -- ce sont deux questions distinctes.

        Ajoute le 2026-08-20 (revue externe). La ponderation du score reduit
        l'atrophie sans l'interdire : des tests verts qui ne tuent AUCUN mutant
        conservent 0.50 et restent competitifs face a un candidat honnete plus
        faible sur les tests. Or le depot a mesure des surfaces a 8,3 % de
        mutants tues -- une suite de ce niveau ne doit pas pouvoir promouvoir
        une mutation, quel que soit son rang.

        Un seuil qui n'a PAS ete mesure n'interdit rien : `None` laisse passer,
        et le motif le dit. Interdire sur une mesure absente reviendrait a punir
        l'ignorance plutot que la faiblesse.
        """
        if self.guard_ok is False:
            return False, "refuse par le garde de mutation"
        if not self.apply_ok:
            return False, "patch non applique"
        if self.etat_vivant == LIVE_PARTIAL:
            # REGLE DURE (P0). Un depot partiel donne un verdict sur une realite
            # qui n'est pas celle du depot. L'experimentation reste permise --
            # c'est son interet -- mais la PROMOTION est interdite, quel que
            # soit le score. Le dire dans un log n'aurait pas suffi.
            return False, ("etat evalue PARTIEL (%s) : experimentation seulement"
                           % (self.etat_detail or "fichiers du vivant absents"))
        if self.score_tests < 1.0:
            return False, "tests non integralement verts"
        mut = self.score_mutation
        if mut is None:
            return True, "mutation non mesuree -- promotion autorisee, non prouvee"
        if mut < SEUIL_MUTATION_PROMOTION:
            return False, ("mutants tues %.0f%% < seuil %.0f%% : la suite ne "
                           "protege pas ce qu'elle declare vert"
                           % (mut * 100, SEUIL_MUTATION_PROMOTION * 100))
        return True, ""

    @property
    def score(self) -> float:
        # UN REFUS DU GARDE NE PEUT JAMAIS GAGNER (2026-08-20). Sans cette
        # ligne, une variante qui tronque un fichier obtiendrait un score
        # parfait des lors que les tests survivants passent -- la selection
        # apprendrait alors a SUPPRIMER le code non couvert. Le garde est
        # eliminatoire, il ne se moyenne pas avec le reste.
        if self.guard_ok is False:
            return 0.0
        if not self.apply_ok:
            return 0.0
        if self.total == 0:
            return 0.0
        base = self.passed / self.total
        mut = self.score_mutation
        if mut is None:
            # Mutation NON MESUREE : on rend le score des tests, sans le
            # maquiller. Melanger une mesure absente a une mesure faite
            # fabriquerait un chiffre que personne ne peut interpreter.
            return base
        # MESUREE : des tests verts qui ne tuent aucun mutant valent MOITIE.
        # Sans cette ponderation, la selection recompense la suppression de
        # code non couvert -- l'atrophie obtient 1.0 et gagne l'arbre.
        return base * (0.5 + 0.5 * mut)


@dataclass
class LATSNode:
    patch: PatchProposal | None
    result: SandboxResult | None = None
    parent: Optional["LATSNode"] = None
    children: list["LATSNode"] = field(default_factory=list)
    depth: int = 0


# === Sandbox apply + test ====================================================


# PAS 3 -- PLAFOND DE LARGEUR. Un bac a sable materialise l'arbre de travail :
# le depot compte ~4455 fichiers suivis, donc chaque branche ouverte coute du
# disque et des inodes. Sur une machine qui declenche deja des `evict_detresse`,
# un arbre large est un risque REEL, pas theorique. Le plafond est un garde
# d'admission, au meme titre que la lane des jobs lourds.
PLAFOND_BACS = 4
# COMPTEUR ATOMIQUE (correction 2026-08-20, revue externe). Un `+= 1` global
# n'est sur qu'en mono-thread : deux appelants concurrents lisent 3, ouvrent
# tous les deux, et le plafond de 4 devient 5. Nokido est justement un systeme
# multi-agent -- le garde d'admission doit donc etre un semaphore, pas une
# convention. `BoundedSemaphore` leve si on relache plus qu'on n'a pris, ce qui
# transforme une retraction en double en erreur VISIBLE plutot qu'en derive.
_semaphore_bacs = threading.BoundedSemaphore(PLAFOND_BACS)


def _bacs_ouverts() -> int:
    """Bacs actuellement pris. Lecture indicative, pour les tests et les logs."""
    return PLAFOND_BACS - _semaphore_bacs._value  # noqa: SLF001


# CE QUE LE BAC ISOLE, ET CE QU'IL N'ISOLE PAS (point 10 de la revue externe,
# 2026-08-20). Le mot « sandbox » recouvre deux choses tres differentes, et les
# confondre serait dangereux le jour ou ce moteur tournera sans surveillance.
#
#   ISOLE (isolation GIT)            N'ISOLE PAS (isolation d'EXECUTION)
#   --------------------------       ----------------------------------
#   l'arbre de fichiers              le reseau : le code teste peut sortir
#   l'index et HEAD du depot         les processus : rien ne borne un fork
#   le retour arriere (retraction)   les ressources : ni RAM, ni CPU, ni disque
#   les branches concurrentes        les secrets : l'environnement est herite
#                                    le systeme de fichiers hors du bac
#
# Autrement dit : un patch malveillant ou simplement fautif s'execute ici avec
# les droits du processus appelant. La retraction annule ses ECRITURES DANS LE
# BAC, jamais ses effets de bord ailleurs. Pour une execution reellement
# confinee il faut passer par `forge_sandbox_exec` / le pont Docker, qui eux
# posent network=none et un compte non privilegie.
#
# On ne renomme pas la variable `sandbox` -- elle est juste dans le sens git --
# mais on ecrit la limite ici, parce qu'une capacite autonome qui croirait
# s'executer confinee prendrait des risques qu'elle ne mesure pas.
ISOLATION = {"git": True, "reseau": False, "processus": False,
             "ressources": False, "secrets": False}


def _ouvrir_bac(workdir_src: str | Path):
    """Prepare un bac a sable jetable -> (chemin, retracter, genre).

    ⚠ Isolation GIT, pas isolation d'EXECUTION : voir `ISOLATION` ci-dessus.

    WORKTREE D'ABORD (2026-08-20). `shutil.copytree` duplique AUSSI le dossier
    `.git`, c'est-a-dire tout l'historique : sur ce depot, c'est l'essentiel du
    poids copie pour rien. `git worktree` materialise les fichiers mais PARTAGE
    l'object store -- moins de disque, et surtout une retraction propre par
    `git worktree remove`, qui est exactement l'apoptose qu'on veut pour une
    branche qui regresse. Repli sur la copie si la source n'est pas un depot :
    un repli qui se tait serait pire que pas de repli du tout, donc le genre
    retenu est rendu a l'appelant et journalise.
    """
    if not _semaphore_bacs.acquire(blocking=False):
        raise RuntimeError(
            "plafond de %d bacs simultanes atteint : elargir l'arbre au-dela "
            "sature le disque avant d'ameliorer la recherche" % PLAFOND_BACS)
    try:
        cible = Path(tempfile.mkdtemp(prefix="lats_"))
        src = str(workdir_src)
        est_git = subprocess.run(["git", "-C", src, "rev-parse", "--git-dir"],
                                 capture_output=True, text=True, errors="replace",
                                 timeout=30).returncode == 0
        if est_git:
            # `--detach` : la branche courante n'est jamais deplacee par l'arbre.
            r = subprocess.run(
                ["git", "-C", src, "worktree", "add", "--detach", str(cible), "HEAD"],
                capture_output=True, text=True, errors="replace", timeout=120)
            if r.returncode == 0:
                etat = _aligner_sur_le_vivant(src, cible)
                genre = "worktree/" + etat.resume()

                def _retracter() -> None:
                    try:
                        subprocess.run(["git", "-C", src, "worktree", "remove",
                                        "--force", str(cible)],
                                       capture_output=True, text=True,
                                       errors="replace", timeout=60)
                        subprocess.run(["git", "-C", src, "worktree", "prune"],
                                       capture_output=True, text=True,
                                       errors="replace", timeout=60)
                        shutil.rmtree(cible, ignore_errors=True)
                    finally:
                        _semaphore_bacs.release()

                return cible, _retracter, genre, etat
            logger.warning("[LATS] worktree indisponible (%s) : repli sur copie",
                           (r.stderr or "").strip()[:120])
        # REPLI ASSUME. Il copie AUSSI `.git`, donc tout l'historique : c'est
        # precisement le cout que le worktree evite. On le garde parce qu'il est
        # le seul chemin qui laisse `git apply --3way` fonctionner, mais il est
        # journalise -- un repli couteux qui se tait ferait passer une lenteur
        # soudaine pour une fatalite.
        logger.warning("[LATS] repli COPIE INTEGRALE de %s (historique inclus)", src)
        shutil.copytree(src, str(cible), dirs_exist_ok=True)

        def _retracter_copie() -> None:
            try:
                shutil.rmtree(cible, ignore_errors=True)
            finally:
                _semaphore_bacs.release()

        # La copie transporte le working tree TEL QUEL : rien ne manque.
        return cible, _retracter_copie, "copie", EtatVivant(base_head="copie")
    except Exception:
        _semaphore_bacs.release()
        raise


def _aligner_sur_le_vivant(src: str, cible: Path) -> "EtatVivant":
    """Reporte dans le bac les modifications NON COMMITEES du depot source.

    P0 CORRIGE LE 2026-08-20 (revue externe). `git worktree add ... HEAD`
    materialise HEAD -- pas l'etat courant. L'ancien `copytree` transportait le
    working tree tel quel. Le remplacer sans compenser changeait donc la BASE
    EVALUEE en silence : l'arbre jugeait un patch contre un depot d'il y a
    quelques commits, et pouvait declarer casse un correctif qui marche, ou
    meilleur un candidat qui exploite un etat revolu.

    On reporte donc `git diff HEAD` (fichiers SUIVIS). Les fichiers non suivis
    ne sont pas transportes -- ils ne peuvent pas l'etre par un patch -- mais
    ils sont COMPTES et nommes dans le genre du bac, pour qu'un ecart entre le
    bac et le depot ne reste jamais invisible.
    """
    etat = EtatVivant()
    r_head = subprocess.run(["git", "-C", src, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, errors="replace", timeout=30)
    etat.base_head = (r_head.stdout or "").strip()
    # COPIE CIBLEE, PAS PATCH (mesure 2026-08-20, run GHA 32413377037).
    # La premiere version generait `git diff HEAD` puis `git apply` dans le bac.
    # Vert en local, ROUGE sur le runner : « patch failed: a.py:1 ». Cause --
    # le patch sort en LF quand le checkout du worktree applique la conversion
    # de fins de ligne du depot. Le patch etait une complication : on veut juste
    # que le bac porte les MEMES OCTETS que le working tree. On copie donc les
    # fichiers que git declare modifies, ce qui ne depend d'aucune convention.
    r = subprocess.run(["git", "-C", src, "diff", "HEAD", "--name-status"],
                       capture_output=True, text=True, errors="replace", timeout=120)
    if r.returncode == 0 and (r.stdout or "").strip():
        for ligne in r.stdout.splitlines():
            morceaux = ligne.split("\t")
            if len(morceaux) < 2:
                continue
            statut, rel = morceaux[0].strip(), morceaux[-1].strip()
            source_f, cible_f = Path(src) / rel, cible / rel
            try:
                if statut.startswith("D"):
                    # Supprime dans le vivant : le bac doit l'etre aussi, sinon
                    # il evalue un fichier que le depot n'a plus.
                    cible_f.unlink(missing_ok=True)
                    etat.suivis_supprimes.append(rel)
                else:
                    cible_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_f, cible_f)
                    etat.suivis_modifies.append(rel)
            except OSError as exc:
                # Ne PAS se taire : une partie du vivant manque, et l'etat
                # bascule en PARTIEL, ce qui INTERDIT la promotion.
                etat.omissions.append("%s (%s)" % (rel, type(exc).__name__))
                logger.warning("[LATS] fichier local NON reporte : %s (%s)",
                               rel, type(exc).__name__)
    r_untracked = subprocess.run(
        ["git", "-C", src, "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, errors="replace", timeout=60)
    etat.non_suivis_absents = [x.strip() for x in (r_untracked.stdout or "").splitlines()
                               if x.strip()]
    if etat.non_suivis_absents:
        logger.warning("[LATS] %d fichier(s) NON SUIVIS absents du bac : etat PARTIEL, "
                       "promotion interdite", len(etat.non_suivis_absents))
    return etat


def _fichiers_python_du_diff(diff: str) -> list[str]:
    """Chemins `.py` touches par un unidiff, lus sur les entetes `+++ b/...`."""
    out: list[str] = []
    for ligne in diff.splitlines():
        if not ligne.startswith("+++ "):
            continue
        chemin = ligne[4:].strip().split("\t")[0]
        if chemin.startswith(("a/", "b/")):
            chemin = chemin[2:]
        if chemin and chemin != "/dev/null" and chemin.endswith(".py"):
            out.append(chemin)
    return out


def garde_mutation(workdir_src: str | Path, sandbox: str | Path, diff: str):
    """Soumet chaque fichier touche au `MutationGuard` -> (ok, motif).

    POURQUOI ICI (2026-08-20). L'arbre de recherche selectionnait sur « les
    tests passent ». Or un LLM qui tronque un fichier fait passer les tests des
    lors que la partie supprimee n'est pas couverte -- et le depot a deja mesure
    des surfaces a 8,3 % de mutants tues. Une pression myope de ce genre ne
    selectionne pas l'amelioration, elle selectionne l'ATROPHIE.

    `MutationGuard` refuse ce que pytest ne voit pas : troncation, classe
    disparue, derive semantique. Il tourne AVANT le juge, donc une variante
    refusee ne consomme meme pas un run de tests.

    `ok=None` = le garde n'a pas pu se prononcer. Ce n'est pas un succes : le
    motif est conserve, et l'appelant peut le lire plutot que de le deviner.
    """
    try:
        from nokido_agent.app.forge_self_mutation import MutationGuard
    except Exception as exc:  # noqa: BLE001 - garde absent : DIT, jamais tu
        return None, "garde indisponible (%s)" % type(exc).__name__
    garde = MutationGuard()
    compares = 0
    for rel in _fichiers_python_du_diff(diff):
        avant_p, apres_p = Path(workdir_src) / rel, Path(sandbox) / rel
        # Fichier cree ou supprime : il n'y a pas deux versions a comparer.
        # Ce n'est pas un refus, et ce n'est pas non plus une validation.
        if not avant_p.exists() or not apres_p.exists():
            continue
        compares += 1
        try:
            avant = avant_p.read_text(encoding="utf-8", errors="replace")
            apres = apres_p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return None, "lecture impossible %s (%s)" % (rel, type(exc).__name__)
        ok, motif = garde.valider(avant, apres)
        if not ok:
            return False, "%s : %s" % (rel, motif)

        # Second garde, sur ce que le premier ne peut pas voir : la FORME est
        # intacte mais la POLITIQUE s'est inversee (`return user.is_admin` ->
        # `return True`). Ce cas ameliore le score au lieu de le degrader, la
        # suite couvrant surtout le chemin autorise -- l'arbre selectionnerait
        # donc activement l'affaiblissement des controles.
        try:
            from nokido_agent.app.forge_semantic_invariant import garde_invariant_semantique
        except Exception as exc:  # noqa: BLE001 - absent : DIT, jamais tu
            return None, "garde semantique indisponible (%s)" % type(exc).__name__
        ok_sem, motif_sem = garde_invariant_semantique(avant, apres)
        if not ok_sem:
            return False, "%s : %s" % (rel, motif_sem)
    if compares == 0:
        # ABSTENTION, PAS VALIDATION (correction 2026-08-20, revue externe).
        # Le commentaire ci-dessus disait deja « ce n'est pas non plus une
        # validation » -- et le code rendait pourtant True. Un diff qui ne cree
        # que des fichiers neufs n'a RIEN de comparable : le garde n'a donc rien
        # examine, et le dire est le seul verdict honnete. C'est exactement le
        # troisieme etat que ce module pretend offrir ; il faut qu'il l'utilise.
        return None, "aucun fichier comparable (creation ou suppression seules)"
    return True, ""


def default_apply_and_test(
    workdir_src: str | Path, diff: str, pytest_targets: list[str] | None = None, timeout_s: int = 60
) -> SandboxResult:
    """Copie workdir_src -> tmp, applique le diff via `git apply`, lance
    pytest sur pytest_targets (None = full discover).

    pytest_targets : liste de fichiers de test ou dossiers. Si None,
    pytest decouvre. Format SWE-bench : passer les FAIL_TO_PASS files.

    Retourne SandboxResult avec score deterministe."""
    t0 = time.monotonic()
    sb = SandboxResult()
    if not Path(workdir_src).exists():
        sb.error_log = f"workdir_src missing: {workdir_src}"
        return sb
    try:
        sandbox, _retracter, sb.bac, _etat = _ouvrir_bac(workdir_src)
        sb.etat_vivant, sb.etat_detail = _etat.mode, _etat.resume()
    except Exception as e:  # noqa: BLE001 - plafond atteint ou substrat indisponible
        sb.error_log = "bac indisponible: %s" % e
        sb.elapsed_s = time.monotonic() - t0
        return sb
    try:
        # Ecrit le diff dans un fichier temp
        diff_path = sandbox / ".lats_patch.diff"
        # `newline="\n"` EXPLICITE (mesure 2026-08-20, run GHA 32414071729).
        # `write_text` traduit `\n` en CRLF sur Windows : le PATCH lui-meme
        # partait en CRLF alors que les fichiers qu'il decrit sont en LF, et
        # `git apply` refusait -- « patch failed: <fichier>:1 ». Le patch etait
        # pourtant correct ; c'est son ECRITURE qui le corrompait. Un outil qui
        # compare des octets doit ecrire les octets qu'il a produits.
        diff_path.write_text(diff, encoding="utf-8", newline="\n")
        # Git apply (suppose git repo dans workdir_src ; sinon fallback simple)
        r_apply = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(diff_path)],
            cwd=str(sandbox),
            capture_output=True,
            text=True,
            timeout=30,
        errors="replace")
        if r_apply.returncode != 0:
            # Tentative 3-way merge
            r_apply2 = subprocess.run(
                ["git", "apply", "--3way", "--whitespace=nowarn", str(diff_path)],
                cwd=str(sandbox),
                capture_output=True,
                text=True,
                timeout=30,
            errors="replace")
            if r_apply2.returncode != 0:
                sb.apply_ok = False
                sb.error_log = f"git apply failed: {r_apply.stderr[:500]}\n3way: {r_apply2.stderr[:500]}"
                sb.elapsed_s = time.monotonic() - t0
                return sb
        sb.apply_ok = True
        # GARDE AVANT JUGE : une variante refusee ne merite pas qu'on depense
        # un run de tests dessus, et surtout elle ne doit pas pouvoir gagner.
        sb.guard_ok, sb.guard_motif = garde_mutation(workdir_src, sandbox, diff)
        if sb.guard_ok is False:
            sb.error_log = "REFUS DU GARDE DE MUTATION -- " + sb.guard_motif
            sb.elapsed_s = time.monotonic() - t0
            return sb
        # Pytest
        cmd = [sys.executable, "-m", "pytest", "-x", "--tb=short", "-q", "-p", "no:cacheprovider"]
        if pytest_targets:
            cmd.extend(pytest_targets)
        try:
            r_test = subprocess.run(cmd, cwd=str(sandbox), capture_output=True, text=True, timeout=timeout_s, errors="replace")
            out = (r_test.stdout or "") + (r_test.stderr or "")
            # Parse "N passed, M failed" ou "N passed"
            import re as _re

            m_pass = _re.search(r"(\d+)\s+passed", out)
            m_fail = _re.search(r"(\d+)\s+failed", out)
            m_err = _re.search(r"(\d+)\s+error", out)
            passed = int(m_pass.group(1)) if m_pass else 0
            failed = int(m_fail.group(1)) if m_fail else 0
            errored = int(m_err.group(1)) if m_err else 0
            sb.passed = passed
            sb.total = passed + failed + errored
            if r_test.returncode != 0 or sb.total == 0:
                sb.error_log = out[-3000:]
        except subprocess.TimeoutExpired:
            sb.error_log = f"pytest timeout {timeout_s}s"
    finally:
        sb.elapsed_s = time.monotonic() - t0
        # RETRACTION : la branche disparait, quoi qu'il soit arrive dedans.
        try:
            _retracter()
        except Exception:  # noqa: BLE001
            logger.warning("[LATS] retraction du bac %s incomplete", sandbox)
    return sb


# === LATS tree search ========================================================


def lats_search(
    problem: str,
    workdir: str | Path,
    propose_fn: Callable[[str, Optional[SandboxResult]], list[PatchProposal]],
    test_fn: Callable[[str, str], SandboxResult] | None = None,
    n_initial: int = 3,
    max_depth: int = 2,
    beam_width: int = 2,
    pytest_targets: list[str] | None = None,
    mutation_fn: Callable[[str, str], tuple[int, int]] | None = None,
) -> dict:
    """Search en arbre :
      - generate n_initial proposals via propose_fn(problem, None)
      - eprouve chacune via test_fn(workdir, diff)
      - garde beam_width meilleurs (par score)
      - si pas de score=1.0, refine chaque survivant (propose_fn avec
        error_log du parent comme contexte) -> children
      - max_depth limit l arbre
    Retourne {best_node, root, all_nodes, elapsed_s}."""
    t0 = time.monotonic()
    test_fn = test_fn or (lambda wd, diff: default_apply_and_test(wd, diff, pytest_targets=pytest_targets))

    root = LATSNode(patch=None, depth=0)
    all_nodes: list[LATSNode] = [root]

    def _eval_and_attach(proposals: list[PatchProposal], parent: LATSNode) -> list[LATSNode]:
        nodes: list[LATSNode] = []
        for prop in proposals:
            n = LATSNode(patch=prop, parent=parent, depth=parent.depth + 1)
            n.result = test_fn(str(workdir), prop.diff)
            parent.children.append(n)
            all_nodes.append(n)
            nodes.append(n)
            logger.info(
                "[LATS] depth=%d provider=%s score=%.2f passed=%d/%d",
                n.depth,
                prop.provider,
                n.result.score,
                n.result.passed,
                n.result.total,
            )
        return nodes

    # Depth 1 : initial proposals
    initial = propose_fn(problem, None)[:n_initial]
    layer = _eval_and_attach(initial, root)

    best = (
        max(all_nodes[1:], key=lambda n: n.result.score if n.result else 0.0, default=None)
        if len(all_nodes) > 1
        else None
    )

    # Refine si pas de score=1.0
    for depth in range(2, max_depth + 1):
        if best and best.result and best.result.score >= 1.0:
            break
        # Garde beam_width meilleurs survivants pour refine
        survivors = sorted([n for n in layer if n.result and n.result.apply_ok], key=lambda n: -n.result.score)[
            :beam_width
        ]
        if not survivors:
            # Aucun apply ok dans cette couche -> abandon
            break
        next_layer: list[LATSNode] = []
        for surv in survivors:
            refines = propose_fn(problem, surv.result)
            next_layer.extend(_eval_and_attach(refines[:n_initial], surv))
        layer = next_layer
        new_best = max(next_layer, key=lambda n: n.result.score if n.result else 0.0, default=None)
        if new_best and (
            best is None or (new_best.result and best.result and new_best.result.score > best.result.score)
        ):
            best = new_best

    # PAS 2 -- MUTATION SUR LES SEULS FINALISTES.
    # Pourquoi pas sur chaque noeud : une campagne de mutation coute des minutes
    # par surface, quand un run pytest coute des secondes. La mesurer partout
    # rendrait l'arbre inutilisable ; ne la mesurer nulle part laisse gagner
    # l'atrophie. On la reserve donc aux candidats qui ont DEJA convaincu les
    # tests -- c'est exactement la ou la question « ces tests valent-ils
    # quelque chose ? » se pose.
    if mutation_fn is not None:
        # CORRECTION 2026-08-20 (revue externe, point 9). Le filtre exigeait
        # `score_tests >= 1.0` : une variante a 98 % de tests mais 100 % de
        # mutants tues n'etait JAMAIS mesuree, donc jamais comparee a une
        # variante a 100 % de tests et 20 % de mutants. La mutation restait un
        # simple depart entre parfaits, et l'objectif reel demeurait « pytest ».
        # On mesure desormais les MEILLEURS candidats applicables, quel que soit
        # leur score de tests -- c'est ce qui fait de la mutation un critere, et
        # non un accessoire. Le budget reste borne par `beam_width`.
        candidats = [n for n in all_nodes[1:]
                     if n.result and n.result.apply_ok
                     and n.result.guard_ok is not False
                     and n.result.score_tests > 0.0]
        finalistes = sorted(candidats, key=lambda x: -x.result.score_tests)
        for n in finalistes[:max(beam_width, 2)]:
            try:
                tues, total = mutation_fn(str(workdir), n.patch.diff if n.patch else "")
            except Exception as exc:  # noqa: BLE001 - non mesure, jamais suppose
                logger.warning("[LATS] mutation non mesuree (%s)", type(exc).__name__)
                continue
            n.result.mutants_tues, n.result.mutants_total = tues, total
            logger.info("[LATS] finaliste mutants %d/%d -> score %.2f",
                        tues, total, n.result.score)
        # Re-depart : le meilleur peut CHANGER une fois la mutation mesuree.
        # C'est le but -- une variante qui passait les tests sans rien proteger
        # perd sa place ici, et pas plus tard en production.
        if finalistes:
            best = max(all_nodes[1:],
                       key=lambda n: n.result.score if n.result else 0.0,
                       default=best)

    elapsed = time.monotonic() - t0
    return {
        "best": best,
        "root": root,
        "all_nodes": all_nodes,
        "elapsed_s": round(elapsed, 1),
        "n_evaluated": len(all_nodes) - 1,
        "mutation_mesuree": bool(mutation_fn),
    }
