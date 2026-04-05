"""Peer messaging infrastructure for teammate communication.

Provides message queue system for:
- Teammate-to-teammate messages
- Lead broadcast directives
- Message subscription and delivery
- Message persistence
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_LOG = logging.getLogger(__name__)


@dataclass
class Message:
    """Represents a message in the queue."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_teammate: str = ""
    to_teammate: Optional[str] = None  # None = broadcast
    body: str = ""
    message_type: str = "message"  # message, directive, response
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    correlation_id: Optional[str] = None  # For request/response patterns
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if message has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_for_teammate(self, teammate_id: str) -> bool:
        """Check if message is for this teammate."""
        if self.to_teammate is None:
            return True  # Broadcast for all
        return self.to_teammate == teammate_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "from_teammate": self.from_teammate,
            "to_teammate": self.to_teammate,
            "body": self.body,
            "message_type": self.message_type,
            "created_at": self.created_at,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }


@dataclass
class TeammateSubscription:
    """Subscription for a teammate to receive messages."""

    teammate_id: str
    callback: Callable[[Message], None]
    created_at: float = field(default_factory=time.time)
    message_types: set[str] = field(default_factory=lambda: {"message", "directive"})

    def should_notify(self, message: Message) -> bool:
        """Check if message should trigger callback."""
        return (
            message.is_for_teammate(self.teammate_id)
            and message.message_type in self.message_types
        )


