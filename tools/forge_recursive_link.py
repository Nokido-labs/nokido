# -*- coding: utf-8 -*-
"""forge_recursive_link.py — runtime SOUVERAIN du RecursiveLink (RecursiveMAS Path 1).

INTERNALISE la logique prouvee de sandbox/workspace/recursivemas_pipeline.py (verdict
GAIN NET -60% tokens d'input, cos_id 0.6375) dans le tool-tree TRACKE : charge le link+LoRA
entraine (recursive_link_v1.pt, sortie Kaggle P3) sur Qwen2.5-0.5B et expose le HOP LATENT
(texte -> K=8 soft-vecteurs -> generation via inputs_embeds) pour que deux agents self-model
echangent SANS re-tokeniser le tour precedent (economie d'input).

IMPORT-SAFE : torch / transformers / peft sont importes PARESSEUSEMENT dans load() — sinon
l'import inline via le hub tape WORKSPACE_GUARD. Importer ce module ne charge donc RIEN de
lourd ; le modele n'est construit qu'au 1er hop latent (singleton, reutilise ensuite).

Archi MIROIR de recursivelink_p3.py / recursivemas_pipeline.py — NE PAS diverger, sinon le
checkpoint ne charge pas (link.load_state_dict + set_peft_model_state_dict strict).
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/reasoning : runtime souverain du RecursiveLink (RecursiveMAS)"  # organe declare le 2026-09-06 (audit de raccordement)

import importlib.util
import os

# --- Paths souverains (pas d'import lourd ici) --------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)                                   # ~/Script python IA/LaForge
_WS = os.path.join(ROOT, "sandbox", "workspace")

MODEL = os.environ.get("RMAS_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
CKPT = os.environ.get("RMAS_CKPT", os.path.join(_WS, "recursive_link_v1.pt"))
K = int(os.environ.get("RMAS_K", 8))
R = int(os.environ.get("RMAS_R", 8))
ALPHA = int(os.environ.get("RMAS_ALPHA", 16))
PREFIX = "Reponds au message latent de ton interlocuteur :"

# HF cache -> zone agent-inscriptible (reutilise le cache ~1GB deja peuple par le harness ;
# le job detache a USERPROFILE=C:\\Users\\Default -> .cache non-writable). DOIT preceder
# tout import transformers/torch (fait dans load()).
_HFC = os.path.join(_WS, "hf_cache")
try:
    os.makedirs(_HFC, exist_ok=True)
except Exception:  # noqa: BLE001
    _HFC = None
if _HFC:
    for _k in ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
               "SENTENCE_TRANSFORMERS_HOME", "XDG_CACHE_HOME"):
        os.environ.setdefault(_k, _HFC)

_STATE = None   # singleton charge (dict) apres load()


def is_available() -> bool:
    """True si le hop latent est jouable ICI : deps torch/transformers/peft presentes ET
    checkpoint present. Ne charge RIEN (find_spec seul) — safe a appeler avant tout hop."""
    if not os.path.isfile(CKPT):
        return False
    for mod in ("torch", "transformers", "peft"):
        if importlib.util.find_spec(mod) is None:
            return False
    return True


def why_unavailable() -> str:
    """Diagnostic court (pour logguer la raison d'un fallback texte)."""
    if not os.path.isfile(CKPT):
        return f"checkpoint absent: {CKPT}"
    miss = [m for m in ("torch", "transformers", "peft")
            if importlib.util.find_spec(m) is None]
    return ("deps manquantes: " + ",".join(miss)) if miss else "ok"


def load():
    """Construit le modele Qwen-0.5B + link + LoRA a partir du checkpoint (MIROIR P3).
    Idempotent : le 1er appel charge (lent, ~1er download HF si cache froid), les suivants
    renvoient le singleton. Leve RuntimeError si indisponible."""
    global _STATE
    if _STATE is not None:
        return _STATE
    if not is_available():
        raise RuntimeError(f"RecursiveLink indisponible: {why_unavailable()}")

    import torch
    import torch.nn as nn
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(MODEL)
    base = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float32).to(dev)
    lcfg = LoraConfig(r=R, lora_alpha=ALPHA, lora_dropout=0.1, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(base, lcfg)
    d = model.config.hidden_size
    emb = model.get_input_embeddings()
    emb_rms = emb.weight.detach().float().pow(2).mean().sqrt().item()
    link = nn.Sequential(nn.Linear(d, d * 2), nn.GELU(), nn.Dropout(0.1),
                         nn.Linear(d * 2, d)).to(dev)

    ck = torch.load(CKPT, map_location=dev)
    link.load_state_dict({k: v.to(dev) for k, v in ck["link"].items()})
    set_peft_model_state_dict(model, {k: v.to(dev) for k, v in ck["lora"].items()})
    model.eval()
    link.eval()

    pref_ids = tok(PREFIX, return_tensors="pt").input_ids.to(dev)
    _STATE = {
        "torch": torch, "tok": tok, "model": model, "link": link, "emb": emb,
        "dev": dev, "d": d, "emb_rms": emb_rms,
        "pref_ids": pref_ids, "pref_len": int(pref_ids.shape[1]),
    }
    return _STATE


def _rms_norm(x, eps=1e-5):
    return x / (x.pow(2).mean(-1, keepdim=True).sqrt() + eps)


def _encode_latent(st, s: str):
    torch = st["torch"]
    tok, model = st["tok"], st["model"]
    with torch.no_grad():
        ids = tok(s, return_tensors="pt", truncation=True, max_length=160).input_ids.to(st["dev"])
        with model.disable_adapter():
            h = model(ids, output_hidden_states=True).hidden_states[-1][0]
        if h.shape[0] >= K:
            h = torch.stack([c.mean(0) for c in torch.chunk(h, K, 0)])
    return h


def _make_soft(st, h):
    torch = st["torch"]
    with torch.no_grad():
        return _rms_norm(st["link"](_rms_norm(h))) * st["emb_rms"]


def latent_hop(prev_text: str, role: str = "", max_new: int = 90):
    """HOP LATENT : encode prev_text -> K=8 soft-vecteurs ; l'agent lit PREFIX+K (+ role
    optionnel prepend, quelques tokens) via inputs_embeds et genere sa reponse. Le tour
    precedent n'est PAS re-tokenise -> input court. Renvoie (texte, n_input_tokens)."""
    st = load()
    torch, tok, model, emb = st["torch"], st["tok"], st["model"], st["emb"]
    with torch.no_grad():
        soft = _make_soft(st, _encode_latent(st, prev_text))            # (K, d)
        parts, role_len = [], 0
        if role:
            role_ids = tok(role[:260], return_tensors="pt", truncation=True,
                           max_length=64).input_ids.to(st["dev"])
            role_len = int(role_ids.shape[1])
            parts.append(emb(role_ids)[0])
        parts.append(emb(st["pref_ids"])[0])
        parts.append(soft)
        inp = torch.cat(parts, 0).unsqueeze(0)                          # (1, role+PREF+K, d)
        out = model.generate(inputs_embeds=inp, max_new_tokens=max_new, do_sample=False,
                             pad_token_id=tok.eos_token_id)
        txt = tok.decode(out[0], skip_special_tokens=True).strip()
    return (txt or "[latent: sortie vide]"), role_len + st["pref_len"] + int(soft.shape[0])


def text_hop(prev_text: str, role: str = "", max_new: int = 90):
    """BASELINE (comparaison) : hop TEXTE — l'agent lit role+PREFIX+prev_text re-tokenise en
    ENTIER via input_ids (modele base). Renvoie (texte, n_input_tokens)."""
    st = load()
    torch, tok, model = st["torch"], st["tok"], st["model"]
    with torch.no_grad():
        prompt = ((role[:220] + "\n") if role else "") + PREFIX + " " + prev_text
        ids = tok(prompt, return_tensors="pt", truncation=True, max_length=320).input_ids.to(st["dev"])
        with model.disable_adapter():
            out = model.generate(input_ids=ids, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.eos_token_id)
        txt = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
    return (txt or "[texte: sortie vide]"), int(ids.shape[1])


def text_input_tokens(prev_text: str, role: str = "") -> int:
    """Nombre de tokens d'INPUT du baseline TEXTE (role+PREFIX+prev re-tokenise en entier),
    SANS generer — pour chiffrer l'economie du hop latent a cout nul."""
    st = load()
    tok = st["tok"]
    prompt = ((role[:220] + "\n") if role else "") + PREFIX + " " + prev_text
    return int(len(tok(prompt, truncation=True, max_length=320).input_ids))


def gen_text(prompt: str, role: str = "", max_new: int = 140):
    """Generation self-model normale (modele base, format chat) — bootstrap du 1er tour et
    synthese en mode latent (100% local, zero cloud). Renvoie le texte."""
    st = load()
    torch, tok, model = st["torch"], st["tok"], st["model"]
    with torch.no_grad():
        msgs = [{"role": "system", "content": role or "Tu es un participant de debat concis."},
                {"role": "user", "content": prompt}]
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt")
        ids = (enc["input_ids"] if hasattr(enc, "input_ids") else enc).to(st["dev"])
        with model.disable_adapter():
            out = model.generate(input_ids=ids, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.eos_token_id)
        txt = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()
    return txt or "[self-model: sortie vide]"
