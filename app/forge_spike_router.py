#!/usr/bin/env python3
"""
forge_spike_router.py — Routeur neuronal à basculement de phase
================================================================
Remplace le triage if/else statique par un routeur SNN qui APPREND
quelles stratégies fonctionnent pour quels challenges.

Architecture:
  Challenge → FeatureExtractor → SpikeRouter → Stratégie
                                      ↓
                                 Confiance (amplitude du spike)
                                      ↓
                                 skip si confiance < seuil_min

Entraîné sur 38 challenges résolus.

⚠ Le "12/12" historique etait mesure sur build_training_set(), c'est-a-dire
sur le jeu d'ENTRAINEMENT : il atteste la memorisation, pas la
generalisation. Une vraie mesure demande une validation groupee
(leave-one-challenge-out) et une accuracy d'abstention.
"""

# DEAD_IMPORT removed: import os
# Routeur EVENEMENTIEL de challenges CTF, pas un reseau a spikes : surrogate
# maison (`_SurrogateSpike`), aucun import snntorch. Le substrat spiking est
# `forge_snn_core`. La page 13-Hardware-Roadmap confondait les deux jusqu'au 28/08.
__FORGE_COLOR__ = "routing/spike-ctf"

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import logging

import torch
import torch.nn as nn
import torch.nn.functional as F
# DEAD_IMPORT removed: import numpy as np

logger = logging.getLogger(__name__)

STRATEGIES = [
    "ret2win",
    "ret2libc",
    "variable_overwrite",
    "format_string",
    "code_injection",
    "scanf_addr",
    "crypto_xor",
    "crypto_interactive",
    "forensics_strings",
    "ocr_images",
    "misc_interactive",
    "rev_static",
    "web_docker",
    "skip",
]
STRAT_TO_IDX = {s: i for i, s in enumerate(STRATEGIES)}


@dataclass
class ChallengeFeatures:
    has_binary: float = 0.0
    is_elf: float = 0.0
    bits_64: float = 0.0
    pie: float = 0.0
    canary: float = 0.0
    nx: float = 0.0
    has_win_fn: float = 0.0
    has_gets: float = 0.0
    has_printf_plt: float = 0.0
    has_puts_plt: float = 0.0
    has_system: float = 0.0
    has_source_c: float = 0.0
    has_source_py: float = 0.0
    has_eval_exec: float = 0.0
    has_scanf: float = 0.0
    has_dockerfile: float = 0.0
    has_server_py: float = 0.0
    has_solve_py: float = 0.0
    has_libc: float = 0.0
    has_pcap: float = 0.0
    has_images: float = 0.0
    has_enc_files: float = 0.0
    has_key_file: float = 0.0
    cat_pwn: float = 0.0
    cat_crypto: float = 0.0
    cat_rev: float = 0.0
    cat_web: float = 0.0
    cat_misc: float = 0.0
    cat_forensics: float = 0.0
    binary_size_kb: float = 0.0
    file_count: float = 0.0

    def to_tensor(self):
        return torch.tensor([getattr(self, f) for f in self.__dataclass_fields__], dtype=torch.float32)

    @staticmethod
    def dim():
        return 31


