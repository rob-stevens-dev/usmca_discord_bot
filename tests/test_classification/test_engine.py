"""Tests for classification engine.

This module tests the main classification engine that coordinates ML models.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from usmca_bot.classification.engine import ClassificationEngine, ClassificationResult
from usmca_bot.config import Settings
from usmca_bot.database.models import ToxicityScores


@pytest.mark.unit
class TestClassificationResult:
    """Test suite for ClassificationResult class."""

    def test_create_result(self) -> None:
        """Test creating a classification result."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        result = ClassificationResult(
            toxicity_scores=scores,
            sentiment_score=0.6,
            processing_time_ms=50.0,
            model_versions={"toxicity": "unbiased"},
        )

        assert result.toxicity_scores == scores
        assert result.sentiment_score == 0.6
        assert result.processing_time_ms == 50.0
        assert result.model_versions == {"toxicity": "unbiased"}

    def test_max_toxicity_property(self) -> None:
        """Test max_toxicity returns highest score."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.9,  # Highest
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        assert result.max_toxicity == 0.9

    def test_to_dict(self) -> None:
        """Test to_dict converts to dictionary."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        result = ClassificationResult(
            toxicity_scores=scores,
            sentiment_score=0.6,
            processing_time_ms=50.0,
            model_versions={"toxicity": "unbiased"},
        )

        data = result.to_dict()

        assert "toxicity_scores" in data
        assert "sentiment_score" in data
        assert "max_toxicity" in data
        assert "processing_time_ms" in data
        assert "model_versions" in data
        assert data["sentiment_score"] == 0.6
        assert data["max_toxicity"] == 0.5


