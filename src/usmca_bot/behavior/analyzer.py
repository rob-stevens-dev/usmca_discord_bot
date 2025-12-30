"""User behavior analysis and risk assessment.

This module analyzes user behavior patterns, calculates risk scores,
and tracks escalation over time.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from usmca_bot.config import Settings
from usmca_bot.database.models import Message, ModerationAction, User
from usmca_bot.database.postgres import PostgresClient

logger = structlog.get_logger()


@dataclass
class BehaviorScore:
    """Behavioral analysis score for a user.

    Attributes:
        user_id: Discord user ID.
        base_score: Base behavioral score (0.0-1.0).
        velocity_multiplier: Message velocity multiplier (1.0-2.0).
        escalation_multiplier: Escalation pattern multiplier (1.0-2.0).
        history_multiplier: Infraction history multiplier (1.0-2.0).
        new_account_multiplier: New account multiplier (1.0-2.0).
        final_score: Aggregated final score (0.0-1.0).
        risk_level: Risk assessment level.
        factors: Dictionary of contributing factors.
    """

    user_id: int
    base_score: float
    velocity_multiplier: float
    escalation_multiplier: float
    history_multiplier: float
    new_account_multiplier: float
    final_score: float
    risk_level: str
    factors: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary containing all score components.
        """
        return {
            "user_id": self.user_id,
            "base_score": self.base_score,
            "velocity_multiplier": self.velocity_multiplier,
            "escalation_multiplier": self.escalation_multiplier,
            "history_multiplier": self.history_multiplier,
            "new_account_multiplier": self.new_account_multiplier,
            "final_score": self.final_score,
            "risk_level": self.risk_level,
            "factors": self.factors,
        }


