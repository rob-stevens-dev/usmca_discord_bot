"""Brigade detection and coordinated attack identification.

This module detects coordinated attacks, mass join events, and other
brigade-like behavior patterns.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from usmca_bot.config import Settings
from usmca_bot.database.models import BrigadeEvent
from usmca_bot.database.postgres import PostgresClient
from usmca_bot.database.redis import RedisClient

logger = structlog.get_logger()


@dataclass
class BrigadeResult:
    """Result of brigade detection analysis.

    Attributes:
        detected: Whether a brigade was detected.
        confidence: Confidence score (0.0-1.0).
        detection_type: Type of brigade pattern detected.
        participant_count: Number of users involved.
        participants: Set of user IDs involved.
        source_hint: Optional hint about brigade source.
        details: Additional detection details.
    """

    detected: bool
    confidence: float
    detection_type: str
    participant_count: int
    participants: set[int]
    source_hint: str | None
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary containing detection results.
        """
        return {
            "detected": self.detected,
            "confidence": self.confidence,
            "detection_type": self.detection_type,
            "participant_count": self.participant_count,
            "participants": list(self.participants),
            "source_hint": self.source_hint,
            "details": self.details,
        }


class BrigadeDetector:
    """Detects brigade attacks and coordinated harassment.

    This detector monitors join patterns, message similarity, and
    coordinated activity to identify brigade attacks.

    Attributes:
        settings: Application settings.
        db: PostgreSQL database client.
        redis: Redis client for real-time tracking.
    """

    def __init__(self, settings: Settings, db: PostgresClient, redis: RedisClient) -> None:
        """Initialize brigade detector.

        Args:
            settings: Application settings.
            db: PostgreSQL database client.
            redis: Redis client.
        """
        self.settings = settings
        self.db = db
        self.redis = redis
        self._logger = logger.bind(component="brigade_detector")

    async def check_join_spike(self, user_id: int, join_timestamp: datetime) -> BrigadeResult:
        """Check for mass join events (join spike).

        Args:
            user_id: ID of user who just joined.
            join_timestamp: Timestamp of join event.

        Returns:
            BrigadeResult indicating detection status.
        """
        # Track this join in Redis
        join_count = await self.redis.track_join_event(user_id, join_timestamp)

        # Check if join count exceeds threshold
        threshold = self.settings.brigade_joins_per_minute
        detected = join_count >= threshold

        if detected:
            # Get list of recent joiners
            recent_joins = await self.redis.get_recent_joins(minutes=1)

            self._logger.warning(
                "join_spike_detected",
                join_count=join_count,
                threshold=threshold,
                participant_count=len(recent_joins),
            )

            return BrigadeResult(
                detected=True,
                confidence=min(1.0, join_count / (threshold * 2)),
                detection_type="join_spike",
                participant_count=len(recent_joins),
                participants=recent_joins,
                source_hint=None,
                details={
                    "joins_per_minute": join_count,
                    "threshold": threshold,
                },
            )
        else:
            return BrigadeResult(
                detected=False,
                confidence=0.0,
                detection_type="join_spike",
                participant_count=0,
                participants=set(),
                source_hint=None,
                details={"joins_per_minute": join_count},
            )

    async def check_message_similarity(
        self, _user_id: int, content: str, timestamp: datetime
    ) -> BrigadeResult:
        """Check for similar messages from multiple users.

        Args:
            user_id: ID of user who sent message.
            content: Message content.
            timestamp: Message timestamp.

        Returns:
            BrigadeResult indicating detection status.
        """
        # Track similar message in Redis
        similar_count = await self.redis.track_similar_message(content, timestamp)

        # Check if similar message count exceeds threshold
        threshold = self.settings.brigade_similar_messages
        detected = similar_count >= threshold

        if detected:
            self._logger.warning(
                "similar_messages_detected",
                similar_count=similar_count,
                threshold=threshold,
                content_preview=content[:50],
            )

            return BrigadeResult(
                detected=True,
                confidence=min(1.0, similar_count / (threshold * 2)),
                detection_type="message_similarity",
                participant_count=similar_count,
                participants=set(),  # We don't track individual IDs in this check
                source_hint=content[:100] if len(content) > 100 else None,
                details={
                    "similar_messages": similar_count,
                    "threshold": threshold,
                    "content_preview": content[:50],
                },
            )
        else:
            return BrigadeResult(
                detected=False,
                confidence=0.0,
                detection_type="message_similarity",
                participant_count=similar_count,
                participants=set(),
                source_hint=None,
                details={"similar_messages": similar_count},
            )

    async def check_coordinated_activity(
        self, user_ids: list[int], time_window_seconds: int = 300
    ) -> BrigadeResult:
        """Check for coordinated activity patterns.

        Analyzes whether multiple users are acting in coordination
        (e.g., all joining and posting within a short time).

        Args:
            user_ids: List of user IDs to check.
            time_window_seconds: Time window to analyze.

        Returns:
            BrigadeResult indicating detection status.
        """
        if len(user_ids) < 3:
            return BrigadeResult(
                detected=False,
                confidence=0.0,
                detection_type="coordinated_activity",
                participant_count=len(user_ids),
                participants=set(user_ids),
                source_hint=None,
                details={"reason": "insufficient_users"},
            )

        # Check if these users joined recently
        recent_joins = await self.redis.get_recent_joins(minutes=time_window_seconds // 60)

        coordinated_users = set(user_ids) & recent_joins
        coordination_ratio = len(coordinated_users) / len(user_ids)

        # High coordination detected if >70% joined recently
        detected = coordination_ratio > 0.7 and len(coordinated_users) >= 3

        if detected:
            self._logger.warning(
                "coordinated_activity_detected",
                coordinated_count=len(coordinated_users),
                total_count=len(user_ids),
                coordination_ratio=coordination_ratio,
            )

            return BrigadeResult(
                detected=True,
                confidence=coordination_ratio,
                detection_type="coordinated_activity",
                participant_count=len(coordinated_users),
                participants=coordinated_users,
                source_hint=None,
                details={
                    "coordination_ratio": coordination_ratio,
                    "coordinated_users": len(coordinated_users),
                    "total_users": len(user_ids),
                },
            )
        else:
            return BrigadeResult(
                detected=False,
                confidence=coordination_ratio,
                detection_type="coordinated_activity",
                participant_count=len(coordinated_users),
                participants=coordinated_users,
                source_hint=None,
                details={
                    "coordination_ratio": coordination_ratio,
                    "coordinated_users": len(coordinated_users),
                },
            )

    async def record_brigade_event(self, result: BrigadeResult) -> BrigadeEvent:
        """Record detected brigade event in database.

        Args:
            result: Brigade detection result.

        Returns:
            Created BrigadeEvent record.
        """
        event = BrigadeEvent(
            participant_count=result.participant_count,
            confidence_score=result.confidence,
            detection_type=result.detection_type,  # type: ignore
            source_hint=result.source_hint,
        )

        created_event = await self.db.create_brigade_event(event)

        # Add participants to database
        for user_id in result.participants:
            await self.db.add_brigade_participant(
                brigade_id=created_event.id,  # type: ignore
                user_id=user_id,
                participation_score=result.confidence,
            )

        self._logger.info(
            "brigade_event_recorded",
            event_id=created_event.id,
            detection_type=result.detection_type,
            participant_count=result.participant_count,
        )

        return created_event

    async def comprehensive_check(
        self,
        user_id: int,
        join_timestamp: datetime | None = None,
        message_content: str | None = None,
        message_timestamp: datetime | None = None,
    ) -> list[BrigadeResult]:
        """Run all brigade detection checks.

        Args:
            user_id: User ID to check.
            join_timestamp: Optional join timestamp.
            message_content: Optional message content.
            message_timestamp: Optional message timestamp.

        Returns:
            List of BrigadeResults from all checks.
        """
        results = []

        # Check join spike if join timestamp provided
        if join_timestamp is not None:
            join_result = await self.check_join_spike(user_id, join_timestamp)
            results.append(join_result)

        # Check message similarity if message provided
        if message_content is not None and message_timestamp is not None:
            message_result = await self.check_message_similarity(
                user_id, message_content, message_timestamp
            )
            results.append(message_result)

        return results

    def aggregate_results(self, results: list[BrigadeResult]) -> BrigadeResult:
        """Aggregate multiple brigade detection results.

        Args:
            results: List of brigade detection results.

        Returns:
            Aggregated BrigadeResult.
        """
        if not results:
            return BrigadeResult(
                detected=False,
                confidence=0.0,
                detection_type="none",
                participant_count=0,
                participants=set(),
                source_hint=None,
                details={},
            )

        # Aggregate detections
        detected = any(r.detected for r in results)
        max_confidence = max((r.confidence for r in results), default=0.0)

        # Get detection type with highest confidence
        detection_type = max(results, key=lambda r: r.confidence).detection_type

        # Combine participants
        all_participants = set()
        for r in results:
            all_participants.update(r.participants)

        return BrigadeResult(
            detected=detected,
            confidence=max_confidence,
            detection_type=detection_type,
            participant_count=len(all_participants),
            participants=all_participants,
            source_hint=None,
            details={
                "individual_results": [r.to_dict() for r in results],
            },
        )
