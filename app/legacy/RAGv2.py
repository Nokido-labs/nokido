import pymupdf4llm
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import MarkdownHeaderTextSplitter
from langchain.retrievers import EnsembleRetriever
from langchain_huggingface import HuggingFaceEmbeddings


# --- ÉTAPE 1 : QUALIFICATION PROFONDE ---
def build_hybrid_rag(pdf_path):
    # Extraction Markdown pour ne pas casser les commandes info
    md_content = pymupdf4llm.to_markdown(pdf_path)

    # Split intelligent par sections (Headers)
    headers_to_split_on = [("#", "H1"), ("##", "H2"), ("###", "H3")]
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    documents = splitter.split_text(md_content)

    # --- ÉTAPE 2 : DOUBLE INDEXATION ---
    # 1. Vecteurs (FAISS) pour le sens
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    faiss_db = FAISS.from_documents(documents, embeddings)
    faiss_retriever = faiss_db.as_retriever(search_kwargs={"k": 3})

    # 2. Mots-clés (BM25) pour les commandes exactes
    bm25_retriever = BM25Retriever.from_documents(documents)
    bm25_retriever.k = 3

    # --- ÉTAPE 3 : HYBRID SEARCH (Ensemble) ---
    # On donne 50% de poids à chaque méthode
    ensemble_retriever = EnsembleRetriever(retrievers=[bm25_retriever, faiss_retriever], weights=[0.5, 0.5])
    return ensemble_retriever


# --- ÉTAPE 4 : INFÉRENCE SUR NPU/iGPU ---
# Assure-toi d'avoir installé : pip install onnxruntime-directml
import onnxruntime as ort


def query_npu(prompt, retriever):
    # Récupération des données qualifiées
    context_docs = retriever.invoke(prompt)
    context_text = "\n---\n".join([d.page_content for d in context_docs])

    # Ici, tu appelles ton modèle Phi-3.5 ONNX
    # IMPORTANT : Vérifie que le provider est 'DmlExecutionProvider' pour le Ryzen
    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession("phi3.5_mini_int4.onnx", providers=providers)

    # ... suite de ta logique d'inférence ...
    return context_text  # (Le contexte prêt pour le LLM)