def extract_features(ch_dir, category):
    f = ChallengeFeatures()
    ch = Path(ch_dir)
    cat_map = {
        "pwn": "cat_pwn",
        "crypto": "cat_crypto",
        "rev": "cat_rev",
        "web": "cat_web",
        "misc": "cat_misc",
        "forensics": "cat_forensics",
    }
    if category in cat_map:
        setattr(f, cat_map[category], 1.0)
    try:
        f.file_count = min(len(list(ch.rglob("*"))) / 20.0, 1.0)
    except OSError as e:
        logger.debug(f"file_count indisponible pour {ch}: {e}")
    for p in ch.iterdir():
        if not p.is_file():
            continue
        nm, sx = p.name.lower(), p.suffix.lower()
        if sx in (".c", ".cpp", ".h"):
            f.has_source_c = 1.0
        if sx == ".py" and nm not in ("solve.py", "solver.py", "sol.py", "solution.py"):
            f.has_source_py = 1.0
            try:
                code = p.read_text(errors="replace")[:2000]
                if "eval(" in code or "exec(" in code:
                    f.has_eval_exec = 1.0
                if "scanf" in code:
                    f.has_scanf = 1.0
            except OSError as e:
                logger.debug(f"lecture source impossible {p}: {e}")
        if nm in ("solve.py", "solver.py", "sol.py", "solution.py"):
            f.has_solve_py = 1.0
        if nm == "dockerfile":
            f.has_dockerfile = 1.0
        if nm in ("server.py", "chall.py"):
            f.has_server_py = 1.0
        if "libc" in nm:
            f.has_libc = 1.0
        if sx in (".pcap", ".pcapng"):
            f.has_pcap = 1.0
        if sx in (".png", ".jpg", ".bmp"):
            f.has_images = 1.0
        if sx == ".enc" or "encrypted" in nm:
            f.has_enc_files = 1.0
        if "key" in nm and sx in (".txt", ".bin", ""):
            f.has_key_file = 1.0
    skip_ext = {
        ".py",
        ".c",
        ".cpp",
        ".h",
        ".json",
        ".txt",
        ".md",
        ".yml",
        ".sh",
        ".so",
        ".zip",
        ".gz",
        ".pcap",
        ".pcapng",
        ".png",
        ".jpg",
        ".pdf",
        ".hex",
    }
    skip_names = {"Makefile", "Dockerfile", "flag.txt", "README.md"}
    for p in ch.iterdir():
        if (
            p.is_file()
            and p.suffix not in skip_ext
            and p.name not in skip_names
            and not p.name.startswith(".")
            and p.stat().st_size > 500
        ):
            f.has_binary = 1.0
            f.binary_size_kb = min(p.stat().st_size / 100000.0, 1.0)
            try:
                from pwn import ELF

                e = ELF(str(p), checksec=False)
                f.is_elf = 1.0
                f.bits_64 = float(e.bits == 64)
                f.pie = float(e.pie)
                f.canary = float("__stack_chk_fail" in e.symbols)
                f.nx = float(not e.execstack)
                win = {"backdoor", "win", "print_flag", "give_shell", "cat_flag", "shell", "flag"}
                f.has_win_fn = float(bool(e.symbols.keys() & win))
                f.has_gets = float("gets" in e.symbols)
                f.has_printf_plt = float("printf" in e.plt)
                f.has_puts_plt = float("puts" in e.plt)
                f.has_system = float("system" in e.symbols)
            except Exception as exc:
                # Un binaire illisible rend un vecteur de features NEUTRE :
                # sans trace, le routeur decide sur du vide en silence.
                logger.debug(f"analyse ELF impossible {p}: {exc}")
            break
    return f


import math


class _SurrogateSpike(torch.autograd.Function):
    """Spike = Heaviside au forward ; gradient arctan lisse au backward (Neftci et al. 2019 / SpikingJelly)."""
    @staticmethod
    def forward(ctx, mem_minus_thr):
        ctx.save_for_backward(mem_minus_thr)
        return (mem_minus_thr > 0).float()

    @staticmethod
    def backward(ctx, grad_out):
        (x,) = ctx.saved_tensors
        sg = 1.0 / (1.0 + (math.pi * x) ** 2)
        return grad_out * sg


spike_fn = _SurrogateSpike.apply


