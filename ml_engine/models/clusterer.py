"""3.3 NLP & clustering — detect recurring root causes from French ticket text.

Pipeline:
  1. Preprocess with spaCy `fr_core_news_sm` (lemmatise, drop stopwords/punct).
     Falls back to a light regex tokenizer if spaCy/model is unavailable.
  2. Embed with sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`
     (chosen over CamemBERT: French-capable, ~470MB, CPU-friendly, one-line
     encode). Model is cached under `MLConfig.model_cache_dir`. Falls back to
     TF-IDF vectors if sentence-transformers is unavailable.
  3. Cluster: DBSCAN on embeddings (dense clusters = recurring issues); K-Means
     (k in config) as a category-agnostic fallback for the top-N view.
  4. Per cluster: sample_titles (5 representative), ticket_count, top_keywords
     (TF-IDF top 10), severity_label from ticket_count thresholds.
  5. Sentiment: lightweight lexicon classifier flags frustrated users.

Interface: train(df) / predict(model, df) / evaluate(model, df).
"train" fits DBSCAN/KMeans on the corpus embeddings and returns a bundle that
predict() reuses; because clustering is transductive, predict() re-derives
clusters from the fitted labels.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from ..features import build_text_corpus

logger = logging.getLogger(__name__)

REGISTERED_MODEL_NAME = "glpi_clusterer"

SEVERITY_THRESHOLDS = (  # (min_count, label) — first match from top wins
    (100, "CRITIQUE"),
    (50, "ÉLEVÉ"),
    (20, "MODÉRÉ"),
    (0, "FAIBLE"),
)

# Small French sentiment lexicon (enough for positive/neutral/negative flags).
_NEG_WORDS = {
    "bloqué", "bloque", "impossible", "urgent", "panne", "erreur", "plante",
    "planté", "cassé", "casse", "inacceptable", "insupportable", "lent", "lente",
    "toujours", "encore", "jamais", "problème", "probleme", "grave", "critique",
    "mécontent", "frustré", "frustre", "colère", "colere", "nul", "catastrophe",
}
_POS_WORDS = {
    "merci", "parfait", "résolu", "resolu", "super", "excellent", "rapide",
    "bien", "content", "satisfait", "ok", "génial", "genial", "top",
}

_TOKEN_RE = re.compile(r"[a-zàâäéèêëïîôöùûüç]{3,}", flags=re.IGNORECASE)
_BASIC_STOPWORDS = {
    "les", "des", "une", "pour", "avec", "dans", "sur", "que", "qui", "pas",
    "est", "sont", "the", "and", "bonjour", "cordialement", "merci",
}


def severity_for_count(count: int) -> str:
    for threshold, label in SEVERITY_THRESHOLDS:
        if count >= threshold:
            return label
    return "FAIBLE"


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _load_spacy(model_name: str):
    try:
        import spacy

        return spacy.load(model_name, disable=["parser", "ner"])
    except Exception as exc:
        logger.warning("spaCy model '%s' unavailable (%s); using regex fallback", model_name, exc)
        return None


def preprocess_texts(texts: list[str], *, spacy_model: str = "fr_core_news_sm") -> list[str]:
    nlp = _load_spacy(spacy_model)
    if nlp is None:
        out = []
        for t in texts:
            toks = [w.lower() for w in _TOKEN_RE.findall(t or "")]
            out.append(" ".join(w for w in toks if w not in _BASIC_STOPWORDS))
        return out
    cleaned = []
    for doc in nlp.pipe([t or "" for t in texts], batch_size=64):
        lemmas = [
            tok.lemma_.lower()
            for tok in doc
            if not tok.is_stop and not tok.is_punct and not tok.is_space and len(tok.lemma_) >= 3
        ]
        cleaned.append(" ".join(lemmas))
    return cleaned


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _load_embedder(model_name: str, cache_dir: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, cache_folder=cache_dir)


def embed_texts(texts: list[str], config: Any) -> tuple[np.ndarray, str]:
    """Return (embeddings, backend). Falls back to TF-IDF when
    sentence-transformers is unavailable."""
    if not texts:
        return np.zeros((0, 1)), "empty"
    try:
        model = _load_embedder(config.embedding_model, config.model_cache_dir)
        emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(emb, dtype=float), "sentence-transformers"
    except Exception as exc:
        logger.warning("embeddings via sentence-transformers failed (%s); TF-IDF fallback", exc)
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(max_features=512)
        mat = vec.fit_transform(texts).toarray()
        # L2 normalise so cosine ~= euclidean for DBSCAN eps.
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms, "tfidf"


# --------------------------------------------------------------------------- #
# Sentiment
# --------------------------------------------------------------------------- #
def sentiment_label(text: str) -> str:
    toks = set(_TOKEN_RE.findall((text or "").lower()))
    neg = len(toks & _NEG_WORDS)
    pos = len(toks & _POS_WORDS)
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


# --------------------------------------------------------------------------- #
# Keywords
# --------------------------------------------------------------------------- #
def top_keywords(cleaned_texts: list[str], top_n: int = 10) -> list[str]:
    if not any(cleaned_texts):
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        vec = TfidfVectorizer(max_features=200)
        mat = vec.fit_transform(cleaned_texts)
    except ValueError:
        return []
    scores = np.asarray(mat.mean(axis=0)).ravel()
    terms = np.array(vec.get_feature_names_out())
    order = scores.argsort()[::-1][:top_n]
    return terms[order].tolist()


@dataclass
class ClusterModel:
    algorithm: str
    labels: np.ndarray
    corpus: pd.DataFrame              # id, text, cleaned, date, ...
    backend: str
    config: Any
    extra: dict = field(default_factory=dict)


def train(df: pd.DataFrame, *, config: Any | None = None, algorithm: str = "dbscan") -> ClusterModel | None:
    from ..config import MLConfig

    cfg = config or MLConfig.from_env()
    corpus = build_text_corpus(df)
    if corpus.empty:
        logger.warning("clusterer.train: empty corpus")
        return None

    cleaned = preprocess_texts(corpus["text"].tolist(), spacy_model=cfg.spacy_model)
    corpus = corpus.assign(cleaned=cleaned)
    emb, backend = embed_texts(cleaned, cfg)

    if algorithm == "kmeans":
        from sklearn.cluster import KMeans

        k = min(cfg.kmeans_k, max(2, len(corpus)))
        labels = KMeans(n_clusters=k, random_state=cfg.random_state, n_init=10).fit_predict(emb)
    else:
        from sklearn.cluster import DBSCAN

        labels = DBSCAN(
            eps=cfg.dbscan_eps, min_samples=cfg.dbscan_min_samples, metric="euclidean"
        ).fit_predict(emb)

    logger.info(
        "clusterer.train: %s -> %d clusters (backend=%s)",
        algorithm,
        len(set(labels)) - (1 if -1 in labels else 0),
        backend,
    )
    return ClusterModel(algorithm, np.asarray(labels), corpus, backend, cfg)


def predict(model: ClusterModel, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Summarise clusters. Returns one row per cluster with the spec's columns.

    Because DBSCAN/KMeans are transductive, we summarise the fitted corpus; `df`
    is accepted for interface uniformity but not required.
    """
    cols = [
        "cluster_id", "algorithm", "sample_titles", "ticket_count",
        "top_keywords", "severity", "first_seen", "last_seen", "neg_ratio",
    ]
    if model is None or model.corpus.empty:
        return pd.DataFrame(columns=cols)

    corpus = model.corpus.assign(_label=model.labels)
    rows = []
    for label, g in corpus.groupby("_label"):
        if label == -1:  # DBSCAN noise
            continue
        titles = g["text"].head(5).str.slice(0, 120).tolist()
        dates = pd.to_datetime(g["date"], errors="coerce").dropna()
        neg = g["text"].map(sentiment_label).eq("negative").mean()
        rows.append(
            {
                "cluster_id": int(label),
                "algorithm": model.algorithm,
                "sample_titles": titles,
                "ticket_count": int(len(g)),
                "top_keywords": top_keywords(g["cleaned"].tolist()),
                "severity": severity_for_count(len(g)),
                "first_seen": dates.min() if not dates.empty else None,
                "last_seen": dates.max() if not dates.empty else None,
                "neg_ratio": round(float(neg), 3),
            }
        )
    out = pd.DataFrame(rows, columns=cols).sort_values("ticket_count", ascending=False)
    logger.info("clusterer.predict: %d clusters summarised", len(out))
    return out.reset_index(drop=True)


def evaluate(model: ClusterModel, df: pd.DataFrame | None = None) -> dict[str, float]:
    """Silhouette score over non-noise points (needs >=2 clusters)."""
    if model is None or model.corpus.empty:
        return {"silhouette": 0.0, "n_clusters": 0.0, "noise_ratio": 0.0}
    labels = model.labels
    mask = labels != -1
    n_clusters = len(set(labels[mask])) if mask.any() else 0
    noise_ratio = float((labels == -1).mean())
    if n_clusters < 2 or mask.sum() < 3:
        return {"silhouette": 0.0, "n_clusters": float(n_clusters), "noise_ratio": noise_ratio}
    cleaned = model.corpus["cleaned"].tolist()
    emb, _ = embed_texts(cleaned, model.config)

    from sklearn.metrics import silhouette_score

    try:
        sil = float(silhouette_score(emb[mask], labels[mask]))
    except Exception:
        sil = 0.0
    return {"silhouette": sil, "n_clusters": float(n_clusters), "noise_ratio": noise_ratio}
