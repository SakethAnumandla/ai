"""Voice speaker verification — enterprise future; NOT enabled."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SpeakerVerificationResult:
    verified: bool
    score: float
    model_version: str
    message: str


class SpeakerVerificationProvider(ABC):
    """
    Speaker verification for high-security tenants.

    NOT implemented. Do not call in production until enterprise tier + privacy review.
    """

    @abstractmethod
    def enroll(self, user_id: int, audio_samples: List[bytes]) -> bool:
        ...

    @abstractmethod
    def verify(self, user_id: int, audio: bytes) -> SpeakerVerificationResult:
        ...


class DisabledSpeakerVerification(SpeakerVerificationProvider):
    """Always skips verification — current default."""

    def enroll(self, user_id: int, audio_samples: List[bytes]) -> bool:
        return False

    def verify(self, user_id: int, audio: bytes) -> SpeakerVerificationResult:
        return SpeakerVerificationResult(
            verified=True,
            score=1.0,
            model_version="disabled",
            message="Speaker verification is not enabled for this tenant.",
        )


def get_speaker_verification_provider() -> SpeakerVerificationProvider:
    from app.config import settings

    if getattr(settings, "voice_biometric_enabled", False):
        raise NotImplementedError(
            "Voice biometric verification is planned for enterprise tier only."
        )
    return DisabledSpeakerVerification()
