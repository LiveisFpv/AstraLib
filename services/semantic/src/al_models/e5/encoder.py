"""E5 encoder wrapper that keeps the model in memory."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, List, Optional

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

try:
    from peft import PeftModel  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    PeftModel = None


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    return (last_hidden_state * mask).sum(1) / torch.clamp(mask.sum(1), min=1e-9)


@dataclass(slots=True)
class EncoderConfig:
    model_name: str
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    max_query_length: int = 96
    max_passage_length: int = 512
    batch_size: int = 64
    lora_path: Optional[str] = None


class SemanticEncoder:
    """Keeps the transformer model loaded and provides helper encode methods."""

    def __init__(self, config: EncoderConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self.tokenizer = AutoTokenizer.from_pretrained(config.model_name, use_fast=True)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
        base_model = AutoModel.from_pretrained(
            config.model_name,
            torch_dtype=dtype,
        ).to(device).eval()

        if device.type == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

        if config.lora_path and PeftModel is not None:
            base_model = PeftModel.from_pretrained(base_model, config.lora_path).to(device).eval()

        self.model = base_model
        self._device = device

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def output_dim(self) -> int:
        return int(self.model.config.hidden_size)

    @torch.inference_mode()
    def embed_query(self, text: str) -> np.ndarray:
        embeddings = self._encode(
            [text],
            prefix=self.config.query_prefix,
            max_length=self.config.max_query_length,
        )
        return embeddings

    @torch.inference_mode()
    def embed_passages(self, texts: Iterable[str]) -> np.ndarray:
        return self._encode(
            list(texts),
            prefix=self.config.passage_prefix,
            max_length=self.config.max_passage_length,
        )

    def _encode(self, texts: List[str], *, prefix: str, max_length: int) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.model.config.hidden_size), dtype=np.float32)

        with self._lock:
            outputs: List[np.ndarray] = []
            for start in range(0, len(texts), self.config.batch_size):
                batch_texts = [prefix + t for t in texts[start : start + self.config.batch_size]]
                encoded = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                hidden = self.model(**encoded).last_hidden_state
                pooled = _mean_pool(hidden, encoded["attention_mask"])
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
                outputs.append(pooled.cpu().numpy().astype("float32"))

        return np.vstack(outputs)

    def close(self) -> None:
        with self._lock:
            del self.model
            if torch.cuda.is_available():  # pragma: no cover - safe guard
                torch.cuda.empty_cache()


__all__ = ["SemanticEncoder", "EncoderConfig"]
