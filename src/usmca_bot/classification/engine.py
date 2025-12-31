"""Main classification engine coordinating all ML models.

This module provides the ClassificationEngine which orchestrates toxicity detection,
sentiment analysis, and other content classification tasks.
"""

from typing import Any

import structlog

from usmca_bot.classification.toxicity import ToxicityDetector
from usmca_bot.config import Settings
from usmca_bot.database.models import ToxicityScores

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
                    engine = ClassificationEngine(settings)
                    result = await engine.classify_message("Hello world!")
                    print(f"Toxicity: {result.max_toxicity:.2f}")
        ```
        """
        import time

        start_time = time.perf_counter()

        try:
            # Run toxicity detection
            # In future, we could run sentiment analysis concurrently here
            toxicity_scores = await self.toxicity_detector.predict(content)

            # Placeholder for sentiment analysis - could add later
            sentiment_score = None

            processing_time = (time.perf_counter() - start_time) * 1000

            result = ClassificationResult(
                toxicity_scores=toxicity_scores,
                sentiment_score=sentiment_score,
                processing_time_ms=processing_time,
                model_versions={
                    "toxicity": self.toxicity_detector.model_type,
                },
            )

            self._logger.debug(
                "message_classified",
                content_length=len(content),
                max_toxicity=result.max_toxicity,
                processing_time_ms=processing_time,
            )

            return result

        except Exception as e:
            self._logger.error(
                "classification_failed",
                error=str(e),
                content_length=len(content),
            )
            raise RuntimeError(f"Message classification failed: {e}") from e

    async def classify_messages_batch(
        self, messages: list[str], batch_size: int = 32
    ) -> list[ClassificationResult]:
        """Classify multiple messages in batch.

                More efficient than calling classify_message() multiple times.

                Args:
                    messages: List of message texts to classify.
                    batch_size: Number of messages to process per batch.

                Returns:
                    List of ClassificationResults, same order as input.

                Raises:
                    RuntimeError: If classification fails.

                Example:
        ```python
                    engine = ClassificationEngine(settings)
                    messages = ["msg1", "msg2", "msg3"]
                    results = await engine.classify_messages_batch(messages)
        ```
        """
        import time

        start_time = time.perf_counter()

        try:
            # Batch toxicity detection
            toxicity_scores_list = await self.toxicity_detector.predict_batch(
                messages, batch_size=batch_size
            )

            processing_time = (time.perf_counter() - start_time) * 1000

            # Create results
            results = [
                ClassificationResult(
                    toxicity_scores=scores,
                    sentiment_score=None,
                    processing_time_ms=processing_time / len(messages),
                    model_versions={"toxicity": self.toxicity_detector.model_type},
                )
                for scores in toxicity_scores_list
            ]

            self._logger.debug(
                "batch_classified",
                count=len(messages),
                total_processing_time_ms=processing_time,
                avg_processing_time_ms=processing_time / len(messages) if messages else 0,
            )

            return results

        except Exception as e:
            self._logger.error(
                "batch_classification_failed",
                error=str(e),
                count=len(messages),
            )
            raise RuntimeError(f"Batch classification failed: {e}") from e

    def should_flag_message(self, result: ClassificationResult, threshold: float = 0.5) -> bool:
        """Determine if message should be flagged for moderation.

        Args:
            result: Classification result to evaluate.
            threshold: Toxicity threshold for flagging.

        Returns:
            True if message should be flagged, False otherwise.
        """
        return result.max_toxicity >= threshold

    def get_flag_reason(self, result: ClassificationResult) -> str:
        """Get human-readable reason for flagging.

        Args:
            result: Classification result.

        Returns:
            String describing why message was flagged.
        """
        scores = result.toxicity_scores
        reasons = []

        if scores.severe_toxicity >= 0.7:
            reasons.append("severe toxicity")
        elif scores.toxicity >= 0.7:
            reasons.append("toxicity")

        if scores.threat >= 0.7:
            reasons.append("threatening content")

        if scores.insult >= 0.7:
            reasons.append("insulting language")

        if scores.obscene >= 0.7:
            reasons.append("obscene language")

        if scores.identity_attack >= 0.7:
            reasons.append("identity-based attack")

        if not reasons:
            # Moderate toxicity
            reasons.append(f"elevated toxicity ({scores.max_score:.2f})")

        return ", ".join(reasons)

    async def health_check(self) -> dict[str, Any]:
        """Check health status of classification engine.

        Returns:
            Dictionary containing health status and model information.
        """
        try:
            # Test classification with sample text
            test_result = await self.classify_message("test message")

            return {
                "status": "healthy",
                "toxicity_detector": {
                    "loaded": self.toxicity_detector.is_loaded,
                    "model_type": self.toxicity_detector.model_type,
                    "device": self.toxicity_detector.device,
                },
                "test_classification": {
                    "success": True,
                    "processing_time_ms": test_result.processing_time_ms,
                },
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "toxicity_detector": {
                    "loaded": self.toxicity_detector.is_loaded,
                },
            }

    async def warmup(self) -> None:
        """Warm up models by running test predictions.

        This loads models into memory and runs initial predictions
        to ensure fast response times for real requests.

        Raises:
            RuntimeError: If warmup fails.
        """
        self._logger.info("warming_up_classification_engine")

        try:
            # Test messages covering various scenarios
            test_messages = [
                "Hello world!",
                "This is a test message.",
                "Another example for warmup.",
            ]

            # Run batch classification to load and test models
            await self.classify_messages_batch(test_messages)

            self._logger.info(
                "warmup_complete",
                model_loaded=self.toxicity_detector.is_loaded,
            )

        except Exception as e:
            self._logger.error("warmup_failed", error=str(e))
            raise RuntimeError(f"Classification engine warmup failed: {e}") from e

    def cleanup(self) -> None:
        """Clean up resources and unload models.

        Useful for graceful shutdown or reducing memory usage.
        """
        self._logger.info("cleaning_up_classification_engine")
        self.toxicity_detector.unload_model()
