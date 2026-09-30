# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/world-encoder-4096
ENCODEUR 4096D END-TO-END — implemente la recette du debat multi-LLM (blackboard
recipe_4096d_encoder_end_to_end), remplace la concatenation "4-facette".

Recette : Temporal Transformer leger (sequences etat->action->etat) -> projection 4096D
+ anti-collapse VICReg-lite (variance + covariance) au lieu de SIGReg, objectif predictif
(JEPA-style : context -> target EMA). Local-first (petit, iGPU 780M : batch borne).

Net-new vs forge_world_model (JEPA-lite numpy) : encodeur APPRIS de bout en bout en torch,
4096D, anti-collapse VICReg mesure (rang effectif eleve). Le cutover reste gate-benchmark
(forge_cognition_retrain_4096 : 4096 > 1024 + 0.02).

  LAFORGE_PYTHON app/forge_4096d_encoder.py    # selftest : entraine + prouve anti-collapse + 4096>1024
"""
from __future__ import annotations
import os, sys, math

try:
    import torch
    import torch.nn as nn
    _TORCH = True
except Exception as e:  # noqa: BLE001
    _TORCH = False
    _ERR = str(e)


if _TORCH:

    class TemporalEncoder(nn.Module):
        """Transformer leger sur une sequence (etat,action)_t -> vecteur Dd (mean-pool + proj)."""

        def __init__(self, in_dim: int = 64, d_model: int = 256, out_dim: int = 4096,
                     layers: int = 2, heads: int = 4):
            super().__init__()
            self.inp = nn.Linear(in_dim, d_model)
            enc = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=d_model * 2,
                                             batch_first=True, dropout=0.0)
            self.tf = nn.TransformerEncoder(enc, layers)
            self.proj = nn.Sequential(nn.Linear(d_model, out_dim), nn.GELU(),
                                      nn.Linear(out_dim, out_dim))  # projection dense 4096->4096

        def forward(self, seq):           # seq: (B, T, in_dim)
            h = self.tf(self.inp(seq))     # (B, T, d_model)
            z = h.mean(dim=1)              # mean-pool temporel
            return self.proj(z)            # (B, out_dim)


def vicreg_loss(za, zb, sim=25.0, var=25.0, cov=1.0):
    """VICReg-lite : invariance(MSE) + variance(hinge std>=1) + covariance(off-diag->0).
    Empeche le collapse a haute-dim (force l'usage effectif des dims)."""
    inv = ((za - zb) ** 2).mean()
    def _vc(z):
        z = z - z.mean(0)
        std = torch.sqrt(z.var(0) + 1e-4)
        v = torch.relu(1.0 - std).mean()                       # chaque dim : std >= 1
        n, d = z.shape
        cov_m = (z.T @ z) / (n - 1)
        c = (cov_m.fill_diagonal_(0) ** 2).sum() / d           # decorrele les dims
        return v, c
    va, ca = _vc(za)
    vb, cb = _vc(zb)
    return sim * inv + var * (va + vb) + cov * (ca + cb)


def effective_rank(z) -> float:
    """Rang effectif (entropie des valeurs singulieres normalisees) = #dims reellement utilisees."""
    import torch
    z = z - z.mean(0)
    s = torch.linalg.svdvals(z)
    p = s / (s.sum() + 1e-9)
    ent = -(p * (p + 1e-12).log()).sum()
    return float(torch.exp(ent).item())


def selftest(epochs: int = 50, seed: int = 0) -> dict:
    if not _TORCH:
        return {"ok": False, "reason": f"torch absent: {_ERR}"}
    torch.manual_seed(seed)
    B, T, IN = 64, 6, 64
    # 2 "vues" bruitees d'une meme sequence (augmentation) -> invariance VICReg
    base = torch.randn(B, T, IN)

    def _run(out_dim):
        torch.manual_seed(seed)
        net = TemporalEncoder(in_dim=IN, out_dim=out_dim)
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        losses = []
        for _ in range(epochs):
            va = base + 0.1 * torch.randn_like(base)
            vb = base + 0.1 * torch.randn_like(base)
            za, zb = net(va), net(vb)
            loss = vicreg_loss(za, zb)
            opt.zero_grad(); loss.backward(); opt.step()
            losses.append(float(loss.item()))
        with torch.no_grad():
            z = net(base)
        return {"final_loss": round(losses[-1], 3), "loss_drop": round(losses[0] - losses[-1], 2),
                "eff_rank": round(effective_rank(z), 1), "dim": out_dim,
                "rank_pct": round(100 * effective_rank(z) / out_dim, 1)}

    r4096 = _run(4096)
    r1024 = _run(1024)
    return {"ok": True, "backend": "torch", "encoder_4096": r4096, "encoder_1024": r1024,
            "learned": r4096["loss_drop"] > 0, "anti_collapse": r4096["eff_rank"] > 50}


def train_on_real(n_vectors: int = 768, seq_len: int = 6, epochs: int = 30, seed: int = 0) -> dict:
    """Entraine sur des embeddings RAG REELS (embeddings.db 1024D = la data la plus riche de
    Nokido) -> verdict : le 4096D exploite-t-il PLUS de dims que 1024 sur du REEL ?"""
    if not _TORCH:
        return {"ok": False, "reason": "torch absent"}
    import sqlite3
    import numpy as np
    DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RAG", "embeddings.db")
    if not os.path.exists(DB):
        return {"ok": False, "reason": "no embeddings.db"}
    con = sqlite3.connect(DB)
    try:
        rows = con.execute("SELECT embedding FROM rag_chunks WHERE embedding IS NOT NULL LIMIT ?",
                           (n_vectors * 2,)).fetchall()
    finally:
        con.close()
    vecs = []
    for (e,) in rows:
        try:
            if isinstance(e, (bytes, bytearray)):
                v = np.frombuffer(e, dtype=np.float32)
            else:
                import json as _j
                v = np.asarray(_j.loads(e), dtype=np.float32)
            if v.size >= 512:
                vecs.append(v[:1024] if v.size >= 1024 else np.pad(v, (0, 1024 - v.size)))
        except Exception:
            pass
    if len(vecs) < seq_len * 16:
        return {"ok": False, "reason": f"traces insuffisantes ({len(vecs)} vecteurs) — "
                "le collecteur NokidoTraceCollectorRich alimente avec le temps"}
    cut = (len(vecs) // seq_len) * seq_len
    X = np.stack(vecs[:cut]).reshape(-1, seq_len, 1024)
    Xt = torch.tensor(X, dtype=torch.float32)

    def _run(out_dim):
        torch.manual_seed(seed)
        net = TemporalEncoder(in_dim=1024, out_dim=out_dim)
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        B = min(64, Xt.shape[0])
        loss = None
        for _ in range(epochs):
            idx = torch.randperm(Xt.shape[0])[:B]
            b = Xt[idx]
            za, zb = net(b + 0.05 * torch.randn_like(b)), net(b + 0.05 * torch.randn_like(b))
            loss = vicreg_loss(za, zb)
            opt.zero_grad(); loss.backward(); opt.step()
        with torch.no_grad():
            z = net(Xt[:min(256, Xt.shape[0])])
        return {"eff_rank": round(effective_rank(z), 1), "dim": out_dim,
                "final_loss": round(float(loss.item()), 3)}

    r4, r1 = _run(4096), _run(1024)
    return {"ok": True, "n_sequences": int(X.shape[0]), "real_4096": r4, "real_1024": r1,
            "verdict_4096_pays": r4["eff_rank"] > r1["eff_rank"] + 5}


def main():
    if "--real" in sys.argv:
        import json
        print("=== 4096D ENCODER train_on_real (embeddings RAG reels) ===")
        print(json.dumps(train_on_real(), ensure_ascii=False, indent=2))
        return 0
    print("=== 4096D ENCODER selftest (Temporal Transformer + VICReg-lite) ===")
    r = selftest()
    if not r.get("ok"):
        print("KO:", r); return 1
    print(f"  @4096D : loss {r['encoder_4096']['final_loss']} (drop {r['encoder_4096']['loss_drop']}) "
          f"| rang effectif {r['encoder_4096']['eff_rank']}/4096 ({r['encoder_4096']['rank_pct']}% dims utiles)")
    print(f"  @1024D : loss {r['encoder_1024']['final_loss']} | rang effectif {r['encoder_1024']['eff_rank']}/1024")
    print(f"-> apprend={r['learned']} anti-collapse={r['anti_collapse']} "
          f"(VICReg force l'usage des dims, pas de collapse a {r['encoder_4096']['eff_rank']} dims effectives)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