class TeammateMessageQueue:
    """Central message queue for teammate communication.

    Provides:
    - Message queue management (FIFO with TTL)
    - Subscriptions for real-time delivery
    - Broadcast messages for lead directives
    - Request/response correlation
    """

    def __init__(self, max_queue_size: int = 1000, message_ttl_sec: float = 3600.0):
        """Initialize message queue.

        Args:
            max_queue_size: Maximum messages in queue before expiry cleanup
            message_ttl_sec: Time-to-live for messages in seconds
        """
        self.max_queue_size = max_queue_size
        self.message_ttl_sec = message_ttl_sec

        self.messages: list[Message] = []  # FIFO queue
        self.subscriptions: dict[str, list[TeammateSubscription]] = {}  # teammate_id -> subscriptions
        self.lock = threading.Lock()
        self.last_consumed: dict[str, int] = {}  # teammate_id -> last message index consumed

        _LOG.info(f"TeammateMessageQueue initialized (max_size={max_queue_size}, ttl={message_ttl_sec}s)")

    def send_message(
        self,
        from_teammate: str,
        to_teammate: Optional[str],
        body: str,
        message_type: str = "message",
        correlation_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Send a message.

        Args:
            from_teammate: ID of sending teammate
            to_teammate: Recipient teammate ID (None = broadcast)
            body: Message content
            message_type: Type of message (message, directive, response)
            correlation_id: For linking request/response
            metadata: Additional context

        Returns:
            Message instance
        """
        with self.lock:
            message = Message(
                from_teammate=from_teammate,
                to_teammate=to_teammate,
                body=body,
                message_type=message_type,
                correlation_id=correlation_id,
                metadata=metadata or {},
            )

            # Add to queue
            self.messages.append(message)

            # Cleanup expired messages and enforce max size
            self._cleanup_expired()
            if len(self.messages) > self.max_queue_size:
                self.messages = self.messages[-self.max_queue_size :]

            # Notify subscribers
            self._notify_subscribers(message)

            _LOG.debug(
                f"Message sent: {from_teammate} → {to_teammate or 'broadcast'} "
                f"(type={message_type}, body_len={len(body)})"
            )

            return message

    def broadcast_directive(
        self,
        from_teammate: str,
        directive: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Message:
        """Broadcast a directive from lead to all teammates.

        Args:
            from_teammate: Lead teammate ID
            directive: Directive text
            metadata: Additional context (e.g., action, params)

        Returns:
            Message instance
        """
        return self.send_message(
            from_teammate=from_teammate,
            to_teammate=None,  # Broadcast
            body=directive,
            message_type="directive",
            metadata=metadata or {},
        )

    def subscribe(
        self,
        teammate_id: str,
        callback: Callable[[Message], None],
        message_types: Optional[set[str]] = None,
    ) -> TeammateSubscription:
        """Subscribe teammate to messages.

        Args:
            teammate_id: ID of teammate to notify
            callback: Function to call when message arrives
            message_types: Message types to subscribe to (default: all)

        Returns:
            TeammateSubscription instance
        """
        with self.lock:
            if message_types is None:
                message_types = {"message", "directive", "response"}

            sub = TeammateSubscription(
                teammate_id=teammate_id,
                callback=callback,
                message_types=message_types,
            )

            if teammate_id not in self.subscriptions:
                self.subscriptions[teammate_id] = []
            self.subscriptions[teammate_id].append(sub)

            _LOG.info(f"Teammate {teammate_id} subscribed to messages")
            return sub

    def unsubscribe(self, teammate_id: str, subscription: TeammateSubscription) -> None:
        """Unsubscribe teammate from messages.

        Args:
            teammate_id: ID of teammate
            subscription: Subscription to remove
        """
        with self.lock:
            if teammate_id in self.subscriptions:
                self.subscriptions[teammate_id] = [
                    s for s in self.subscriptions[teammate_id] if s != subscription
                ]
                if not self.subscriptions[teammate_id]:
                    del self.subscriptions[teammate_id]

            _LOG.info(f"Teammate {teammate_id} unsubscribed from messages")

    def get_messages_since(
        self,
        teammate_id: str,
        last_message_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Message]:
        """Get messages for teammate since last consumed.

        Args:
            teammate_id: ID of teammate
            last_message_id: Optional message ID to start after
            limit: Maximum messages to return

        Returns:
            List of messages
        """
        with self.lock:
            # Find starting index
            start_idx = 0
            if last_message_id:
                for i, msg in enumerate(self.messages):
                    if msg.id == last_message_id:
                        start_idx = i + 1
                        break

            # Get messages for this teammate
            messages = []
            for msg in self.messages[start_idx:]:
                if not msg.is_expired() and msg.is_for_teammate(teammate_id):
                    messages.append(msg)
                    if len(messages) >= limit:
                        break

            # Update last consumed
            if messages:
                self.last_consumed[teammate_id] = start_idx + len(messages) - 1

            return messages

    def wait_for_message(
        self,
        teammate_id: str,
        timeout_sec: float = 30.0,
        message_type: Optional[str] = None,
    ) -> Optional[Message]:
        """Wait for next message to arrive.

        Blocks until message arrives or timeout.

        Args:
            teammate_id: ID of teammate
            timeout_sec: Maximum wait time
            message_type: Optional filter by message type

        Returns:
            Message or None if timeout
        """
        start_time = time.time()
        last_count = len(self.messages)

        while time.time() - start_time < timeout_sec:
            with self.lock:
                # Check for new messages
                current_count = len(self.messages)
                if current_count > last_count:
                    for msg in self.messages[last_count:]:
                        if msg.is_for_teammate(teammate_id) and not msg.is_expired():
                            if message_type is None or msg.message_type == message_type:
                                return msg
                    last_count = current_count

            time.sleep(0.1)  # Poll interval

        return None

    def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics.

        Returns:
            Dictionary with queue stats
        """
        with self.lock:
            return {
                "total_messages": len(self.messages),
                "total_subscriptions": sum(len(subs) for subs in self.subscriptions.values()),
                "subscribed_teammates": len(self.subscriptions),
                "max_queue_size": self.max_queue_size,
                "message_ttl_sec": self.message_ttl_sec,
            }

    def clear_messages(self, older_than_sec: float = 3600.0) -> int:
        """Clear old messages.

        Args:
            older_than_sec: Messages older than this are removed

        Returns:
            Number of messages cleared
        """
        with self.lock:
            cutoff_time = time.time() - older_than_sec
            before_count = len(self.messages)
            self.messages = [m for m in self.messages if m.created_at > cutoff_time]
            after_count = len(self.messages)

            cleared = before_count - after_count
            if cleared > 0:
                _LOG.info(f"Cleared {cleared} old messages from queue")

            return cleared

    def _cleanup_expired(self) -> None:
        """Remove expired messages (called within lock)."""
        self.messages = [m for m in self.messages if not m.is_expired()]

    def _notify_subscribers(self, message: Message) -> None:
        """Notify subscribers of new message (called within lock)."""
        # Run callbacks in separate thread to avoid blocking queue operations
        def notify():
            for teammate_id, subs in self.subscriptions.items():
                for sub in subs:
                    if sub.should_notify(message):
                        try:
                            sub.callback(message)
                        except Exception as e:
                            _LOG.error(f"Error notifying {teammate_id}: {e}")

        thread = threading.Thread(target=notify, daemon=True)
        thread.start()


# Global singleton instance
_message_queue: Optional[TeammateMessageQueue] = None
_queue_lock = threading.Lock()


def get_message_queue() -> TeammateMessageQueue:
    """Get global message queue instance."""
    global _message_queue
    if _message_queue is None:
        with _queue_lock:
            if _message_queue is None:
                _message_queue = TeammateMessageQueue()
    return _message_queue