class CTFSpikeRouter(nn.Module):
    def __init__(self, input_dim=31, hidden=48, num_strategies=14, threshold=0.8, leak=0.85, steps=6):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden)
        self.fc2 = nn.Linear(hidden, num_strategies)
        self.threshold = nn.Parameter(torch.tensor(threshold))
        self.leak = leak
        self.steps = steps

    def forward(self, x):
        h = F.relu(self.fc1(x))
        a = self.fc2(h)
        membrane = torch.zeros_like(a)
        spikes = torch.zeros_like(a)
        for _ in range(self.steps):
            membrane = self.leak * membrane + a
            s = spike_fn(membrane - self.threshold)
            spikes = spikes + s
            membrane = membrane * (1 - s)
        return a, spikes

    def predict(self, features):
        # TRAVAIL B (2026-07-05 / AGY) : routage sur `spikes` rendu apprenable
        # grâce au Surrogate Gradient (_SurrogateSpike / ATan) dans le forward.
        # Rétablit l'alignement parfait entre train et inférence sur le chemin SNN.
        self.eval()
        x = features.to_tensor().unsqueeze(0)
        with torch.no_grad():
            _, spikes = self(x)
            probs = F.softmax(spikes.squeeze(0), dim=-1)
            conf = probs.max().item()
            idx = probs.argmax().item()
            if conf < 0.15:
                return "skip", conf
            return STRATEGIES[idx], conf

    def predict_top_k(self, features, k=3):
        # TRAVAIL B : idem predict — top-k sur `spikes` (chemin SNN entraîné).
        self.eval()
        x = features.to_tensor().unsqueeze(0)
        with torch.no_grad():
            _, spikes = self(x)
            probs = F.softmax(spikes.squeeze(0), dim=-1)
            vals, idxs = probs.topk(min(k, len(STRATEGIES)))
            res = [
                (STRATEGIES[i.item()], round(v.item(), 3))
                for v, i in zip(vals, idxs)
                if v.item() >= 0.1
            ]
            return res if res else [("skip", 0.0)]


@dataclass
class Spike:
    type: str
    payload: str
    source: str
    severity: str


@dataclass
class SpikeResult:
    system_used: str
    response: str
    confidence: float
    # Provider reel decide par le routage. Sans ce champ, l'appelant ne
    # recuperait que l'etiquette de systeme ("ORCHESTRATOR"/"S1"), qui n'est
    # PAS un provider, et la vraie decision etait perdue.
    provider: str = ""


class SpikeRouter:
    """
    Nouveau SpikeRouter pour le routage LLM de l'Engrid.
    Branchement direct sur le modèle d'arbre de décision 'router_dt'.
    """

    def __init__(self, gate=None, orchestrator=None, ollama_url: str = ""):
        self.gate = gate
        self.orchestrator = orchestrator
        self.ollama_url = ollama_url
        try:
            from nokido_agent.app.forge_llm_router_dt import _load_or_train

            _load_or_train()
        except Exception as e:
            logger.warning(f"SpikeRouter: modele de routage indisponible: {e}")

    def route(self, spike: Spike) -> SpikeResult:
        from nokido_agent.app.forge_llm_router_dt import route_with_dt

        provider, confidence, src = route_with_dt(spike.type, spike.payload)

        # Mapping logique pour le `system_used`
        system_used = "S1"
        if provider in ["claude", "gemini", "kimi", "kimi_think", "glm5"]:
            system_used = "ORCHESTRATOR"
        elif provider == "local" or provider == "ollama":
            system_used = "S1"

        # L'Engine va ré-exploiter system_used et exécuter l'appel
        # On ne fait ici que la décision de routage pour Engrid.
        return SpikeResult(
            system_used=system_used,
            response=f"[Routed via {src} to {provider}]",
            confidence=confidence,
            provider=provider,
        )


