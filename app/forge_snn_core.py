# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = neuro/snn-substrate
SNN CORE — couche LIF canonique APPRENABLE (surrogate gradient).

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  Le substrat LIF REEL existe deja, mais en INFERENCE A POIDS FIXES, dupplique :
    - forge_snn_monitor.SNNMonitor = 3 neurones LIF (RAM/CPU/GPU), spike->adrenaline.
    - forge_spike_router.CTFSpikeRouter = SNN torch (threshold/leak/steps) routage CTF.
  Ni l'un ni l'autre n'APPREND (pas de backward a travers le spike non-differentiable).
  Ce module comble la capacite manquante : un LIF CANONIQUE entrainable par
  SURROGATE GRADIENT (le spike, marche d'escalier non-derivable, recoit un gradient
  de substitution lisse au backward). C'est le saut metaphore/inference -> substrat
  spiking APPRENANT. Reutilisable : SNNMonitor/CTFSpikeRouter pourront s'y refactorer.

snntorch utilise si installe (Leaky + fast_sigmoid), sinon implementation pur-torch
integree (zero dep, torch suffit). 0 cloud.

  LAFORGE_PYTHON app/forge_snn_core.py    # selftest : entraine un SNN, prouve l'apprentissage
"""
from __future__ import annotations
import sys, math

try:
    import torch
    import torch.nn as nn
    _TORCH = True
except Exception as e:  # noqa: BLE001
    _TORCH = False
    _TORCH_ERR = str(e)

# snntorch en option (vehicule canonique si present)
try:
    import snntorch as snn  # noqa: F401
    from snntorch import surrogate as _snn_surrogate  # noqa: F401
    _HAS_SNNTORCH = True
except Exception:
    _HAS_SNNTORCH = False


if _TORCH:

    class _SurrogateSpike(torch.autograd.Function):
        """Spike = Heaviside au forward ; gradient arctan lisse au backward.
        d/dx (1/pi * atan(pi*x)) = 1/(1+(pi*x)^2). Standard (Neftci et al. 2019)."""

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

    class LIFCell(nn.Module):
        """Leaky-Integrate-and-Fire differentiable : mem = beta*mem + I ; spike si
        mem>thr ; reset soustractif. beta = retention membranaire (leak = 1-beta)."""

        def __init__(self, beta: float = 0.9, threshold: float = 1.0):
            super().__init__()
            self.beta = beta
            self.threshold = threshold

        def forward(self, x, mem):
            mem = self.beta * mem + x
            spk = spike_fn(mem - self.threshold)
            mem = mem - spk * self.threshold  # reset soustractif (garde le residu)
            return spk, mem

    class SpikingMLP(nn.Module):
        """SNN 2 couches deroule sur T pas. Entree rate-codee, readout = somme des
        spikes de sortie (taux). Entrainable de bout en bout (surrogate)."""

        def __init__(self, in_dim, hidden, out_dim, steps: int = 25,
                     beta: float = 0.9, backend: str | None = None):
            """backend : None = auto (snntorch si present), "snntorch", "builtin".

            POURQUOI ce parametre (mesure du 2026-08-21) : les deux backends
            n'ont PAS le meme state_dict. snn.Leaky porte des parametres
            (threshold, beta, graded_spikes_factor, reset_mechanism_val) que
            LIFCell n'a pas. Un modele entrainee sous un interpreteur SANS
            snntorch ne se recharge donc pas sous un interpreteur AVEC, et
            reciproquement -- constate en production : le modele ecrit par
            trusted_script refusait de se charger cote sandbox.
            En mode auto, la STRUCTURE DU RESEAU depend d'un import optionnel :
            c'est une dependance invisible. Qui persiste des poids doit fixer
            le backend explicitement et le stocker avec eux.
            """
            super().__init__()
            self.fc1 = nn.Linear(in_dim, hidden)
            self.fc2 = nn.Linear(hidden, out_dim)
            self.steps = steps
            if backend is None:
                backend = "snntorch" if _HAS_SNNTORCH else "builtin"
            if backend == "snntorch" and not _HAS_SNNTORCH:
                raise RuntimeError("backend 'snntorch' demande mais snntorch absent")
            if backend not in ("snntorch", "builtin"):
                raise ValueError(f"backend inconnu: {backend!r}")
            self.backend = backend
            if backend == "snntorch":  # backend lib reel (Leaky + fast_sigmoid)
                self.lif1 = snn.Leaky(beta=beta, spike_grad=_snn_surrogate.fast_sigmoid())
                self.lif2 = snn.Leaky(beta=beta, spike_grad=_snn_surrogate.fast_sigmoid())
            else:                # implementation pur-torch integree (zero dep)
                self.lif1 = LIFCell(beta)
                self.lif2 = LIFCell(beta)

        def forward(self, x_rate):
            # x_rate: (B, in_dim) probas de spike par pas ; on echantillonne T fois
            B = x_rate.shape[0]
            mem1 = torch.zeros(B, self.fc1.out_features)
            mem2 = torch.zeros(B, self.fc2.out_features)
            out_sum = torch.zeros(B, self.fc2.out_features)
            spk_count = 0.0
            for _ in range(self.steps):
                xt = (torch.rand_like(x_rate) < x_rate).float()  # encodage de Poisson
                cur1 = self.fc1(xt)
                spk1, mem1 = self.lif1(cur1, mem1)
                cur2 = self.fc2(spk1)
                spk2, mem2 = self.lif2(cur2, mem2)
                out_sum = out_sum + spk2
                spk_count += float(spk1.sum().item() + spk2.sum().item())
            return out_sum / self.steps, spk_count


def available() -> dict:
    """Trois etats, jamais deux : present / absent / illisible.

    Mesure 2026-08-04 : sous le sandbox du hub, `import torch` echoue non pas
    parce que torch manque, mais parce que `dill` (dependance de
    torch.utils.data) fait `open(os.devnull)` a l'import et que WORKSPACE_GUARD
    refuse `nul` comme ecriture hors zone. torch 2.11.0+cpu est INSTALLE et
    fonctionne des qu'on sort de ce contexte (verifie : le selftest apprend,
    acc 0.848 -> 1.0).

    Rendre un simple `False` confond « pas la » et « pas pu regarder ». Ce faux
    negatif a fait conclure a un agent que Nokido n'avait pas de substrat
    spiking exploitable, et a oriente tout un plan sur cette base. `torch` reste
    un booleen pour ne pas casser les lecteurs existants ; `torch_etat` porte la
    distinction que le booleen ne peut pas exprimer.
    """
    if _TORCH:
        etat = "present"
    elif _TORCH_ERR and "WORKSPACE_GUARD" in str(_TORCH_ERR):
        etat = "illisible_garde_sandbox"
    else:
        etat = "absent"
    return {"torch": _TORCH, "snntorch": _HAS_SNNTORCH,
            "torch_err": None if _TORCH else _TORCH_ERR,
            "torch_etat": etat}


def selftest(epochs: int = 60, seed: int = 0) -> dict:
    """Entraine un SNN a separer 2 blobs gaussiens rate-codes. Prouve : (a) des
    spikes sont generes (substrat reel), (b) l'accuracy MONTE (apprentissage par
    surrogate gradient). Retourne les metriques."""
    if not _TORCH:
        return {"ok": False, "reason": f"torch absent: {_TORCH_ERR}"}
    torch.manual_seed(seed)
    in_dim, hidden, out_dim, N = 8, 24, 2, 128
    # 2 classes : centroides opposes -> rate-codes dans [0,1]
    c0 = torch.full((in_dim,), 0.25)
    c1 = torch.full((in_dim,), 0.75)
    x0 = (c0 + 0.08 * torch.randn(N, in_dim)).clamp(0, 1)
    x1 = (c1 + 0.08 * torch.randn(N, in_dim)).clamp(0, 1)
    X = torch.cat([x0, x1]); Y = torch.cat([torch.zeros(N), torch.ones(N)]).long()

    net = SpikingMLP(in_dim, hidden, out_dim)
    opt = torch.optim.Adam(net.parameters(), lr=0.01)
    lossf = nn.CrossEntropyLoss()

    def accuracy():
        with torch.no_grad():
            out, _ = net(X)
            return float((out.argmax(1) == Y).float().mean().item())

    acc0 = accuracy()
    last_spikes = 0.0
    for _ in range(epochs):
        opt.zero_grad()
        out, last_spikes = net(X)
        loss = lossf(out, Y)
        loss.backward()
        opt.step()
    acc1 = accuracy()
    return {"ok": True, "backend": "snntorch" if _HAS_SNNTORCH else "builtin-lif",
            "acc_before": round(acc0, 3), "acc_after": round(acc1, 3),
            "final_loss": round(float(loss.item()), 4),
            "spikes_last_pass": int(last_spikes),
            "learned": acc1 > acc0 + 0.1}


def main():
    av = available()
    print("=== SNN CORE selftest ===")
    print("available:", av)
    r = selftest()
    print("result:", r)
    if r.get("ok"):
        verdict = "APPREND (substrat spiking entrainable)" if r["learned"] else "pas de gain (revoir hyperparams)"
        print(f"-> {verdict} : acc {r['acc_before']} -> {r['acc_after']}, spikes={r['spikes_last_pass']}, backend={r['backend']}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
