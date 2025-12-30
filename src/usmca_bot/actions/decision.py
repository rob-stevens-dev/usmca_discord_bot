"""Decision engine for moderation actions.

This module determines what moderation action should be taken based on
toxicity scores, behavior analysis, and user history.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import structlog

from usmca_bot.behavior.analyzer import BehaviorAnalyzer, BehaviorScore
from usmca_bot.classification.engine import ClassificationResult
from usmca_bot.config import Settings
from usmca_bot.database.models import User
from usmca_bot.database.postgres import PostgresClient

logger = structlog.get_logger()


@dataclass
class ActionDecision:
    """Decision about what moderation action to take.

    Attributes:
        action_type: Type of action to take.
        reason: Human-readable reason for the action.
        toxicity_score: Content toxicity score.
        behavior_score: Behavioral analysis score.
        context_score: Contextual factors score.
        final_score: Aggregated decision score.
        duration_seconds: Duration for timeout (if applicable).
        should_notify_user: Whether to send DM to user.
        should_delete_message: Whether to delete the message.
        escalated: Whether action was escalated from normal flow.
        confidence: Confidence in the decision (0.0-1.0).
        details: Additional decision details.
    """

    action_type: Literal["none", "warning", "timeout", "kick", "ban"]
    reason: str
    toxicity_score: float
    behavior_score: float
    context_score: float
    final_score: float
    duration_seconds: int | None = None
    should_notify_user: bool = True
    should_delete_message: bool = False
    escalated: bool = False
    confidence: float = 1.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary containing all decision data.
        """
        return {
            "action_type": self.action_type,
            "reason": self.reason,
            "toxicity_score": self.toxicity_score,
            "behavior_score": self.behavior_score,
            "context_score": self.context_score,
            "final_score": self.final_score,
            "duration_seconds": self.duration_seconds,
            "should_notify_user": self.should_notify_user,
            "should_delete_message": self.should_delete_message,
            "escalated": self.escalated,
            "confidence": self.confidence,
            "details": self.details or {},
        }