SOLVED_TRAINING_DATA = [
    ("roppity", "pwn", "ret2libc"),
    ("baby_boi", "pwn", "ret2libc"),
    ("get_it", "pwn", "ret2win"),
    ("bigboy", "pwn", "variable_overwrite"),
    ("pilot", "pwn", "ret2win"),
    ("alien-math", "pwn", "ret2win"),
    ("got_milk", "pwn", "format_string"),
    ("my_first_pwnie", "pwn", "code_injection"),
    ("unlimited_subway", "pwn", "ret2win"),
    ("puffin", "pwn", "variable_overwrite"),
    ("Password-Checker", "pwn", "ret2win"),
    ("get_it?", "pwn", "ret2win"),
    ("target practice", "pwn", "scanf_addr"),
    ("babycrypto", "crypto", "crypto_xor"),
    ("RSA-Pop-Quiz", "crypto", "crypto_interactive"),
    ("super_curve", "crypto", "crypto_interactive"),
    ("Gotta-Decrypt", "crypto", "crypto_interactive"),
    ("lottery", "crypto", "crypto_interactive"),
    ("difib", "crypto", "crypto_interactive"),
    ("smallsurp", "crypto", "crypto_interactive"),
    ("too-much-in-common", "crypto", "crypto_interactive"),
    ("Forgery", "crypto", "crypto_interactive"),
    ("gotta-crack", "crypto", "crypto_xor"),
    ("circles", "crypto", "ocr_images"),
    ("perfect_secrecy", "crypto", "ocr_images"),
    ("tablez", "rev", "rev_static"),
    ("beleaf", "rev", "rev_static"),
    ("baby_mult", "rev", "rev_static"),
    ("prophecy", "rev", "rev_static"),
    ("rusty_road", "rev", "rev_static"),
    ("not_malware", "rev", "rev_static"),
    ("poem-collection", "web", "web_docker"),
    ("no-pass-needed", "web", "web_docker"),
    ("notmycupofcoffe", "web", "web_docker"),
    ("algebra", "misc", "misc_interactive"),
    ("bin_t", "misc", "misc_interactive"),
    ("mental-poker", "crypto", "crypto_interactive"),
    ("Lazy-Leaks", "forensics", "forensics_strings"),
]


def build_training_set():
    X, y = [], []
    for name, cat, strat in SOLVED_TRAINING_DATA:
        f = ChallengeFeatures()
        cm = {
            "pwn": "cat_pwn",
            "crypto": "cat_crypto",
            "rev": "cat_rev",
            "web": "cat_web",
            "misc": "cat_misc",
            "forensics": "cat_forensics",
        }
        setattr(f, cm.get(cat, "cat_misc"), 1.0)
        if strat == "ret2win":
            f.has_binary = 1
            f.is_elf = 1
            f.bits_64 = 1
            f.has_win_fn = 1
            f.has_gets = 1
        elif strat == "ret2libc":
            f.has_binary = 1
            f.is_elf = 1
            f.bits_64 = 1
            f.has_puts_plt = 1
            f.has_libc = 1
        elif strat == "variable_overwrite":
            f.has_binary = 1
            f.is_elf = 1
            f.bits_64 = 1
        elif strat == "format_string":
            f.has_binary = 1
            f.is_elf = 1
            f.has_printf_plt = 1
        elif strat == "code_injection":
            f.has_source_py = 1
            f.has_eval_exec = 1
        elif strat == "scanf_addr":
            f.has_binary = 1
            f.is_elf = 1
            f.has_win_fn = 1
            f.has_scanf = 1
        elif strat == "crypto_xor":
            f.has_enc_files = 1
            f.has_key_file = 1
        elif strat == "crypto_interactive":
            f.has_server_py = 1
            f.has_solve_py = 1
        elif strat == "forensics_strings":
            f.has_pcap = 1
        elif strat == "ocr_images":
            f.has_images = 1
        elif strat == "misc_interactive":
            f.has_server_py = 1
            f.has_source_py = 1
        elif strat == "rev_static":
            f.has_binary = 1
            f.is_elf = 1
            f.has_source_c = 1
        elif strat == "web_docker":
            f.has_dockerfile = 1
            f.has_server_py = 1
        X.append(f.to_tensor())
        y.append(STRAT_TO_IDX[strat])
    return torch.stack(X), torch.tensor(y, dtype=torch.long)


