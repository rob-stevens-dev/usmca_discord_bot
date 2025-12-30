"""Redis client for USMCA Bot.

This module provides a Redis client for rate limiting, brigade detection,
message deduplication, and caching.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as redis

from usmca_bot.config import Settings


class RedisClient:
    """Async Redis client for caching and rate limiting.

    This client provides high-level methods for common Redis operations
    including rate limiting, message deduplication, and brigade detection.

    Attributes:
        settings: Application settings containing Redis configuration.
        client: Async Redis client instance.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize Redis client.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis.

        Creates a connection pool with configured max connections.

        Raises:
            redis.RedisError: If connection fails.
        """
        self.client = redis.from_url(
            str(self.settings.redis_url),
            max_connections=self.settings.redis_max_connections,
            decode_responses=True,
        )
        # Test connection
        await self.client.ping()

    async def disconnect(self) -> None:
        """Close Redis connection gracefully.

        Closes the connection pool and cleans up resources.
        """
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # Rate Limiting

    async def check_user_rate_limit(
        self, user_id: int, max_messages: int = 10, window_seconds: int = 60
    ) -> tuple[bool, int]:
        """Check if user has exceeded rate limit.

        Uses a sliding window counter to track message rates.

        Args:
            user_id: Discord user ID.
            max_messages: Maximum messages allowed in window.
            window_seconds: Time window in seconds.

        Returns:
            Tuple of (is_allowed, current_count).
            is_allowed is True if under limit, False if exceeded.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = f"rate:user:{user_id}:messages"
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds

        # Use pipeline for atomic operations
        pipe = self.client.pipeline()
        
        # Remove old entries outside window
        pipe.zremrangebyscore(key, "-inf", window_start)
        
        # Add current timestamp
        pipe.zadd(key, {str(now): now})
        
        # Count messages in window
        pipe.zcard(key)
        
        # Set expiration
        pipe.expire(key, window_seconds)
        
        results = await pipe.execute()
        current_count = results[2]  # zcard result

        is_allowed = current_count <= max_messages
        return is_allowed, current_count

    async def check_global_rate_limit(
        self, max_messages: int = 100, window_seconds: int = 60
    ) -> tuple[bool, int]:
        """Check global server rate limit.

        Args:
            max_messages: Maximum global messages allowed in window.
            window_seconds: Time window in seconds.

        Returns:
            Tuple of (is_allowed, current_count).

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = "rate:global:messages"
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds

        pipe = self.client.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        
        results = await pipe.execute()
        current_count = results[2]

        is_allowed = current_count <= max_messages
        return is_allowed, current_count

    # Message Deduplication

    async def is_duplicate_message(
        self, message_id: int, ttl_seconds: int = 60
    ) -> bool:
        """Check if message has already been processed.

        Uses Redis SET NX (set if not exists) to atomically mark messages.

        Args:
            message_id: Discord message ID.
            ttl_seconds: Time to live for deduplication marker.

        Returns:
            True if message is a duplicate, False otherwise.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = f"dedup:{message_id}"
        
        # Try to set key with NX (only if not exists)
        was_set = await self.client.set(key, "1", nx=True, ex=ttl_seconds)
        
        # If set succeeded, it's not a duplicate
        return not bool(was_set)

    # Active Timeouts

    async def set_active_timeout(
        self, user_id: int, expires_at: datetime
    ) -> None:
        """Mark user as actively timed out.

        Args:
            user_id: Discord user ID.
            expires_at: Timeout expiration timestamp.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = f"timeout:{user_id}"
        ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        
        if ttl > 0:
            await self.client.setex(key, ttl, expires_at.isoformat())

    async def is_user_timed_out(self, user_id: int) -> bool:
        """Check if user is currently timed out.

        Args:
            user_id: Discord user ID.

        Returns:
            True if user has an active timeout, False otherwise.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = f"timeout:{user_id}"
        exists = await self.client.exists(key)
        return bool(exists)

    async def clear_timeout(self, user_id: int) -> None:
        """Clear user's timeout marker.

        Args:
            user_id: Discord user ID.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        key = f"timeout:{user_id}"
        await self.client.delete(key)

    # Brigade Detection

    async def track_join_event(self, user_id: int, timestamp: datetime) -> int:
        """Track user join event for brigade detection.

        Args:
            user_id: Discord user ID.
            timestamp: Join timestamp.

        Returns:
            Number of joins in the current minute.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        # Use minute as key granularity
        minute_key = timestamp.strftime("%Y%m%d%H%M")
        key = f"brigade:joins:{minute_key}"
        
        pipe = self.client.pipeline()
        pipe.sadd(key, user_id)
        pipe.expire(key, 600)  # Keep for 10 minutes
        pipe.scard(key)
        
        results = await pipe.execute()
        return results[2]  # scard result

    async def track_similar_message(
        self, content: str, user_id: int, timestamp: datetime
    ) -> int:
        """Track similar messages for brigade detection.

        Uses content hash to identify similar messages.

        Args:
            content: Message content.
            user_id: Discord user ID.
            timestamp: Message timestamp.

        Returns:
            Number of users who sent similar messages in window.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        # Hash message content
        content_hash = hashlib.md5(content.lower().strip().encode()).hexdigest()[:12]
        minute_key = timestamp.strftime("%Y%m%d%H%M")
        key = f"brigade:messages:{minute_key}:{content_hash}"
        
        pipe = self.client.pipeline()
        pipe.sadd(key, user_id)
        pipe.expire(key, 600)  # Keep for 10 minutes
        pipe.scard(key)
        
        results = await pipe.execute()
        return results[2]

    async def get_recent_joins(self, minutes: int = 5) -> set[int]:
        """Get all user IDs that joined recently.

        Args:
            minutes: Number of minutes to look back.

        Returns:
            Set of user IDs that joined in the time window.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        now = datetime.now(timezone.utc)
        user_ids: set[int] = set()
        
        for i in range(minutes):
            timestamp = now - timedelta(minutes=i)
            minute_key = timestamp.strftime("%Y%m%d%H%M")
            key = f"brigade:joins:{minute_key}"
            
            members = await self.client.smembers(key)
            user_ids.update(int(uid) for uid in members)
        
        return user_ids

    # Caching

    async def cache_set(
        self, key: str, value: Any, ttl_seconds: int = 3600
    ) -> None:
        """Cache a value with TTL.

        Args:
            key: Cache key.
            value: Value to cache (will be JSON serialized).
            ttl_seconds: Time to live in seconds.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        serialized = json.dumps(value)
        await self.client.setex(f"cache:{key}", ttl_seconds, serialized)

    async def cache_get(self, key: str) -> Any | None:
        """Get cached value.

        Args:
            key: Cache key.

        Returns:
            Cached value (deserialized from JSON), or None if not found.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        value = await self.client.get(f"cache:{key}")
        if value is None:
            return None
        
        return json.loads(value)

    async def cache_delete(self, key: str) -> None:
        """Delete cached value.

        Args:
            key: Cache key.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")

        await self.client.delete(f"cache:{key}")

    # Health Check

    async def health_check(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis is accessible, False otherwise.
        """
        try:
            if self.client is None:
                return False
            return await self.client.ping()
        except Exception:
            return False

    # Cleanup

    async def cleanup_expired_data(self) -> None:
        """Clean up expired brigade detection data.

        This is a maintenance task that should be run periodically.
        Uses SCAN instead of KEYS for production safety.

        Raises:
            redis.RedisError: If Redis operation fails.
        """
        if self.client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=10)
        
        patterns = ["brigade:joins:*", "brigade:messages:*"]
        
        for pattern in patterns:
            cursor = 0
            while True:
                # Use SCAN instead of KEYS for production safety
                cursor, keys = await self.client.scan(cursor, match=pattern, count=100)
                
                for key in keys:
                    try:
                        # Parse timestamp from key (format: brigade:joins:YYYYMMDDHHMM)
                        parts = key.split(":")
                        if len(parts) >= 3:
                            timestamp_str = parts[-1]
                            # Check if it's a valid timestamp format
                            if timestamp_str.isdigit() and len(timestamp_str) == 12:
                                key_time = datetime.strptime(timestamp_str, "%Y%m%d%H%M")
                                # Make it timezone-aware for comparison
                                key_time = key_time.replace(tzinfo=timezone.utc)
                                
                                if key_time < cutoff:
                                    await self.client.delete(key)
                    except (ValueError, IndexError):
                        # Skip malformed keys
                        pass
                
                # SCAN returns 0 when iteration is complete
                if cursor == 0:
                    break