"""Tests for behavior analyzer.

This module tests user behavior analysis and risk scoring.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from usmca_bot.behavior.analyzer import BehaviorAnalyzer, BehaviorScore
from usmca_bot.config import Settings
from usmca_bot.database.models import Message, User


@pytest.mark.unit
class TestBehaviorAnalyzer:
    """Test suite for BehaviorAnalyzer class."""

    @pytest.fixture
    def analyzer(
        self, test_settings: Settings, mock_postgres_client: AsyncMock
    ) -> BehaviorAnalyzer:
        """Create analyzer instance for testing.

        Args:
            test_settings: Test settings fixture.
            mock_postgres_client: Mock PostgreSQL client.

        Returns:
            BehaviorAnalyzer instance.
        """
        return BehaviorAnalyzer(test_settings, mock_postgres_client)

    @pytest.mark.asyncio
    async def test_analyze_user_low_risk(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
        sample_message: Message,
    ) -> None:
        """Test analyzing a low-risk user.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
            sample_message: Sample message fixture.
        """
        # Create user with low toxicity - use model constructor instead of setting properties
        low_risk_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            toxicity_avg=0.1,
            warnings=0,
            timeouts=0,
            kicks=0,
            bans=0,
            total_messages=10,
        )

        messages = [sample_message for _ in range(10)]
        
        score = await analyzer.analyze_user(low_risk_user, messages)

        assert isinstance(score, BehaviorScore)
        assert score.user_id == low_risk_user.user_id
        assert score.final_score < 0.5
        assert score.risk_level == "green"

    @pytest.mark.asyncio
    async def test_analyze_user_high_risk(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
        sample_message: Message,
    ) -> None:
        """Test analyzing a high-risk user.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
            sample_message: Sample message fixture.
        """
        # Create user with high toxicity and infractions
        high_risk_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            toxicity_avg=0.8,
            warnings=2,
            timeouts=1,
            kicks=0,
            bans=0,
            total_messages=10,
        )

        messages = [sample_message for _ in range(10)]
        for msg in messages:
            # Create new messages with high toxicity instead of modifying
            pass  # Messages already have toxicity scores from fixture

        # Create high toxicity messages
        high_tox_messages = []
        for i, msg in enumerate(messages):
            high_tox_msg = Message(
                message_id=msg.message_id + i,
                user_id=high_risk_user.user_id,
                channel_id=msg.channel_id,
                guild_id=msg.guild_id,
                content=msg.content,
                toxicity_score=0.85,
                severe_toxicity_score=0.7,
                obscene_score=0.6,
                threat_score=0.5,
                insult_score=0.75,
                identity_attack_score=0.4,
            )
            high_tox_messages.append(high_tox_msg)

        score = await analyzer.analyze_user(high_risk_user, high_tox_messages)

        assert score.final_score > 0.7
        assert score.risk_level in ["orange", "red"]

    @pytest.mark.asyncio
    async def test_velocity_multiplier_high(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
        sample_message: Message,
    ) -> None:
        """Test high message velocity increases multiplier.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
            sample_message: Sample message fixture.
        """
        # Create messages with rapid timing (10 messages in 1 minute)
        now = datetime.now(timezone.utc)
        messages = []
        for i in range(10):
            msg = Message(
                message_id=sample_message.message_id + i,
                user_id=sample_user.user_id,
                channel_id=sample_message.channel_id,
                guild_id=sample_message.guild_id,
                content=f"Message {i}",
                created_at=now - timedelta(seconds=i * 6),  # 10 msg/min
            )
            messages.append(msg)

        multiplier = await analyzer._calculate_velocity_multiplier(
            sample_user, messages
        )

        assert multiplier > 1.0

    @pytest.mark.asyncio
    async def test_escalation_multiplier_increasing(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
        sample_message: Message,
    ) -> None:
        """Test escalating toxicity increases multiplier.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
            sample_message: Sample message fixture.
        """
        # Recent messages more toxic than older messages
        messages = []
        for i in range(10):
            msg = Message(
                message_id=sample_message.message_id + i,
                user_id=sample_user.user_id,
                channel_id=sample_message.channel_id,
                guild_id=sample_message.guild_id,
                content=f"Message {i}",
                toxicity_score=0.7 if i < 5 else 0.3,  # Recent more toxic
            )
            messages.append(msg)

        multiplier = await analyzer._calculate_escalation_multiplier(
            sample_user, messages
        )

        assert multiplier > 1.0

    def test_history_multiplier_no_infractions(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test history multiplier with no infractions.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # Create user with no infractions
        clean_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            warnings=0,
            timeouts=0,
            kicks=0,
            bans=0,
        )

        multiplier = analyzer._calculate_history_multiplier(clean_user)

        assert multiplier == 1.0

    def test_history_multiplier_with_infractions(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test history multiplier with infractions.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # Create user with infractions
        user_with_infractions = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            warnings=2,
            timeouts=1,
            kicks=0,
            bans=0,
        )

        multiplier = analyzer._calculate_history_multiplier(user_with_infractions)

        assert multiplier > 1.0

    def test_new_account_multiplier_very_new(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test new account multiplier for very new account.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # Account less than 1 day old
        new_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=datetime.now(timezone.utc) - timedelta(hours=12),
        )

        multiplier = analyzer._calculate_new_account_multiplier(new_user)

        assert multiplier > 1.0

    def test_new_account_multiplier_old_account(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test new account multiplier for old account.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # Account 30 days old
        old_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

        multiplier = analyzer._calculate_new_account_multiplier(old_user)

        assert multiplier == 1.0

    def test_determine_risk_level_green(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test risk level determination for low risk.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        risk_level = analyzer._determine_risk_level(0.2, sample_user)

        assert risk_level == "green"

    def test_determine_risk_level_red(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test risk level determination for high risk.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        risk_level = analyzer._determine_risk_level(0.9, sample_user)

        assert risk_level == "red"

    def test_determine_risk_level_whitelisted(
        self, analyzer: BehaviorAnalyzer, sample_user: User
    ) -> None:
        """Test whitelisted users always get green risk level.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # Create whitelisted user
        whitelisted_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            is_whitelisted=True,
        )

        risk_level = analyzer._determine_risk_level(0.9, whitelisted_user)

        assert risk_level == "green"

    @pytest.mark.asyncio
    async def test_should_escalate_action_repeat_offender(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
        mock_postgres_client: AsyncMock,
    ) -> None:
        """Test escalation for repeat offender.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
            mock_postgres_client: Mock PostgreSQL client.
        """
        # Create repeat offender user
        repeat_offender = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=sample_user.joined_at,
            warnings=3,
            timeouts=2,
            kicks=0,
            bans=0,
        )

        # Mock action history
        mock_postgres_client.get_user_action_history = AsyncMock(return_value=[])

        should_escalate, reason = await analyzer.should_escalate_action(
            repeat_offender, 0.75
        )

        assert should_escalate is True
        assert "repeat offender" in reason.lower()

    @pytest.mark.asyncio
    async def test_get_context_score_new_account(
        self,
        analyzer: BehaviorAnalyzer,
        sample_user: User,
    ) -> None:
        """Test context score for new account.

        Args:
            analyzer: BehaviorAnalyzer fixture.
            sample_user: Sample user fixture.
        """
        # New account with few messages
        new_user = User(
            user_id=sample_user.user_id,
            username=sample_user.username,
            discriminator=sample_user.discriminator,
            display_name=sample_user.display_name,
            joined_at=datetime.now(timezone.utc) - timedelta(days=2),
            total_messages=5,
        )

        context_score = await analyzer.get_context_score(new_user, 0.5)

        assert context_score > 0.0
        assert context_score <= 1.0