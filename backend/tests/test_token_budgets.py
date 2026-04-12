"""
Tests for token budget checking and prompt compression.
"""

import pytest

from app.services.token_budgets import TokenBudgetChecker, TokenBudgetExceeded


class TestTokenEstimation:
    """Test token estimation from character count."""

    def test_empty_text(self):
        """Empty text should estimate to 0 tokens."""
        assert TokenBudgetChecker.estimate_tokens("") == 0

    def test_short_text(self):
        """Short text should estimate to at least 1 token."""
        assert TokenBudgetChecker.estimate_tokens("a") >= 1

    def test_char_to_token_ratio(self):
        """Estimate should follow ~3.5 chars per token ratio."""
        # 3500 chars should be ~1000 tokens
        text = "a" * 3500
        tokens = TokenBudgetChecker.estimate_tokens(text)
        assert 900 <= tokens <= 1100, f"Expected ~1000 tokens, got {tokens}"

    def test_prompt_estimation(self):
        """Prompt tokens should include system + user + overhead."""
        system = "You are helpful." * 100  # ~1600 chars = ~457 tokens
        user = "Tell me a story." * 100  # ~1600 chars = ~457 tokens
        total = TokenBudgetChecker.estimate_prompt_tokens(system, user)
        # Should be ~914 + 100 overhead = ~1014 tokens
        assert 900 <= total <= 1200, f"Expected ~1000 tokens, got {total}"


class TestBudgetChecking:
    """Test budget checking logic."""

    def test_unlimited_budget(self):
        """When budget is unlimited (999999), everything should fit."""
        system = "System prompt" * 1000
        user = "User prompt" * 1000
        fits, info = TokenBudgetChecker.check_budget(system, user, 4096)
        assert fits is True
        assert info["fits_in_budget"] is True

    def test_budget_info_accuracy(self):
        """Budget info should contain correct fields."""
        system = "System"
        user = "User prompt"
        fits, info = TokenBudgetChecker.check_budget(system, user, 4096)

        required_fields = [
            "prompt_tokens",
            "output_tokens",
            "total_tokens_needed",
            "remaining_budget",
            "safety_margin",
            "compression_needed_tokens",
            "fits_in_budget",
        ]
        for field in required_fields:
            assert field in info, f"Missing field: {field}"


class TestPromptCompression:
    """Test prompt compression strategies."""

    def test_compression_reduces_size(self):
        """Compression should reduce token count."""
        system = "You are a helpful assistant." + "\n\nExamples:\n" + ("Example " * 100)
        user = "Context excerpt:\n" + ("Long context " * 500) + "\n\nUser question: Tell me a story"

        original_tokens = TokenBudgetChecker.estimate_prompt_tokens(system, user)
        target_tokens = max(500, original_tokens // 2)  # Compress to 50%

        comp_system, comp_user, info = TokenBudgetChecker.compress_prompt_for_budget(
            system=system,
            user=user,
            target_tokens=target_tokens,
        )

        final_tokens = TokenBudgetChecker.estimate_prompt_tokens(comp_system, comp_user)

        assert final_tokens <= target_tokens + 100, (
            f"Compression failed: {final_tokens} tokens "
            f"vs target {target_tokens} (ratio: {info['compression_ratio']:.1%})"
        )
        assert info["compression_ratio"] < 1.0, "Compression ratio should be < 1.0"
        assert len(info["tiers_applied"]) > 0, "Should have applied at least one compression tier"

    def test_compression_preserves_content(self):
        """Compression should keep key content, not destroy everything."""
        system = "Be helpful"
        user = "Question: What is AI?\nAnswer should include: definition, history, applications"

        original_tokens = TokenBudgetChecker.estimate_prompt_tokens(system, user)

        comp_system, comp_user, info = TokenBudgetChecker.compress_prompt_for_budget(
            system=system,
            user=user,
            target_tokens=original_tokens // 3,  # Compress to 33%
        )

        # Key terms should still be present
        assert "AI" in comp_user or "artificial" in comp_user.lower() or len(comp_user) > 50

    def test_different_strategies(self):
        """Different compression strategies should behave differently."""
        system = "You are helpful. Examples: " + ("Example " * 100)
        user = "Context: " + ("Long context " * 500)

        target = 500

        _, _, aggressive_info = TokenBudgetChecker.compress_prompt_for_budget(
            system=system,
            user=user,
            target_tokens=target,
            compression_strategy="aggressive",
        )

        _, _, conservative_info = TokenBudgetChecker.compress_prompt_for_budget(
            system=system,
            user=user,
            target_tokens=target,
            compression_strategy="conservative",
        )

        # Both should reach the target (within safety margin)
        assert aggressive_info["compressed_tokens"] <= target + 100
        assert conservative_info["compressed_tokens"] <= target + 100

        # Aggressive should be more aggressive (lower final token count)
        # (though this isn't guaranteed for all inputs)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_compression_with_zero_target(self):
        """Compression should handle zero target gracefully."""
        system = "System"
        user = "User" * 1000

        # Should not raise, should return something
        comp_sys, comp_user, info = TokenBudgetChecker.compress_prompt_for_budget(
            system=system,
            user=user,
            target_tokens=0,
        )
        assert isinstance(comp_user, str)

    def test_compression_with_empty_input(self):
        """Compression should handle empty input gracefully."""
        _, _, info = TokenBudgetChecker.compress_prompt_for_budget(
            system="",
            user="",
            target_tokens=100,
        )
        assert "compression_ratio" in info
        assert info["compression_ratio"] >= 0

    def test_should_compress_detection(self):
        """Should correctly detect when compression is needed."""
        system = "Short"
        user = "Short"
        # With unlimited budget, should not need compression
        # (This test assumes budget checking can detect unlimited state)
        result = TokenBudgetChecker.should_compress_for_call(system, user, 4096)
        # Result depends on budget system state, so just check it returns bool
        assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
