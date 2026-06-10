"""Receipt visual fingerprint — future extension point for embedding-based similarity."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class FingerprintMatch:
    expense_id: int
    similarity: float
    model_version: str


class BaseReceiptFingerprintProvider(ABC):
    """
    Compute visual embeddings for receipt images and find near-duplicates.

    Future: manipulated duplicates, altered receipts, fraud clustering.
  Not enabled in production — implement and set RECEIPT_FINGERPRINT_ENABLED.
    """

    @property
    @abstractmethod
    def model_version(self) -> str:
        ...

    @abstractmethod
    def compute_embedding(self, image_bytes: bytes, *, mime_type: Optional[str] = None) -> List[float]:
        ...

    @abstractmethod
    def find_similar(
        self,
        embedding: List[float],
        *,
        tenant_id: int,
        user_id: Optional[int] = None,
        limit: int = 5,
        min_similarity: float = 0.85,
    ) -> List[FingerprintMatch]:
        ...


class NoOpReceiptFingerprintProvider(BaseReceiptFingerprintProvider):
    """Placeholder until embedding store and model are wired."""

    model_version = "noop-v0"

    def compute_embedding(self, image_bytes: bytes, *, mime_type: Optional[str] = None) -> List[float]:
        return []

    def find_similar(
        self,
        embedding: List[float],
        *,
        tenant_id: int,
        user_id: Optional[int] = None,
        limit: int = 5,
        min_similarity: float = 0.85,
    ) -> List[FingerprintMatch]:
        return []


def get_fingerprint_provider() -> BaseReceiptFingerprintProvider:
    from app.config import settings

    if getattr(settings, "receipt_fingerprint_enabled", False):
        # Future: return CLIPProvider() or similar
        pass
    return NoOpReceiptFingerprintProvider()