class DecisionEngine:
    """Makes moderation decisions based on classification and behavior analysis.

    This engine aggregates toxicity scores, behavior patterns, and context
    to determine appropriate moderation actions.

    Attributes:
        settings: Application settings.
        db: PostgreSQL database client.
        behavior_analyzer: Behavior analysis engine.
    """

    def __init__(
        self,
        settings: Settings,
        db: PostgresClient,
        behavior_analyzer: BehaviorAnalyzer,
    ) -> None:
        """Initialize decision engine.

        Args:
            settings: Application settings.
            db: PostgreSQL database client.
            behavior_analyzer: Behavior analyzer instance.
        """
        self.settings = settings
        self.db = db
        self.behavior_analyzer = behavior_analyzer
        self._logger = logger.bind(component="decision_engine")

    async def make_decision(
        self,
        user: User,
        classification: ClassificationResult,
        behavior_score: BehaviorScore | None = None,
    ) -> ActionDecision:
        """Make a moderation decision for a user's message.

        Args:
            user: User who sent the message.
            classification: Classification results for the message.
            behavior_score: Optional pre-computed behavior score.

        Returns:
            ActionDecision indicating what action to take.

        Example:
```python
            engine = DecisionEngine(settings, db, behavior_analyzer)
            decision = await engine.make_decision(user, classification)
            print(f"Action: {decision.action_type}")
```
        """
        self._logger.debug(
            "making_decision",
            user_id=user.user_id,
            max_toxicity=classification.max_toxicity,
        )

        # Get behavior score if not provided
        if behavior_score is None:
            behavior_score = await self.behavior_analyzer.analyze_user(user)

        # Calculate aggregated score
        final_score = await self._calculate_final_score(
            user, classification, behavior_score
        )

        # Determine base action from thresholds
        base_action = self._determine_action_from_score(final_score)

        # Check if we should escalate
        should_escalate, escalation_reason = (
            await self.behavior_analyzer.should_escalate_action(
                user, classification.max_toxicity
            )
        )

        # Apply escalation if needed
        if should_escalate and base_action not in ["kick", "ban"]:
            escalated_action = self._escalate_action(base_action)
            reason = f"{escalation_reason}. {self._get_action_reason(classification)}"
            action_type = escalated_action
            escalated = True
        else:
            action_type = base_action
            reason = self._get_action_reason(classification)
            escalated = False

        # Calculate duration for timeouts
        duration_seconds = None
        if action_type == "timeout":
            timeout_count = await self.db.count_user_timeouts(user.user_id)
            duration_seconds = self.settings.get_timeout_duration(timeout_count)

        # Determine if message should be deleted
        should_delete = self._should_delete_message(
            classification.max_toxicity, action_type
        )

        # Calculate confidence based on score clarity
        confidence = self._calculate_confidence(final_score, action_type)

        decision = ActionDecision(
            action_type=action_type,
            reason=reason,
            toxicity_score=classification.max_toxicity,
            behavior_score=behavior_score.final_score,
            context_score=await self.behavior_analyzer.get_context_score(
                user, classification.max_toxicity
            ),
            final_score=final_score,
            duration_seconds=duration_seconds,
            should_notify_user=True,
            should_delete_message=should_delete,
            escalated=escalated,
            confidence=confidence,
            details={
                "risk_level": behavior_score.risk_level,
                "velocity_multiplier": behavior_score.velocity_multiplier,
                "escalation_multiplier": behavior_score.escalation_multiplier,
                "history_multiplier": behavior_score.history_multiplier,
                "new_account_multiplier": behavior_score.new_account_multiplier,
                "total_infractions": user.total_infractions,
            },
        )

        self._logger.info(
            "decision_made",
            user_id=user.user_id,
            action_type=action_type,
            final_score=final_score,
            escalated=escalated,
            confidence=confidence,
        )

        return decision

    async def _calculate_final_score(
        self,
        user: User,
        classification: ClassificationResult,
        behavior_score: BehaviorScore,
    ) -> float:
        """Calculate final aggregated score for decision making.

        Combines toxicity score with behavior analysis using weighted average.

        Args:
            user: User being evaluated.
            classification: Classification results.
            behavior_score: Behavior analysis results.

        Returns:
            Final aggregated score (0.0-1.0).
        """
        # Weight toxicity and behavior scores
        # Toxicity: 60%, Behavior: 40%
        toxicity_weight = 0.6
        behavior_weight = 0.4

        base_score = (
            classification.max_toxicity * toxicity_weight
            + behavior_score.final_score * behavior_weight
        )

        # Apply context adjustments
        context_score = await self.behavior_analyzer.get_context_score(
            user, classification.max_toxicity
        )

        # Context can boost score by up to 20%
        final_score = min(1.0, base_score * (1.0 + context_score * 0.2))

        return final_score

    def _determine_action_from_score(
        self, score: float
    ) -> Literal["none", "warning", "timeout", "kick", "ban"]:
        """Determine action type based on score and thresholds.

        Args:
            score: Final aggregated score.

        Returns:
            Action type to take.
        """
        if score >= self.settings.toxicity_ban_threshold:
            return "ban"
        elif score >= self.settings.toxicity_kick_threshold:
            return "kick"
        elif score >= self.settings.toxicity_timeout_threshold:
            return "timeout"
        elif score >= self.settings.toxicity_warning_threshold:
            return "warning"
        else:
            return "none"

    def _escalate_action(
        self, action: Literal["none", "warning", "timeout", "kick", "ban"]
    ) -> Literal["warning", "timeout", "kick", "ban"]:
        """Escalate an action to the next severity level.

        Args:
            action: Current action type.

        Returns:
            Escalated action type.
        """
        escalation_map = {
            "none": "warning",
            "warning": "timeout",
            "timeout": "kick",
            "kick": "ban",
            "ban": "ban",  # Can't escalate beyond ban
        }
        return escalation_map[action]  # type: ignore

    def _get_action_reason(self, classification: ClassificationResult) -> str:
        """Generate human-readable reason for action.

        Args:
            classification: Classification results.

        Returns:
            Reason string explaining the action.
        """
        scores = classification.toxicity_scores
        reasons = []

        # Identify primary concerns
        if scores.severe_toxicity >= 0.7:
            reasons.append("severe toxic content")
        elif scores.toxicity >= 0.7:
            reasons.append("toxic behavior")

        if scores.threat >= 0.7:
            reasons.append("threatening language")

        if scores.insult >= 0.7:
            reasons.append("insulting behavior")

        if scores.obscene >= 0.7:
            reasons.append("obscene language")

        if scores.identity_attack >= 0.7:
            reasons.append("identity-based harassment")

        # If no specific high scores, use general reason
        if not reasons:
            if scores.max_score >= 0.5:
                reasons.append(f"elevated toxicity (score: {scores.max_score:.2f})")
            else:
                reasons.append("inappropriate content")

        return "Automated moderation: " + ", ".join(reasons)

    def _should_delete_message(
        self, toxicity_score: float, action_type: str
    ) -> bool:
        """Determine if message should be deleted.

        Args:
            toxicity_score: Message toxicity score.
            action_type: Action being taken.

        Returns:
            True if message should be deleted.
        """
        # Delete for kicks and bans
        if action_type in ["kick", "ban"]:
            return True

        # Delete for very high toxicity
        if toxicity_score >= 0.8:
            return True

        # Delete for timeouts with moderate-high toxicity
        if action_type == "timeout" and toxicity_score >= 0.6:
            return True

        return False

    def _calculate_confidence(
        self, final_score: float, action_type: str
    ) -> float:
        """Calculate confidence in the decision.

        Confidence is higher when score is clearly above/below thresholds.

        Args:
            final_score: Final aggregated score.
            action_type: Action type decided.

        Returns:
            Confidence score (0.0-1.0).
        """
        # Get threshold for this action
        if action_type == "none":
            # Below warning threshold
            threshold = self.settings.toxicity_warning_threshold
            distance = threshold - final_score
        elif action_type == "warning":
            threshold = self.settings.toxicity_warning_threshold
            distance = final_score - threshold
        elif action_type == "timeout":
            threshold = self.settings.toxicity_timeout_threshold
            distance = final_score - threshold
        elif action_type == "kick":
            threshold = self.settings.toxicity_kick_threshold
            distance = final_score - threshold
        else:  # ban
            threshold = self.settings.toxicity_ban_threshold
            distance = final_score - threshold

        # Confidence based on distance from threshold
        # 0.1+ away = high confidence (0.9-1.0)
        # Near threshold = lower confidence (0.6-0.8)
        if abs(distance) >= 0.1:
            confidence = 0.95
        elif abs(distance) >= 0.05:
            confidence = 0.85
        else:
            confidence = 0.70

        return confidence

    async def should_take_action(
        self, decision: ActionDecision, user: User
    ) -> bool:
        """Determine if action should actually be executed.

        Provides final check before action execution.

        Args:
            decision: Action decision to evaluate.
            user: User who would be actioned.

        Returns:
            True if action should be executed.
        """
        # Never action whitelisted users
        if user.is_whitelisted:
            self._logger.info(
                "action_skipped_whitelisted",
                user_id=user.user_id,
                action_type=decision.action_type,
            )
            return False

        # Skip "none" actions
        if decision.action_type == "none":
            return False

        # Check if user already has active timeout for timeout decisions
        if decision.action_type == "timeout":
            active_timeout = await self.db.get_active_timeout(user.user_id)
            if active_timeout is not None:
                self._logger.info(
                    "action_skipped_existing_timeout",
                    user_id=user.user_id,
                    expires_at=active_timeout.expires_at,
                )
                return False

        # Low confidence decisions might want manual review
        if decision.confidence < 0.7 and decision.action_type in ["kick", "ban"]:
            self._logger.warning(
                "low_confidence_severe_action",
                user_id=user.user_id,
                action_type=decision.action_type,
                confidence=decision.confidence,
            )
            # In production, might want to queue for manual review instead
            # For now, we'll still execute but log the concern
            pass

        return True

    async def get_action_message(
        self, decision: ActionDecision, user: User
    ) -> str:
        """Generate user-facing message explaining the action.

        Args:
            decision: Action decision.
            user: User receiving the action.

        Returns:
            Message text to send to user.
        """
        action_names = {
            "warning": "received a warning",
            "timeout": "been timed out",
            "kick": "been kicked",
            "ban": "been banned",
        }

        action_text = action_names.get(decision.action_type, "received an action")

        message = f"You have {action_text} for: {decision.reason}\n\n"

        if decision.action_type == "timeout" and decision.duration_seconds:
            duration_str = self._format_duration(decision.duration_seconds)
            message += f"Duration: {duration_str}\n\n"

        if decision.action_type in ["warning", "timeout"]:
            message += (
                "Please review the server rules. "
                "Repeated violations may result in stronger enforcement.\n\n"
            )

        # Add appeal information
        if decision.action_type in ["timeout", "kick", "ban"]:
            message += (
                "If you believe this action was taken in error, "
                "you may appeal by contacting the moderators."
            )

        return message

    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to human-readable string.

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable duration string.
        """
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''}"