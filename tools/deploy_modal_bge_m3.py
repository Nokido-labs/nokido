"""Deploy BGE-M3 sur Modal serverless A10G GPU.

Pre-requis :
    pip install modal
    modal token new  # auth Modal compte free tier
    modal deploy tools/deploy_modal_bge_m3.py

Endpoint genere : https://<user>--bge-m3-embed.modal.run
Configurer ensuite :
    setx LAFORGE_MODAL_EMBED_URL "https://<user>--bge-m3-embed.modal.run"

Cout, CHIFFRE DU COMPTE REEL (owner, 2026-09-06) : le quota mensuel de CE workspace est
de **5 $**, pas 30 -- il en restait 0,07 $ ce mois-ci, ce qui explique le
`404 workspace ... is disabled` au serving alors que le CLI et le deploiement passent.
5 $ ~ 4,5 h d'A10G (1,10 $/h GPU seul, CPU et RAM en plus). Au debit MESURE le 2026-08-19
(23,4 chunks/s), cela vaut de l'ordre de 250 000 a 350 000 chunks par mois -- assez pour
le backlog entier, a condition que `min_containers` reste a 0 : 4 conteneurs permanents
consomment 4,40 $/h, soit tout le quota en une heure et quart.

Architecture : @modal.fastapi_endpoint DANS la cls = 1 container, 1 hop
(vs function endpoint + cls = 2 containers + cross-RPC = 4s+ warm latency).
"""

import os

import modal

app = modal.App("bge-m3-embed")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        [
            "sentence-transformers==3.3.1",
            "torch==2.5.1",
            "FlagEmbedding==1.3.3",
            "fastapi[standard]",
        ]
    )
    .run_commands(
        [
            "python -c \"from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)\""
        ]
    )
)


@app.cls(
    image=image,
    gpu="A10G",
    scaledown_window=600,
    timeout=120,
    # 0 par defaut (2026-09-06) : 4 A10G permanentes = 4 x 1,10 $/h GPU seul = les 30 $
    # de credits mensuels consommes en ~6,8 h de temps mural, campagne ou pas. Une
    # campagne de rattrapage se deploie avec MODAL_MIN_CONTAINERS=4 dans l'env du
    # `modal deploy`, puis se REDEPLOIE a 0 (ou `modal app stop bge-m3-embed`).
    min_containers=int(os.environ.get("MODAL_MIN_CONTAINERS", "0")),
)
class BgeM3Embedder:
    @modal.enter()
    def load_model(self):
        from FlagEmbedding import BGEM3FlagModel

        self.model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

    @modal.method()
    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self.model.encode(
            texts,
            batch_size=32,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense = out["dense_vecs"]
        return dense.tolist() if hasattr(dense, "tolist") else dense

    @modal.fastapi_endpoint(method="POST", label="bge-m3-embed")
    def embed_http(self, payload: dict) -> dict:
        texts = payload.get("texts") or [payload.get("text", "")]
        if not any(t for t in texts):
            return {"error": "empty input"}
        out = self.model.encode(
            texts,
            batch_size=64,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense = out["dense_vecs"]
        emb = dense.tolist() if hasattr(dense, "tolist") else dense
        return {"embeddings": emb, "model": "BAAI/bge-m3", "dim": 1024}


if __name__ == "__main__":
    print("Run: modal deploy tools/deploy_modal_bge_m3.py")
    print("Then: modal app list  # for endpoint URL")
