"""Phase 3 Peer Messaging Tests.

Tests for teammate message queue, peer communication, and lead directives.
"""

import threading
import time
from unittest.mock import Mock

import pytest

from app.services.teammate_message_queue import (
    Message,
    TeammateMessageQueue,
    get_message_queue,
)


class TestTeammateMessage:
    """Test Message dataclass."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(
            from_teammate="t1",
            to_teammate="t2",
            body="Hello",
            message_type="message",
        )

        assert msg.from_teammate == "t1"
        assert msg.to_teammate == "t2"
        assert msg.body == "Hello"
        assert msg.message_type == "message"
        assert msg.id is not None
        assert msg.created_at > 0
        assert not msg.is_expired()

    def test_message_is_for_teammate_unicast(self):
        """Test message filtering for unicast."""
        msg = Message(from_teammate="t1", to_teammate="t2", body="Hello")

        assert msg.is_for_teammate("t2")
        assert not msg.is_for_teammate("t3")

    def test_message_is_for_teammate_broadcast(self):
        """Test message filtering for broadcast."""
        msg = Message(from_teammate="t1", to_teammate=None, body="Hello")

        assert msg.is_for_teammate("t2")
        assert msg.is_for_teammate("t3")
        assert msg.is_for_teammate("anyone")

    def test_message_expiration(self):
        """Test message expiration."""
        msg = Message(from_teammate="t1", body="Hello")
        msg.expires_at = time.time() - 1  # Expired

        assert msg.is_expired()

    def test_message_to_dict(self):
        """Test converting message to dict."""
        msg = Message(
            from_teammate="t1",
            to_teammate="t2",
            body="Hello",
            message_type="message",
        )

        d = msg.to_dict()
        assert d["from_teammate"] == "t1"
        assert d["to_teammate"] == "t2"
        assert d["body"] == "Hello"
        assert d["message_type"] == "message"


class TestTeammateMessageQueue:
    """Test TeammateMessageQueue."""

    def test_queue_initialization(self):
        """Test queue initialization."""
        queue = TeammateMessageQueue(max_queue_size=100, message_ttl_sec=3600)

        assert queue.max_queue_size == 100
        assert queue.message_ttl_sec == 3600
        assert len(queue.messages) == 0
        assert len(queue.subscriptions) == 0

    def test_send_unicast_message(self):
        """Test sending a unicast message."""
        queue = TeammateMessageQueue()

        msg = queue.send_message(
            from_teammate="t1",
            to_teammate="t2",
            body="Hello t2",
        )

        assert msg.from_teammate == "t1"
        assert msg.to_teammate == "t2"
        assert msg.body == "Hello t2"
        assert len(queue.messages) == 1

    def test_send_broadcast_message(self):
        """Test sending a broadcast message."""
        queue = TeammateMessageQueue()

        msg = queue.send_message(
            from_teammate="t1",
            body="Hello everyone",
            to_teammate=None,  # Broadcast
        )

        assert msg.to_teammate is None
        assert msg.body == "Hello everyone"

    def test_broadcast_directive(self):
        """Test broadcasting a directive."""
        queue = TeammateMessageQueue()

        msg = queue.broadcast_directive(
            from_teammate="lead",
            directive="Please process output",
            metadata={"action": "process"},
        )

        assert msg.from_teammate == "lead"
        assert msg.to_teammate is None
        assert msg.message_type == "directive"
        assert msg.metadata["action"] == "process"

    def test_subscribe_to_messages(self):
        """Test subscribing to messages."""
        queue = TeammateMessageQueue()
        callback = Mock()

        sub = queue.subscribe("t1", callback)

        assert sub.teammate_id == "t1"
        assert "t1" in queue.subscriptions
        assert sub in queue.subscriptions["t1"]

    def test_unsubscribe_from_messages(self):
        """Test unsubscribing from messages."""
        queue = TeammateMessageQueue()
        callback = Mock()
        sub = queue.subscribe("t1", callback)

        assert "t1" in queue.subscriptions

        queue.unsubscribe("t1", sub)

        assert "t1" not in queue.subscriptions

    def test_get_messages_since(self):
        """Test retrieving messages since last consumed."""
        queue = TeammateMessageQueue()

        # Send multiple messages
        queue.send_message("t1", "t2", "Hello 1")
        queue.send_message("t1", "t2", "Hello 2")
        queue.send_message("t1", "t2", "Hello 3")

        messages = queue.get_messages_since("t2")

        assert len(messages) == 3
        assert messages[0].body == "Hello 1"
        assert messages[2].body == "Hello 3"

    def test_get_messages_filters_by_recipient(self):
        """Test that get_messages filters by recipient."""
        queue = TeammateMessageQueue()

        queue.send_message("t1", "t2", "For t2")
        queue.send_message("t1", "t3", "For t3")
        queue.send_message("t1", None, "For everyone")

        messages_t2 = queue.get_messages_since("t2")
        messages_t3 = queue.get_messages_since("t3")

        # t2 should get 2 messages (one direct, one broadcast)
        assert len(messages_t2) == 2
        # t3 should get 2 messages (one direct, one broadcast)
        assert len(messages_t3) == 2

    def test_get_messages_respects_limit(self):
        """Test that get_messages respects limit parameter."""
        queue = TeammateMessageQueue()

        for i in range(10):
            queue.send_message("t1", "t2", f"Message {i}")

        messages = queue.get_messages_since("t2", limit=5)

        assert len(messages) == 5

    def test_wait_for_message_timeout(self):
        """Test waiting for message with timeout."""
        queue = TeammateMessageQueue()

        # Wait with short timeout
        msg = queue.wait_for_message("t1", timeout_sec=0.1)

        assert msg is None

    def test_wait_for_message_success(self):
        """Test waiting for message that arrives."""
        queue = TeammateMessageQueue()

        def send_delayed():
            time.sleep(0.05)
            queue.send_message("t1", "t2", "Delayed message")

        thread = threading.Thread(target=send_delayed, daemon=True)
        thread.start()

        msg = queue.wait_for_message("t2", timeout_sec=1.0)

        assert msg is not None
        assert msg.body == "Delayed message"

    def test_queue_cleanup_old_messages(self):
        """Test cleanup of old messages by creation time."""
        queue = TeammateMessageQueue()

        # Create message
        msg1 = queue.send_message("t1", "t2", "Current")

        # Manually create an old message by backdating its creation time
        import copy
        msg2 = copy.copy(msg1)
        msg2.body = "Old"
        msg2.created_at = time.time() - 100  # 100 seconds old
        queue.messages.append(msg2)

        assert len(queue.messages) == 2

        # Clear messages older than 60 seconds - should remove msg2
        cleared = queue.clear_messages(older_than_sec=60)

        assert cleared == 1
        assert len(queue.messages) == 1
        assert queue.messages[0].body == "Current"

    def test_queue_max_size_enforcement(self):
        """Test that queue enforces max size."""
        queue = TeammateMessageQueue(max_queue_size=5)

        for i in range(10):
            queue.send_message("t1", "t2", f"Message {i}")

        # Should keep only last 5
        assert len(queue.messages) <= 5

    def test_queue_stats(self):
        """Test getting queue statistics."""
        queue = TeammateMessageQueue()
        callback = Mock()

        queue.send_message("t1", "t2", "Message 1")
        queue.send_message("t1", "t2", "Message 2")
        queue.subscribe("t1", callback)
        queue.subscribe("t2", callback)

        stats = queue.get_queue_stats()

        assert stats["total_messages"] == 2
        assert stats["total_subscriptions"] == 2
        assert stats["subscribed_teammates"] == 2

    def test_callback_notification(self):
        """Test that callbacks are notified on new messages."""
        queue = TeammateMessageQueue()
        callback = Mock()

        queue.subscribe("t2", callback)
        queue.send_message("t1", "t2", "Hello")

        # Give notification thread time to run
        time.sleep(0.1)

        # Callback should have been called
        assert callback.called

    def test_message_correlation_id(self):
        """Test message correlation for request/response."""
        queue = TeammateMessageQueue()

        # Send request
        request = queue.send_message(
            "t1",
            "t2",
            "Can you process this?",
            message_type="message",
        )

        # Send response with correlation
        response = queue.send_message(
            "t2",
            "t1",
            "Yes, processing",
            message_type="response",
            correlation_id=request.id,
        )

        assert response.correlation_id == request.id

    def test_message_metadata(self):
        """Test message metadata."""
        queue = TeammateMessageQueue()

        msg = queue.send_message(
            "t1",
            "t2",
            "Process this",
            metadata={"priority": "high", "output_type": "docx"},
        )

        assert msg.metadata["priority"] == "high"
        assert msg.metadata["output_type"] == "docx"

    def test_get_message_queue_singleton(self):
        """Test that get_message_queue returns singleton."""
        queue1 = get_message_queue()
        queue2 = get_message_queue()

        assert queue1 is queue2

    def test_concurrent_send_and_receive(self):
        """Test concurrent message sending and receiving."""
        queue = TeammateMessageQueue()
        received_messages = []

        def send_messages():
            for i in range(3):
                queue.send_message("t1", "t2", f"Message {i}")
                time.sleep(0.02)

        def receive_messages():
            # Just collect messages that are available
            for _ in range(5):
                msgs = queue.get_messages_since("t2")
                received_messages.extend(msgs)
                if len(received_messages) >= 3:
                    break
                time.sleep(0.05)

        sender = threading.Thread(target=send_messages, daemon=True)
        receiver = threading.Thread(target=receive_messages, daemon=True)

        sender.start()
        receiver.start()

        sender.join(timeout=5)
        receiver.join(timeout=5)

        assert len(received_messages) >= 2  # At least some messages received


class TestMessageTypeFiltering:
    """Test filtering messages by type."""

    def test_subscribe_filters_by_type(self):
        """Test that subscription filters by message type."""
        queue = TeammateMessageQueue()
        callback = Mock()

        # Subscribe only to directives
        queue.subscribe("t1", callback, message_types={"directive"})

        # Send regular message - should not trigger callback
        queue.send_message("t2", "t1", "Hello", message_type="message")
        time.sleep(0.1)
        assert not callback.called

        # Send directive - should trigger callback
        queue.broadcast_directive("t2", "Process now")
        time.sleep(0.1)
        assert callback.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
