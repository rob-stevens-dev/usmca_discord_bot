"""Data models for USMCA Bot.

This module defines Pydantic models for all database entities, providing
type safety, validation, and serialization.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ToxicityScores(BaseModel):
    """Toxicity classification scores from ML model.

    All scores are in the range [0.0, 1.0] where higher values indicate
    greater likelihood of the respective category.

    Attributes:
        toxicity: Overall toxicity score.
        severe_toxicity: Severe toxic content score.
        obscene: Obscene language score.
        threat: Threatening content score.
        insult: Insulting content score.
        identity_attack: Identity-based attack score.
    """

    toxicity: float = Field(ge=0.0, le=1.0)
    severe_toxicity: float = Field(ge=0.0, le=1.0)
    obscene: float = Field(ge=0.0, le=1.0)
    threat: float = Field(ge=0.0, le=1.0)
    insult: float = Field(ge=0.0, le=1.0)
    identity_attack: float = Field(ge=0.0, le=1.0)

    @property
    def max_score(self) -> float:
        """Get the maximum score across all categories.

        Returns:
            The highest toxicity score.
        """
        return max(
            self.toxicity,
            self.severe_toxicity,
            self.obscene,
            self.threat,
            self.insult,
            self.identity_attack,
        )

    @property
    def is_toxic(self, threshold: float = 0.5) -> bool:
        """Check if any score exceeds the toxicity threshold.

        Args:
            threshold: Toxicity threshold (default: 0.5).

        Returns:
            True if any score exceeds threshold.
        """
        return self.max_score >= threshold


class User(BaseModel):
    """Discord user profile with behavior tracking.

    Attributes:
        user_id: Discord user ID (snowflake).
        username: Discord username.
        discriminator: Discord discriminator (deprecated in new username system).
        display_name: User's display name.
        joined_at: When user joined the guild.
        first_message_at: When user sent their first message.
        total_messages: Total message count.
        toxicity_avg: Rolling average toxicity score.
        warnings: Number of warnings received.
        timeouts: Number of timeouts received.
        kicks: Number of kicks received.
        bans: Number of bans received.
        last_action_at: Timestamp of last moderation action.
        risk_level: Current risk assessment level.
        is_whitelisted: Whether user is exempt from auto-moderation.
        notes: Admin notes about the user.
        created_at: Record creation timestamp.
        updated_at: Record last update timestamp.
    """

    user_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=32)
    discriminator: str | None = Field(default=None, max_length=4)
    display_name: str | None = Field(default=None, max_length=32)
    joined_at: datetime
    first_message_at: datetime | None = None
    total_messages: int = Field(default=0, ge=0)
    toxicity_avg: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: int = Field(default=0, ge=0)
    timeouts: int = Field(default=0, ge=0)
    kicks: int = Field(default=0, ge=0)
    bans: int = Field(default=0, ge=0)
    last_action_at: datetime | None = None
    risk_level: Literal["green", "yellow", "orange", "red"] = "green"
    is_whitelisted: bool = False
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def total_infractions(self) -> int:
        """Get total number of moderation actions.

        Returns:
            Sum of all warnings, timeouts, kicks, and bans.
        """
        return self.warnings + self.timeouts + self.kicks + self.bans

    @property
    def is_new_account(self, days: int = 7) -> bool:
        """Check if account is considered new.

        Args:
            days: Number of days to consider "new" (default: 7).

        Returns:
            True if account joined within the specified days.
        """
        from datetime import timezone

        age = datetime.now(timezone.utc) - self.joined_at
        return age.days < days


class Message(BaseModel):
    """Discord message with toxicity analysis.

    Attributes:
        message_id: Discord message ID (snowflake).
        user_id: Author's Discord user ID.
        channel_id: Channel ID where message was sent.
        guild_id: Guild ID where message was sent.
        content: Message text content.
        toxicity_score: Overall toxicity score.
        severe_toxicity_score: Severe toxicity score.
        obscene_score: Obscenity score.
        threat_score: Threat score.
        insult_score: Insult score.
        identity_attack_score: Identity attack score.
        sentiment_score: Sentiment analysis score (-1.0 to 1.0).
        is_edited: Whether message has been edited.
        is_deleted: Whether message has been deleted.
        deleted_at: Timestamp of deletion.
        created_at: Message creation timestamp.
        updated_at: Record last update timestamp.
    """

    message_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    channel_id: int = Field(gt=0)
    guild_id: int = Field(gt=0)
    content: str
    toxicity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    severe_toxicity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    obscene_score: float | None = Field(default=None, ge=0.0, le=1.0)
    threat_score: float | None = Field(default=None, ge=0.0, le=1.0)
    insult_score: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_attack_score: float | None = Field(default=None, ge=0.0, le=1.0)
    sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    is_edited: bool = False
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_toxicity_scores(
        cls,
        message_id: int,
        user_id: int,
        channel_id: int,
        guild_id: int,
        content: str,
        scores: ToxicityScores,
        sentiment_score: float | None = None,
    ) -> "Message":
        """Create Message from ToxicityScores object.

        Args:
            message_id: Discord message ID.
            user_id: Author's Discord user ID.
            channel_id: Channel ID.
            guild_id: Guild ID.
            content: Message text.
            scores: Toxicity classification scores.
            sentiment_score: Optional sentiment score.

        Returns:
            Message instance with scores populated.
        """
        return cls(
            message_id=message_id,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            content=content,
            toxicity_score=scores.toxicity,
            severe_toxicity_score=scores.severe_toxicity,
            obscene_score=scores.obscene,
            threat_score=scores.threat,
            insult_score=scores.insult,
            identity_attack_score=scores.identity_attack,
            sentiment_score=sentiment_score,
        )


class ModerationAction(BaseModel):
    """Moderation action record.

    Attributes:
        id: Database auto-increment ID.
        action_uuid: Unique identifier for the action.
        user_id: Target user's Discord ID.
        message_id: Related message ID (if applicable).
        action_type: Type of moderation action.
        reason: Human-readable reason for the action.
        toxicity_score: Content toxicity score.
        behavior_score: Behavioral analysis score.
        context_score: Contextual factors score.
        final_score: Aggregated final score.
        is_automated: Whether action was taken automatically.
        moderator_id: ID of moderator (for manual actions).
        moderator_name: Name of moderator (for manual actions).
        expires_at: Expiration time (for timeouts).
        appealed: Whether user has appealed this action.
        appeal_id: Related appeal ID.
        created_at: Action timestamp.
    """

    id: int | None = None
    action_uuid: UUID | None = None
    user_id: int = Field(gt=0)
    message_id: int | None = Field(default=None, gt=0)
    action_type: Literal["warning", "timeout", "kick", "ban", "unban"]
    reason: str = Field(min_length=1)
    toxicity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    behavior_score: float | None = Field(default=None, ge=0.0, le=1.0)
    context_score: float | None = Field(default=None, ge=0.0, le=1.0)
    final_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_automated: bool = True
    moderator_id: int | None = Field(default=None, gt=0)
    moderator_name: str | None = None
    expires_at: datetime | None = None
    appealed: bool = False
    appeal_id: int | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None, info: dict) -> datetime | None:
        """Validate that expires_at is set for timeouts.

        Args:
            v: Expiration timestamp.
            info: Field validation info.

        Returns:
            Validated expiration timestamp.

        Raises:
            ValueError: If timeout has no expiration.
        """
        if info.data.get("action_type") == "timeout" and v is None:
            raise ValueError("Timeout actions must have expires_at set")
        return v


class Appeal(BaseModel):
    """User appeal of a moderation action.

    Attributes:
        id: Database auto-increment ID.
        action_id: ID of the moderation action being appealed.
        user_id: User submitting the appeal.
        appeal_text: User's appeal statement.
        status: Current appeal status.
        review_notes: Moderator review notes.
        reviewed_by: ID of reviewing moderator.
        reviewed_by_name: Name of reviewing moderator.
        reviewed_at: Review timestamp.
        created_at: Appeal submission timestamp.
        updated_at: Last update timestamp.
    """

    id: int | None = None
    action_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    appeal_text: str = Field(min_length=10, max_length=2000)
    status: Literal["pending", "approved", "denied", "withdrawn"] = "pending"
    review_notes: str | None = None
    reviewed_by: int | None = Field(default=None, gt=0)
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class BrigadeEvent(BaseModel):
    """Detected brigade or coordinated attack event.

    Attributes:
        id: Database auto-increment ID.
        event_uuid: Unique identifier for the event.
        detected_at: Detection timestamp.
        participant_count: Number of users involved.
        confidence_score: Detection confidence (0.0-1.0).
        detection_type: Type of brigade pattern detected.
        source_hint: Additional context about the source.
        is_resolved: Whether event has been resolved.
        resolved_at: Resolution timestamp.
        resolution_notes: Notes about resolution.
        created_at: Record creation timestamp.
    """

    id: int | None = None
    event_uuid: UUID | None = None
    detected_at: datetime = Field(default_factory=datetime.now)
    participant_count: int = Field(gt=0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    detection_type: Literal["join_spike", "message_similarity", "coordinated_activity"]
    source_hint: str | None = None
    is_resolved: bool = False
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)