from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable, List

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_VECTOR_SIZE = 384


@lru_cache(maxsize=2)
def _load_model(model_name: str) -> SentenceTransformer:
    logger.info("Loading embedding model: %s", model_name)
    return SentenceTransformer(model_name)


class EmbeddingModel:
    def __init__(self, *, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self._model_name = model_name
        self._model = _load_model(model_name)
        dimension = int(self._model.get_sentence_embedding_dimension())
        if dimension != DEFAULT_VECTOR_SIZE:
            raise ValueError(
                f"Embedding model dimension {dimension} does not match expected {DEFAULT_VECTOR_SIZE}."
            )
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return int(self._dimension)

    def encode(self, texts: Iterable[str], *, normalize: bool = True, batch_size: int = 64) -> List[List[float]]:
        text_list = list(texts)
        if not text_list:
            return []

        vectors = self._model.encode(
            text_list,
            batch_size=batch_size,
            normalize_embeddings=normalize,
        )
        return [v.tolist() for v in vectors]