class BehaviorAnalyzer:
    """Analyzes user behavior patterns and calculates risk scores.

    This analyzer examines user history, message velocity, toxicity trends,
    and infraction patterns to assess behavioral risk.

    Attributes:
        settings: Application settings.
        db: PostgreSQL database client.
    """

    def __init__(self, settings: Settings, db: PostgresClient) -> None:
        """Initialize behavior analyzer.

        Args:
            settings: Application settings.
            db: PostgreSQL database client.
        """
        self.settings = settings
        self.db = db
        self._logger = logger.bind(component="behavior_analyzer")

    async def analyze_user(
        self, user: User, recent_messages: list[Message] | None = None
    ) -> BehaviorScore:
        """Analyze user behavior and calculate risk score.

        Args:
            user: User to analyze.
            recent_messages: Optional list of recent messages (if not provided, will fetch).

        Returns:
            BehaviorScore containing analysis results.

        Example:
```python
            analyzer = BehaviorAnalyzer(settings, db)
            user = await db.get_user(user_id)
            score = await analyzer.analyze_user(user)
            print(f"Risk level: {score.risk_level}")
```
        """
        self._logger.debug("analyzing_user", user_id=user.user_id)

        # Fetch recent messages if not provided
        if recent_messages is None:
            recent_messages = await self.db.get_user_recent_messages(user.user_id, limit=50)

        # Calculate base score from average toxicity
        base_score = user.toxicity_avg

        # Calculate multipliers
        velocity_mult = await self._calculate_velocity_multiplier(user, recent_messages)
        escalation_mult = await self._calculate_escalation_multiplier(user, recent_messages)
        history_mult = self._calculate_history_multiplier(user)
        new_account_mult = self._calculate_new_account_multiplier(user)

        # Aggregate final score (capped at 1.0)
        final_score = min(
            1.0,
            base_score * velocity_mult * escalation_mult * history_mult * new_account_mult,
        )

        # Determine risk level
        risk_level = self._determine_risk_level(final_score, user)

        # Collect factors that contributed to score
        factors = {
            "message_count": len(recent_messages),
            "average_toxicity": user.toxicity_avg,
            "total_infractions": user.total_infractions,
            "account_age_days": (datetime.now(timezone.utc) - user.joined_at).days,
            "recent_escalation": escalation_mult > 1.0,
            "high_velocity": velocity_mult > 1.0,
        }

        score = BehaviorScore(
            user_id=user.user_id,
            base_score=base_score,
            velocity_multiplier=velocity_mult,
            escalation_multiplier=escalation_mult,
            history_multiplier=history_mult,
            new_account_multiplier=new_account_mult,
            final_score=final_score,
            risk_level=risk_level,
            factors=factors,
        )

        self._logger.info(
            "user_analyzed",
            user_id=user.user_id,
            final_score=final_score,
            risk_level=risk_level,
        )

        return score

    async def _calculate_velocity_multiplier(
        self, user: User, recent_messages: list[Message]
    ) -> float:
        """Calculate message velocity multiplier.

        High message velocity (rapid posting) increases risk.

        Args:
            user: User being analyzed.
            recent_messages: Recent messages from user.

        Returns:
            Velocity multiplier (1.0-2.0).
        """
        if len(recent_messages) < 5:
            return 1.0

        # Calculate messages per minute over last 10 messages
        recent_10 = recent_messages[:10]
        if len(recent_10) < 2:
            return 1.0

        time_span = (recent_10[0].created_at - recent_10[-1].created_at).total_seconds()
        if time_span <= 0:
            return 1.0

        messages_per_minute = (len(recent_10) / time_span) * 60

        # Multiplier increases with velocity
        # 1 msg/min = 1.0x, 5 msg/min = 1.5x, 10+ msg/min = 2.0x
        if messages_per_minute > 10:
            return 2.0
        elif messages_per_minute > 5:
            return 1.5
        elif messages_per_minute > 2:
            return 1.2
        else:
            return 1.0

    async def _calculate_escalation_multiplier(
        self, user: User, recent_messages: list[Message]
    ) -> float:
        """Calculate toxicity escalation multiplier.

        Increasing toxicity over time indicates escalating behavior.

        Args:
            user: User being analyzed.
            recent_messages: Recent messages from user.

        Returns:
            Escalation multiplier (1.0-2.0).
        """
        if len(recent_messages) < 10:
            return 1.0

        # Compare recent 5 messages to previous 5 messages
        recent_5 = recent_messages[:5]
        previous_5 = recent_messages[5:10]

        recent_avg = sum(
            m.toxicity_score for m in recent_5 if m.toxicity_score is not None
        ) / len([m for m in recent_5 if m.toxicity_score is not None])

        previous_avg = sum(
            m.toxicity_score for m in previous_5 if m.toxicity_score is not None
        ) / len([m for m in previous_5 if m.toxicity_score is not None])

        if previous_avg == 0:
            return 1.0

        # Calculate escalation ratio
        escalation_ratio = recent_avg / previous_avg

        # Multiplier increases with escalation
        if escalation_ratio > 2.0:
            return 2.0
        elif escalation_ratio > 1.5:
            return 1.5
        elif escalation_ratio > 1.2:
            return 1.2
        else:
            return 1.0

    def _calculate_history_multiplier(self, user: User) -> float:
        """Calculate infraction history multiplier.

        Users with prior warnings/timeouts are higher risk.

        Args:
            user: User being analyzed.

        Returns:
            History multiplier (1.0-2.0).
        """
        total_infractions = user.total_infractions

        if total_infractions == 0:
            return 1.0
        elif total_infractions == 1:
            return 1.2
        elif total_infractions == 2:
            return 1.4
        elif total_infractions >= 3:
            return 1.6
        else:
            return 1.0

    def _calculate_new_account_multiplier(self, user: User) -> float:
        """Calculate new account multiplier.

        New accounts are held to stricter standards.

        Args:
            user: User being analyzed.

        Returns:
            New account multiplier (1.0-1.5).
        """
        account_age = (datetime.now(timezone.utc) - user.joined_at).days

        # New accounts (< 7 days) get stricter treatment
        if account_age < 1:
            return 1.5
        elif account_age < 3:
            return 1.3
        elif account_age < 7:
            return 1.2
        else:
            return 1.0

    def _determine_risk_level(self, final_score: float, user: User) -> str:
        """Determine risk level based on final score.

        Args:
            final_score: Aggregated behavior score.
            user: User being analyzed.

        Returns:
            Risk level: 'green', 'yellow', 'orange', or 'red'.
        """
        # Check if user is whitelisted
        if user.is_whitelisted:
            return "green"

        # Determine risk level by score thresholds
        if final_score < self.settings.toxicity_warning_threshold:
            return "green"
        elif final_score < self.settings.toxicity_timeout_threshold:
            return "yellow"
        elif final_score < self.settings.toxicity_kick_threshold:
            return "orange"
        else:
            return "red"

    async def should_escalate_action(
        self, user: User, current_toxicity: float
    ) -> tuple[bool, str]:
        """Determine if action should be escalated based on user history.

        Args:
            user: User to evaluate.
            current_toxicity: Current message toxicity score.

        Returns:
            Tuple of (should_escalate, reason).
        """
        # Get recent action history
        recent_actions = await self.db.get_user_action_history(user.user_id, limit=10)

        # Check for recent timeouts in last 24 hours
        recent_timeouts = [
            a
            for a in recent_actions
            if a.action_type == "timeout"
            and (datetime.now(timezone.utc) - a.created_at) < timedelta(hours=24)
        ]

        if len(recent_timeouts) >= 2:
            return (
                True,
                f"User has {len(recent_timeouts)} timeouts in last 24 hours",
            )

        # Check for pattern of escalating toxicity
        if user.total_infractions >= 3 and current_toxicity > 0.7:
            return (True, "Repeat offender with high toxicity")

        # Check for very high toxicity regardless of history
        if current_toxicity >= self.settings.toxicity_ban_threshold:
            return (True, "Extremely high toxicity score")

        return (False, "No escalation needed")

    async def get_context_score(
        self, user: User, message_toxicity: float
    ) -> float:
        """Calculate context score considering user history and current state.

        Args:
            user: User being analyzed.
            message_toxicity: Toxicity score of current message.

        Returns:
            Context score (0.0-1.0).
        """
        # Base context score
        context = 0.0

        # Factor in user's average toxicity
        if user.toxicity_avg > 0.3:
            context += 0.2

        # Factor in recent infractions
        if user.total_infractions > 0:
            context += min(0.3, user.total_infractions * 0.1)

        # Factor in new account status
        account_age_days = (datetime.now(timezone.utc) - user.joined_at).days
        if account_age_days < 7:
            context += 0.2

        # Factor in message frequency
        if user.total_messages > 100:
            # High activity reduces context penalty
            context -= 0.1
        elif user.total_messages < 10:
            # Low activity increases context penalty
            context += 0.1

        # Clamp to valid range
        return max(0.0, min(1.0, context))

    async def update_user_risk_level(self, user: User) -> None:
        """Update user's risk level in database based on current behavior.

        Args:
            user: User to update.
        """
        score = await self.analyze_user(user)
        
        if score.risk_level != user.risk_level:
            await self.db.update_user_risk_level(user.user_id, score.risk_level)
            
            self._logger.info(
                "user_risk_updated",
                user_id=user.user_id,
                old_level=user.risk_level,
                new_level=score.risk_level,
            )