def train_router(epochs=100):
    X, y = build_training_set()
    router = CTFSpikeRouter()
    opt = torch.optim.Adam(router.parameters(), lr=0.01)
    router.train()
    for ep in range(epochs):
        opt.zero_grad()
        _, spikes = router(X)
        loss = F.cross_entropy(spikes, y)
        loss.backward()
        opt.step()
        if (ep + 1) % 50 == 0:
            acc = (spikes.argmax(1) == y).float().mean().item()
            print(f"  Epoch {ep + 1}/{epochs} loss={loss.item():.4f} acc={acc * 100:.1f}%")
    return router


MODEL_PATH = Path(__file__).parent.parent / "models" / "spike_router.pt"


def save_router(router):
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(router.state_dict(), str(MODEL_PATH))


def load_router():
    if not MODEL_PATH.exists():
        return None
    r = CTFSpikeRouter()
    r.load_state_dict(torch.load(str(MODEL_PATH), weights_only=True))
    r.eval()
    return r


def get_router():
    r = load_router()
    if r is None:
        print("[SpikeRouter] Training...")
        r = train_router(100)
        save_router(r)
    return r


# --- SEMANTIC INTENT PROXY EXTENSION (2026-05-01) ---
import numpy as np
import uuid

RISK_CATEGORIES = {
    "DESTRUCTIVE": [
        "supprimer un dossier",
        "effacer la base de données",
        "formater le disque",
        "delete files",
        "drop table",
        "remove directory",
        "purge logs",
    ],
    "EXPLORATORY": [
        "lister les fichiers",
        "lire la configuration",
        "chercher des secrets",
        "list directory",
        "read config",
        "scan network",
        "check environment",
    ],
    "CONFIGURATIONAL": [
        "modifier le port",
        "changer l'api key",
        "mettre à jour le système",
        "update settings",
        "change password",
        "install package",
    ],
}


def evaluate_intent(payload: dict) -> dict:
    """
    Analyse sémantique de l'intention du payload.
    Retourne un objet de négociation si le risque est élevé.
    """
    from nokido_agent.app.forge_npu_embedder import get_embed

    requested_tools = payload.get("tools", [])
    if not requested_tools:
        return {"status": "safe", "reason": "No tools requested"}

    # Extraction du texte de l'intention (noms des outils + descriptions si présentes)
    intent_text = " ".join(
        [
            f"{t.get('function', {}).get('name', t.get('name', ''))} {t.get('function', {}).get('description', '')}"
            for t in requested_tools
        ]
    )

    # Embedding de l'intention (1024 dims via NPU)
    intent_vec = get_embed([intent_text])
    if not intent_vec:
        return {"status": "error", "message": "NPU embedding failed"}

    intent_vec = np.array(intent_vec[0])

    # Comparaison sémantique avec les catégories de risque
    max_score = 0.0
    detected_category = "UNKNOWN"

    for category, examples in RISK_CATEGORIES.items():
        example_vecs = get_embed(examples)
        if not example_vecs:
            continue

        # Similitude cosinus vectorisée
        m = np.array(example_vecs)
        scores = m @ intent_vec / (np.linalg.norm(m, axis=1) * np.linalg.norm(intent_vec) + 1e-9)
        best_score = np.max(scores)

        if best_score > max_score:
            max_score = best_score
            detected_category = category

    # Seuil de négociation (Human-in-the-Loop)
    if max_score > 0.75 and detected_category == "DESTRUCTIVE":
        return {
            "status": "requires_negotiation",
            "intent_id": f"req_{uuid.uuid4().hex[:6].upper()}",
            "tool_requested": requested_tools[0].get("name", "unknown"),
            "ai_justification": f"L'action est classée comme {detected_category} (score: {max_score:.2f})",
            "risk_assessment": "high_data_loss",
            "payload": payload,
        }

    return {"status": "safe", "category": detected_category, "score": float(max_score)}


def route_challenge(ch_dir, category):
    return get_router().predict_top_k(extract_features(ch_dir, category), k=3)
