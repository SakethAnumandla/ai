from typing import List

from pydantic import BaseModel, Field

from app.ai.classifier.response_classifier import ResponseClassification


class ResponseClassificationOut(BaseModel):
    classification: ResponseClassification
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)
