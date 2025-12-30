"""Tests for brigade detector.

This module tests brigade detection and coordinated attack identification.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from usmca_bot.behavior.brigade import BrigadeDetector, BrigadeResult
from usmca_bot.config import Settings


@pytest.mark.unit
class TestBrigadeDetector:
    """Test suite for BrigadeDetector class."""

    @pytest.fixture
    def detector(
        self,
        test_settings: Settings,
        mock_postgres_client: AsyncMock,
        mock_redis_client: AsyncMock,
    ) -> BrigadeDetector:
        """Create detector instance for testing.

        Args:
            test_settings: Test settings fixture.
            mock_postgres_client: Mock PostgreSQL client.
            mock_redis_client: Mock Redis client.

        Returns:
            BrigadeDetector instance.
        """
        return BrigadeDetector(test_settings, mock_postgres_client, mock_redis_client)

    @pytest.mark.asyncio
    async def test_check_join_spike_not_detected(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test join spike detection when below threshold.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        # Mock Redis to return low join count
        mock_redis_client.track_join_event = AsyncMock(return_value=2)

        result = await detector.check_join_spike(
            user_id=123456,
            join_timestamp=datetime.now(timezone.utc),
        )

        assert isinstance(result, BrigadeResult)
        assert result.detected is False
        assert result.detection_type == "join_spike"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_check_join_spike_detected(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test join spike detection when above threshold.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        # Mock Redis to return high join count
        mock_redis_client.track_join_event = AsyncMock(return_value=10)
        mock_redis_client.get_recent_joins = AsyncMock(
            return_value={123456, 123457, 123458, 123459, 123460}
        )

        result = await detector.check_join_spike(
            user_id=123456,
            join_timestamp=datetime.now(timezone.utc),
        )

        assert result.detected is True
        assert result.detection_type == "join_spike"
        assert result.confidence > 0.0
        assert result.participant_count == 5

    @pytest.mark.asyncio
    async def test_check_message_similarity_not_detected(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test message similarity detection when below threshold.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        # Mock Redis to return low similar message count
        mock_redis_client.track_similar_message = AsyncMock(return_value=1)

        result = await detector.check_message_similarity(
            user_id=123456,
            content="Test message",
            timestamp=datetime.now(timezone.utc),
        )

        assert result.detected is False
        assert result.detection_type == "message_similarity"

    @pytest.mark.asyncio
    async def test_check_message_similarity_detected(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test message similarity detection when above threshold.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        # Mock Redis to return high similar message count
        mock_redis_client.track_similar_message = AsyncMock(return_value=5)

        result = await detector.check_message_similarity(
            user_id=123456,
            content="Spam message repeated by many users",
            timestamp=datetime.now(timezone.utc),
        )

        assert result.detected is True
        assert result.detection_type == "message_similarity"
        assert result.confidence > 0.0
        assert result.participant_count == 5

    @pytest.mark.asyncio
    async def test_check_coordinated_activity_insufficient_users(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test coordinated activity with insufficient users.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        result = await detector.check_coordinated_activity(
            user_ids=[123456, 123457],
            time_window_seconds=300,
        )

        assert result.detected is False
        assert result.details["reason"] == "insufficient_users"

    @pytest.mark.asyncio
    async def test_check_coordinated_activity_detected(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test coordinated activity detection.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        user_ids = [123456, 123457, 123458, 123459, 123460]
        
        # Mock Redis to show most users joined recently
        mock_redis_client.get_recent_joins = AsyncMock(
            return_value={123456, 123457, 123458, 123459}
        )

        result = await detector.check_coordinated_activity(
            user_ids=user_ids,
            time_window_seconds=300,
        )

        assert result.detected is True
        assert result.detection_type == "coordinated_activity"
        assert result.confidence > 0.7
        assert result.participant_count >= 3

    @pytest.mark.asyncio
    async def test_check_coordinated_activity_low_coordination(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test coordinated activity with low coordination ratio.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        user_ids = [123456, 123457, 123458, 123459, 123460]
        
        # Mock Redis to show only 1 user joined recently
        mock_redis_client.get_recent_joins = AsyncMock(return_value={123456})

        result = await detector.check_coordinated_activity(
            user_ids=user_ids,
            time_window_seconds=300,
        )

        assert result.detected is False
        assert result.confidence < 0.7

    @pytest.mark.asyncio
    async def test_record_brigade_event(
        self,
        detector: BrigadeDetector,
        mock_postgres_client: AsyncMock,
    ) -> None:
        """Test recording brigade event to database.

        Args:
            detector: BrigadeDetector fixture.
            mock_postgres_client: Mock PostgreSQL client.
        """
        from usmca_bot.database.models import BrigadeEvent

        # Create mock brigade event
        mock_event = BrigadeEvent(
            id=1,
            participant_count=5,
            confidence_score=0.9,
            detection_type="join_spike",
        )
        mock_postgres_client.create_brigade_event = AsyncMock(return_value=mock_event)
        mock_postgres_client.add_brigade_participant = AsyncMock()

        result = BrigadeResult(
            detected=True,
            confidence=0.9,
            detection_type="join_spike",
            participant_count=5,
            participants={123456, 123457, 123458},
            source_hint=None,
            details={},
        )

        event = await detector.record_brigade_event(result)

        assert event.id == 1
        assert event.participant_count == 5
        mock_postgres_client.create_brigade_event.assert_called_once()
        assert mock_postgres_client.add_brigade_participant.call_count == 3

    @pytest.mark.asyncio
    async def test_comprehensive_check_with_join(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test comprehensive check with join timestamp.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        mock_redis_client.track_join_event = AsyncMock(return_value=2)

        results = await detector.comprehensive_check(
            user_id=123456,
            join_timestamp=datetime.now(timezone.utc),
        )

        assert len(results) >= 1
        assert any(r.detection_type == "join_spike" for r in results)

    @pytest.mark.asyncio
    async def test_comprehensive_check_with_message(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test comprehensive check with message content.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        mock_redis_client.track_similar_message = AsyncMock(return_value=1)

        results = await detector.comprehensive_check(
            user_id=123456,
            message_content="Test message",
            message_timestamp=datetime.now(timezone.utc),
        )

        assert len(results) >= 1
        assert any(r.detection_type == "message_similarity" for r in results)

    @pytest.mark.asyncio
    async def test_comprehensive_check_both(
        self,
        detector: BrigadeDetector,
        mock_redis_client: AsyncMock,
    ) -> None:
        """Test comprehensive check with both join and message.

        Args:
            detector: BrigadeDetector fixture.
            mock_redis_client: Mock Redis client.
        """
        mock_redis_client.track_join_event = AsyncMock(return_value=2)
        mock_redis_client.track_similar_message = AsyncMock(return_value=1)

        results = await detector.comprehensive_check(
            user_id=123456,
            join_timestamp=datetime.now(timezone.utc),
            message_content="Test message",
            message_timestamp=datetime.now(timezone.utc),
        )

        assert len(results) == 2
        detection_types = {r.detection_type for r in results}
        assert "join_spike" in detection_types
        assert "message_similarity" in detection_types

    def test_aggregate_results_empty(self, detector: BrigadeDetector) -> None:
        """Test aggregating empty results.

        Args:
            detector: BrigadeDetector fixture.
        """
        result = detector.aggregate_results([])

        assert result.detected is False
        assert result.confidence == 0.0
        assert result.detection_type == "none"

    def test_aggregate_results_mixed(self, detector: BrigadeDetector) -> None:
        """Test aggregating mixed detection results.

        Args:
            detector: BrigadeDetector fixture.
        """
        results = [
            BrigadeResult(
                detected=False,
                confidence=0.2,
                detection_type="join_spike",
                participant_count=2,
                participants={123456, 123457},
                source_hint=None,
                details={},
            ),
            BrigadeResult(
                detected=True,
                confidence=0.9,
                detection_type="message_similarity",
                participant_count=5,
                participants={123458, 123459, 123460},
                source_hint=None,
                details={},
            ),
        ]

        aggregated = detector.aggregate_results(results)

        assert aggregated.detected is True
        assert aggregated.confidence == 0.9
        assert aggregated.detection_type == "message_similarity"
        assert aggregated.participant_count == 5

    def test_aggregate_results_all_detected(self, detector: BrigadeDetector) -> None:
        """Test aggregating when all checks detected brigade.

        Args:
            detector: BrigadeDetector fixture.
        """
        results = [
            BrigadeResult(
                detected=True,
                confidence=0.8,
                detection_type="join_spike",
                participant_count=5,
                participants={123456, 123457, 123458},
                source_hint=None,
                details={},
            ),
            BrigadeResult(
                detected=True,
                confidence=0.7,
                detection_type="message_similarity",
                participant_count=4,
                participants={123459, 123460, 123461},
                source_hint=None,
                details={},
            ),
        ]

        aggregated = detector.aggregate_results(results)

        assert aggregated.detected is True
        assert aggregated.confidence == 0.8
        # Participants from both results
        assert aggregated.participant_count == 6