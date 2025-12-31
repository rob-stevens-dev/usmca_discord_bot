"""Tests for database models.

This module tests Pydantic model validation, properties, and helper methods.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from usmca_bot.database.models import (
    Appeal,
    BrigadeEvent,
    Message,
    ModerationAction,
    ToxicityScores,
    User,
)


@pytest.mark.unit
class TestToxicityScores:
    """Test suite for ToxicityScores model."""

    def test_valid_scores(self) -> None:
        """Test creating toxicity scores with valid values."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        assert scores.toxicity == 0.5
        assert scores.severe_toxicity == 0.3
        assert scores.obscene == 0.2
        assert scores.threat == 0.1
        assert scores.insult == 0.4
        assert scores.identity_attack == 0.15

    def test_scores_out_of_range_high(self) -> None:
        """Test validation fails for scores > 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            ToxicityScores(
                toxicity=1.5,  # Invalid
                severe_toxicity=0.3,
                obscene=0.2,
                threat=0.1,
                insult=0.4,
                identity_attack=0.15,
            )

        assert "toxicity" in str(exc_info.value)

    def test_scores_out_of_range_low(self) -> None:
        """Test validation fails for scores < 0.0."""
        with pytest.raises(ValidationError) as exc_info:
            ToxicityScores(
                toxicity=0.5,
                severe_toxicity=-0.1,  # Invalid
                obscene=0.2,
                threat=0.1,
                insult=0.4,
                identity_attack=0.15,
            )

        assert "severe_toxicity" in str(exc_info.value)

    def test_max_score_property(self) -> None:
        """Test max_score returns highest value."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.9,  # Highest
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        assert scores.max_score == 0.9

    def test_is_toxic_default_threshold(self) -> None:
        """Test is_toxic with default threshold (0.5)."""
        scores = ToxicityScores(
            toxicity=0.6,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        assert scores.is_toxic() is True

    def test_is_toxic_custom_threshold(self) -> None:
        """Test is_toxic with custom threshold."""
        scores = ToxicityScores(
            toxicity=0.6,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        assert scores.is_toxic(0.7) is False
        assert scores.is_toxic(0.5) is True

    def test_is_toxic_at_threshold(self) -> None:
        """Test is_toxic when score equals threshold."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        assert scores.is_toxic(0.5) is True  # >= threshold


@pytest.mark.unit
class TestUser:
    """Test suite for User model."""

    def test_create_user_minimal(self) -> None:
        """Test creating user with minimal required fields."""
        user = User(
            user_id=123456789,
            username="testuser",
            joined_at=datetime.now(UTC),
        )

        assert user.user_id == 123456789
        assert user.username == "testuser"
        assert user.total_messages == 0
        assert user.toxicity_avg == 0.0
        assert user.risk_level == "green"
        assert user.is_whitelisted is False

    def test_create_user_full(self) -> None:
        """Test creating user with all fields."""
        now = datetime.now(UTC)
        user = User(
            user_id=123456789,
            username="testuser",
            discriminator="1234",
            display_name="Test User",
            joined_at=now,
            first_message_at=now,
            total_messages=10,
            toxicity_avg=0.25,
            warnings=1,
            timeouts=0,
            kicks=0,
            bans=0,
            risk_level="yellow",
            is_whitelisted=False,
            notes="Test notes",
        )

        assert user.user_id == 123456789
        assert user.username == "testuser"
        assert user.discriminator == "1234"
        assert user.total_messages == 10
        assert user.toxicity_avg == 0.25
        assert user.warnings == 1
        assert user.risk_level == "yellow"

    def test_user_id_validation_negative(self) -> None:
        """Test validation fails for negative user_id."""
        with pytest.raises(ValidationError) as exc_info:
            User(
                user_id=-1,
                username="testuser",
                joined_at=datetime.now(UTC),
            )

        assert "user_id" in str(exc_info.value)

    def test_user_id_validation_zero(self) -> None:
        """Test validation fails for zero user_id."""
        with pytest.raises(ValidationError) as exc_info:
            User(
                user_id=0,
                username="testuser",
                joined_at=datetime.now(UTC),
            )

        assert "user_id" in str(exc_info.value)

    def test_toxicity_avg_range_validation(self) -> None:
        """Test toxicity_avg must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            User(
                user_id=123456789,
                username="testuser",
                joined_at=datetime.now(UTC),
                toxicity_avg=1.5,
            )

    def test_total_infractions_property(self) -> None:
        """Test total_infractions sums all action counts."""
        user = User(
            user_id=123456789,
            username="testuser",
            joined_at=datetime.now(UTC),
            warnings=2,
            timeouts=1,
            kicks=1,
            bans=0,
        )

        assert user.total_infractions == 4

    def test_is_new_account_default_threshold(self) -> None:
        """Test is_new_account with default 7 day threshold."""
        # New account (3 days old)
        new_user = User(
            user_id=123456789,
            username="newuser",
            joined_at=datetime.now(UTC) - timedelta(days=3),
        )

        assert new_user.is_new_account() is True

        # Old account (30 days old)
        old_user = User(
            user_id=987654321,
            username="olduser",
            joined_at=datetime.now(UTC) - timedelta(days=30),
        )

        assert old_user.is_new_account() is False

    def test_is_new_account_custom_threshold(self) -> None:
        """Test is_new_account with custom threshold."""
        user = User(
            user_id=123456789,
            username="testuser",
            joined_at=datetime.now(UTC) - timedelta(days=10),
        )

        assert user.is_new_account(7) is False
        assert user.is_new_account(30) is True

    def test_risk_level_validation(self) -> None:
        """Test risk_level must be one of allowed values."""
        with pytest.raises(ValidationError):
            User(
                user_id=123456789,
                username="testuser",
                joined_at=datetime.now(UTC),
                risk_level="purple",  # Invalid
            )


@pytest.mark.unit
class TestMessage:
    """Test suite for Message model."""

    def test_create_message_minimal(self) -> None:
        """Test creating message with minimal fields."""
        message = Message(
            message_id=987654321,
            user_id=123456789,
            channel_id=111222333,
            guild_id=444555666,
            content="Test message",
        )

        assert message.message_id == 987654321
        assert message.user_id == 123456789
        assert message.content == "Test message"
        assert message.is_edited is False
        assert message.is_deleted is False

    def test_create_message_with_scores(self) -> None:
        """Test creating message with toxicity scores."""
        message = Message(
            message_id=987654321,
            user_id=123456789,
            channel_id=111222333,
            guild_id=444555666,
            content="Test message",
            toxicity_score=0.5,
            severe_toxicity_score=0.3,
            obscene_score=0.2,
            threat_score=0.1,
            insult_score=0.4,
            identity_attack_score=0.15,
            sentiment_score=0.6,
        )

        assert message.toxicity_score == 0.5
        assert message.sentiment_score == 0.6

    def test_from_toxicity_scores_factory(self) -> None:
        """Test creating message from ToxicityScores object."""
        scores = ToxicityScores(
            toxicity=0.5,
            severe_toxicity=0.3,
            obscene=0.2,
            threat=0.1,
            insult=0.4,
            identity_attack=0.15,
        )

        message = Message.from_toxicity_scores(
            message_id=987654321,
            user_id=123456789,
            channel_id=111222333,
            guild_id=444555666,
            content="Test message",
            scores=scores,
            sentiment_score=0.6,
        )

        assert message.toxicity_score == 0.5
        assert message.severe_toxicity_score == 0.3
        assert message.sentiment_score == 0.6

    def test_message_id_validation(self) -> None:
        """Test message_id must be positive."""
        with pytest.raises(ValidationError):
            Message(
                message_id=-1,
                user_id=123456789,
                channel_id=111222333,
                guild_id=444555666,
                content="Test",
            )

    def test_sentiment_score_range(self) -> None:
        """Test sentiment_score must be between -1.0 and 1.0."""
        with pytest.raises(ValidationError):
            Message(
                message_id=987654321,
                user_id=123456789,
                channel_id=111222333,
                guild_id=444555666,
                content="Test",
                sentiment_score=1.5,  # Invalid
            )


@pytest.mark.unit
class TestModerationAction:
    """Test suite for ModerationAction model."""

    def test_create_action_warning(self) -> None:
        """Test creating a warning action."""
        action = ModerationAction(
            user_id=123456789,
            action_type="warning",
            reason="Inappropriate language",
            toxicity_score=0.4,
            behavior_score=0.3,
            context_score=0.2,
            final_score=0.4,
        )

        assert action.user_id == 123456789
        assert action.action_type == "warning"
        assert action.is_automated is True
        assert action.appealed is False

    def test_create_action_timeout_with_expiration(self) -> None:
        """Test creating a timeout action with expiration."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        action = ModerationAction(
            user_id=123456789,
            action_type="timeout",
            reason="Toxic behavior",
            toxicity_score=0.6,
            behavior_score=0.5,
            context_score=0.3,
            final_score=0.6,
            expires_at=expires_at,
        )

        assert action.action_type == "timeout"
        assert action.expires_at == expires_at

    def test_timeout_without_expiration_fails(self) -> None:
        """Test timeout must have expires_at set."""
        with pytest.raises(ValidationError) as exc_info:
            ModerationAction(
                user_id=123456789,
                action_type="timeout",
                reason="Toxic behavior",
                expires_at=None,  # Required for timeout
            )

        assert "expires_at" in str(exc_info.value).lower()

    def test_action_type_validation(self) -> None:
        """Test action_type must be one of allowed values."""
        with pytest.raises(ValidationError):
            ModerationAction(
                user_id=123456789,
                action_type="suspend",  # Invalid
                reason="Test",
            )

    def test_manual_action(self) -> None:
        """Test creating a manual (non-automated) action."""
        action = ModerationAction(
            user_id=123456789,
            action_type="kick",
            reason="Manual kick by moderator",
            is_automated=False,
            moderator_id=111222333,
            moderator_name="ModName",
        )

        assert action.is_automated is False
        assert action.moderator_id == 111222333
        assert action.moderator_name == "ModName"


@pytest.mark.unit
class TestAppeal:
    """Test suite for Appeal model."""

    def test_create_appeal(self) -> None:
        """Test creating an appeal."""
        appeal = Appeal(
            action_id=1,
            user_id=123456789,
            appeal_text="I believe this action was taken in error because...",
        )

        assert appeal.action_id == 1
        assert appeal.user_id == 123456789
        assert appeal.status == "pending"
        assert appeal.reviewed_by is None

    def test_appeal_text_min_length(self) -> None:
        """Test appeal_text must be at least 10 characters."""
        with pytest.raises(ValidationError):
            Appeal(
                action_id=1,
                user_id=123456789,
                appeal_text="Too short",  # < 10 chars
            )

    def test_appeal_text_max_length(self) -> None:
        """Test appeal_text must not exceed 2000 characters."""
        with pytest.raises(ValidationError):
            Appeal(
                action_id=1,
                user_id=123456789,
                appeal_text="x" * 2001,  # Too long
            )

    def test_appeal_status_validation(self) -> None:
        """Test status must be one of allowed values."""
        with pytest.raises(ValidationError):
            Appeal(
                action_id=1,
                user_id=123456789,
                appeal_text="Valid appeal text here",
                status="processing",  # Invalid
            )

    def test_reviewed_appeal(self) -> None:
        """Test appeal with review information."""
        now = datetime.now(UTC)
        appeal = Appeal(
            action_id=1,
            user_id=123456789,
            appeal_text="Valid appeal text here",
            status="approved",
            review_notes="Appeal granted",
            reviewed_by=111222333,
            reviewed_by_name="ModName",
            reviewed_at=now,
        )

        assert appeal.status == "approved"
        assert appeal.reviewed_by == 111222333
        assert appeal.reviewed_at == now


@pytest.mark.unit
class TestBrigadeEvent:
    """Test suite for BrigadeEvent model."""

    def test_create_brigade_event(self) -> None:
        """Test creating a brigade event."""
        event = BrigadeEvent(
            participant_count=10,
            confidence_score=0.9,
            detection_type="join_spike",
        )

        assert event.participant_count == 10
        assert event.confidence_score == 0.9
        assert event.detection_type == "join_spike"
        assert event.is_resolved is False

    def test_participant_count_validation(self) -> None:
        """Test participant_count must be positive."""
        with pytest.raises(ValidationError):
            BrigadeEvent(
                participant_count=0,  # Invalid
                confidence_score=0.9,
                detection_type="join_spike",
            )

    def test_confidence_score_range(self) -> None:
        """Test confidence_score must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            BrigadeEvent(
                participant_count=10,
                confidence_score=1.5,  # Invalid
                detection_type="join_spike",
            )

    def test_detection_type_validation(self) -> None:
        """Test detection_type must be one of allowed values."""
        with pytest.raises(ValidationError):
            BrigadeEvent(
                participant_count=10,
                confidence_score=0.9,
                detection_type="raid",  # Invalid
            )

    def test_resolved_brigade_event(self) -> None:
        """Test brigade event with resolution."""
        now = datetime.now(UTC)
        event = BrigadeEvent(
            participant_count=10,
            confidence_score=0.9,
            detection_type="message_similarity",
            is_resolved=True,
            resolved_at=now,
            resolution_notes="False positive - coordinated meme",
        )

        assert event.is_resolved is True
        assert event.resolved_at == now
        assert event.resolution_notes is not None