@pytest.mark.unit
class TestClassificationEngine:
    """Test suite for ClassificationEngine class."""

    @pytest.fixture
    def engine(self, test_settings: Settings) -> ClassificationEngine:
        """Create engine instance for testing.

        Args:
            test_settings: Test settings fixture.

        Returns:
            ClassificationEngine instance.
        """
        return ClassificationEngine(test_settings)

    def test_initialization(self, engine: ClassificationEngine) -> None:
        """Test engine initializes correctly.

        Args:
            engine: ClassificationEngine fixture.
        """
        assert engine.settings is not None
        assert engine.toxicity_detector is not None

    @pytest.mark.asyncio
    async def test_classify_message(self, engine: ClassificationEngine) -> None:
        """Test classify_message returns result.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock toxicity detector
        mock_scores = ToxicityScores(
            toxicity=0.25,
            severe_toxicity=0.10,
            obscene=0.05,
            threat=0.03,
            insult=0.15,
            identity_attack=0.02,
        )
        engine.toxicity_detector.predict = AsyncMock(return_value=mock_scores)

        result = await engine.classify_message("Test message")

        assert isinstance(result, ClassificationResult)
        assert result.toxicity_scores == mock_scores
        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_classify_message_empty(self, engine: ClassificationEngine) -> None:
        """Test classify_message handles empty text.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock toxicity detector
        mock_scores = ToxicityScores(
            toxicity=0.0,
            severe_toxicity=0.0,
            obscene=0.0,
            threat=0.0,
            insult=0.0,
            identity_attack=0.0,
        )
        engine.toxicity_detector.predict = AsyncMock(return_value=mock_scores)

        result = await engine.classify_message("")

        assert result.toxicity_scores.toxicity == 0.0

    @pytest.mark.asyncio
    async def test_classify_message_error_handling(self, engine: ClassificationEngine) -> None:
        """Test classify_message handles errors.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector to raise error
        engine.toxicity_detector.predict = AsyncMock(side_effect=RuntimeError("Model error"))

        with pytest.raises(RuntimeError) as exc_info:
            await engine.classify_message("Test")

        assert "Message classification failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_classify_messages_batch(self, engine: ClassificationEngine) -> None:
        """Test classify_messages_batch returns multiple results.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock toxicity detector
        mock_scores_list = [
            ToxicityScores(
                toxicity=0.1,
                severe_toxicity=0.05,
                obscene=0.03,
                threat=0.02,
                insult=0.04,
                identity_attack=0.01,
            ),
            ToxicityScores(
                toxicity=0.2,
                severe_toxicity=0.10,
                obscene=0.05,
                threat=0.03,
                insult=0.08,
                identity_attack=0.02,
            ),
        ]
        engine.toxicity_detector.predict_batch = AsyncMock(return_value=mock_scores_list)

        messages = ["Message 1", "Message 2"]
        results = await engine.classify_messages_batch(messages)

        assert len(results) == 2
        assert all(isinstance(r, ClassificationResult) for r in results)
        assert results[0].toxicity_scores.toxicity == 0.1
        assert results[1].toxicity_scores.toxicity == 0.2

    @pytest.mark.asyncio
    async def test_classify_messages_batch_empty(self, engine: ClassificationEngine) -> None:
        """Test classify_messages_batch with empty list.

        Args:
            engine: ClassificationEngine fixture.
        """
        engine.toxicity_detector.predict_batch = AsyncMock(return_value=[])

        results = await engine.classify_messages_batch([])

        assert results == []

    @pytest.mark.asyncio
    async def test_classify_messages_batch_with_batch_size(
        self, engine: ClassificationEngine
    ) -> None:
        """Test classify_messages_batch respects batch_size.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector
        mock_scores_list = [
            ToxicityScores(
                toxicity=0.1,
                severe_toxicity=0.05,
                obscene=0.03,
                threat=0.02,
                insult=0.04,
                identity_attack=0.01,
            )
            for _ in range(5)
        ]
        engine.toxicity_detector.predict_batch = AsyncMock(return_value=mock_scores_list)

        messages = ["Message " + str(i) for i in range(5)]
        results = await engine.classify_messages_batch(messages, batch_size=2)

        assert len(results) == 5
        engine.toxicity_detector.predict_batch.assert_called_once_with(messages, batch_size=2)

    @pytest.mark.asyncio
    async def test_classify_messages_batch_error_handling(
        self, engine: ClassificationEngine
    ) -> None:
        """Test classify_messages_batch handles errors.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector to raise error
        engine.toxicity_detector.predict_batch = AsyncMock(side_effect=RuntimeError("Batch error"))

        with pytest.raises(RuntimeError) as exc_info:
            await engine.classify_messages_batch(["Text 1", "Text 2"])

        assert "Batch classification failed" in str(exc_info.value)

    def test_should_flag_message_above_threshold(self, engine: ClassificationEngine) -> None:
        """Test should_flag_message returns True above threshold.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.7,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        assert engine.should_flag_message(result, threshold=0.5) is True

    def test_should_flag_message_below_threshold(self, engine: ClassificationEngine) -> None:
        """Test should_flag_message returns False below threshold.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.3,
            severe_toxicity=0.1,
            obscene=0.05,
            threat=0.02,
            insult=0.08,
            identity_attack=0.01,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        assert engine.should_flag_message(result, threshold=0.5) is False

    def test_should_flag_message_at_threshold(self, engine: ClassificationEngine) -> None:
        """Test should_flag_message at exact threshold.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.2,
            obscene=0.1,
            threat=0.05,
            insult=0.2,
            identity_attack=0.05,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        assert engine.should_flag_message(result, threshold=0.5) is True

    def test_get_flag_reason_severe_toxicity(self, engine: ClassificationEngine) -> None:
        """Test get_flag_reason for severe toxicity.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.8,  # High
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        reason = engine.get_flag_reason(result)

        assert "severe toxic" in reason.lower()

    def test_get_flag_reason_threat(self, engine: ClassificationEngine) -> None:
        """Test get_flag_reason for threatening content.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.8,  # High
            insult=0.4,
            identity_attack=0.15,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        reason = engine.get_flag_reason(result)

        assert "threat" in reason.lower()

    def test_get_flag_reason_multiple_factors(self, engine: ClassificationEngine) -> None:
        """Test get_flag_reason with multiple high scores.

        Args:
            engine: ClassificationEngine fixture.
        """
        scores = ToxicityScores(
            toxicity=0.8,
            severe_toxicity=0.3,
            obscene=0.9,
            threat=0.1,
            insult=0.85,
            identity_attack=0.15,
        )
        result = ClassificationResult(
            toxicity_scores=scores,
            processing_time_ms=50.0,
        )

        reason = engine.get_flag_reason(result)

        # Should mention multiple factors
        assert "toxic" in reason.lower()
        assert any(word in reason.lower() for word in ["obscene", "insult"])

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, engine: ClassificationEngine) -> None:
        """Test health_check when engine is healthy.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock toxicity detector
        mock_scores = ToxicityScores(
            toxicity=0.1,
            severe_toxicity=0.05,
            obscene=0.03,
            threat=0.02,
            insult=0.04,
            identity_attack=0.01,
        )
        engine.toxicity_detector.predict = AsyncMock(return_value=mock_scores)
        # Mock the is_loaded property instead of setting it
        with patch.object(
            type(engine.toxicity_detector),
            "is_loaded",
            new_callable=lambda: property(lambda self: True),
        ):
            health = await engine.health_check()

        assert health["status"] == "healthy"
        assert health["test_classification"]["success"] is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, engine: ClassificationEngine) -> None:
        """Test health_check when engine has errors.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector to raise error
        engine.toxicity_detector.predict = AsyncMock(side_effect=RuntimeError("Model error"))

        health = await engine.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health

    @pytest.mark.asyncio
    async def test_warmup(self, engine: ClassificationEngine) -> None:
        """Test warmup loads models.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock classifier
        mock_scores_list = [
            ToxicityScores(
                toxicity=0.1,
                severe_toxicity=0.05,
                obscene=0.03,
                threat=0.02,
                insult=0.04,
                identity_attack=0.01,
            )
            for _ in range(3)
        ]
        engine.toxicity_detector.predict_batch = AsyncMock(return_value=mock_scores_list)

        # Should not raise exception
        await engine.warmup()

        engine.toxicity_detector.predict_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_warmup_error_handling(self, engine: ClassificationEngine) -> None:
        """Test warmup handles errors gracefully.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector to raise error
        engine.toxicity_detector.predict_batch = AsyncMock(
            side_effect=RuntimeError("Model load error")
        )

        with pytest.raises(RuntimeError) as exc_info:
            await engine.warmup()

        assert "Classification engine warmup failed" in str(exc_info.value)

    def test_cleanup(self, engine: ClassificationEngine) -> None:
        """Test cleanup unloads models.

        Args:
            engine: ClassificationEngine fixture.
        """
        # Mock detector
        engine.toxicity_detector.unload_model = MagicMock()

        engine.cleanup()

        engine.toxicity_detector.unload_model.assert_called_once()
