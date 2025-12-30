"""Main classification engine coordinating all ML models.

This module provides the ClassificationEngine which orchestrates toxicity detection,
sentiment analysis, and other content classification tasks.
"""

import asyncio
from typing import Any

import structlog

from usmca_bot.classification.toxicity import ToxicityDetector
from usmca_bot.config import Settings
from usmca_bot.database.models import Message, ToxicityScores

logger = structlog.get_logger()


class ClassificationResult:
    """Results from message classification.

    Attributes:
        toxicity_scores: Toxicity classification scores.
        sentiment_score: Sentiment analysis score (-1.0 to 1.0).
        processing_time_ms: Time taken for classification in milliseconds.
        model_versions: Dictionary of model names and versions used.
    """

    def __init__(
        self,
        toxicity_scores: ToxicityScores,
        sentiment_score: float | None = None,
        processing_time_ms: float = 0.0,
        model_versions: dict[str, str] | None = None,
    ) -> None:
        """Initialize classification result.

        Args:
            toxicity_scores: Toxicity scores from model.
            sentiment_score: Sentiment score (optional).
            processing_time_ms: Processing time in milliseconds.
            model_versions: Model version information.
        """
        self.toxicity_scores = toxicity_scores
        self.sentiment_score = sentiment_score
        self.processing_time_ms = processing_time_ms
        self.model_versions = model_versions or {}

    @property
    def max_toxicity(self) -> float:
        """Get maximum toxicity score across all categories.

        Returns:
            Highest toxicity score.
        """
        return self.toxicity_scores.max_score

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary containing all classification results.
        """
        return {
            "toxicity_scores": self.toxicity_scores.model_dump(),
            "sentiment_score": self.sentiment_score,
            "max_toxicity": self.max_toxicity,
            "processing_time_ms": self.processing_time_ms,
            "model_versions": self.model_versions,
        }


class ClassificationEngine:
    """Main classification engine for content analysis.

    This engine coordinates multiple ML models to provide comprehensive
    content analysis including toxicity detection and sentiment analysis.

    Attributes:
        settings: Application settings.
        toxicity_detector: Toxicity detection model.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize classification engine.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.toxicity_detector = ToxicityDetector(settings)
        self._logger = logger.bind(component="classification")

    async def classify_message(self, content: str) -> ClassificationResult:
        """Classify a single message.

        Runs toxicity detection and sentiment analysis on the message content.

        Args:
            content: Message text to classify.

        Returns:
            ClassificationResult containing all analysis results.

        Raises:
            RuntimeError: If classification fails.

        Example:
```python