"""
Token budget checking and intelligent prompt compression.

Provides pre-call budget verification and Cowork-style prompt compression
to keep API calls within token budget constraints.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings
from app.services.observability import increment

logger = logging.getLogger(__name__)


class TokenBudgetExceeded(Exception):
    """Raised when a prompt would exceed the remaining token budget."""

    pass


class TokenBudgetChecker:
    """Pre-call budget verification and intelligent prompt compression."""

    # Token estimation: empirically ~3.5 characters per token
    CHARS_PER_TOKEN = 3.5

    # Safety margin to account for estimation errors
    SAFETY_MARGIN_TOKENS = 100

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate tokens from character count.

        Uses empirical ratio of ~3.5 chars/token (more accurate than /4).
        """
        if not text:
            return 0
        return max(1, int(len(text) / TokenBudgetChecker.CHARS_PER_TOKEN))

    @staticmethod
    def estimate_prompt_tokens(system: str, user: str) -> int:
        """
        Estimate total prompt tokens (system + user + overhead).

        Includes overhead for message framing and stop sequences.
        """
        system_tokens = TokenBudgetChecker.estimate_tokens(system)
        user_tokens = TokenBudgetChecker.estimate_tokens(user)
        overhead = 100  # Message framing, stop sequences, etc.
        return system_tokens + user_tokens + overhead

    @staticmethod
    def get_remaining_budget() -> int:
        """
        Get remaining tokens in current run's budget.

        Returns:
            Remaining tokens, or unlimited (999999) if budgeting disabled.
        """
        from app.services.run_budget import get_remaining_token_budget

        try:
            remaining = get_remaining_token_budget()
            if remaining is None or remaining <= 0:
                return 999999  # Unlimited
            return remaining
        except Exception:
            # Budgeting not active or error retrieving budget
            return 999999

    @staticmethod
    def check_budget(
        system: str,
        user: str,
        needed_output_tokens: int = 4096,
        throw_on_exceed: bool = False,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Check if an API call would fit within remaining budget.

        Args:
            system: System prompt text
            user: User prompt text
            needed_output_tokens: Expected output tokens (default 4096)
            throw_on_exceed: If True, raise TokenBudgetExceeded when over budget

        Returns:
            (fits_in_budget: bool, {
                'prompt_tokens': int,
                'output_tokens': int,
                'total_tokens_needed': int,
                'remaining_budget': int,
                'safety_margin': int,
                'compression_needed_tokens': int,  # tokens to remove
            })
        """
        remaining = TokenBudgetChecker.get_remaining_budget()
        prompt_tokens = TokenBudgetChecker.estimate_prompt_tokens(system, user)
        output_tokens = int(needed_output_tokens or 4096)
        total_needed = prompt_tokens + output_tokens + TokenBudgetChecker.SAFETY_MARGIN_TOKENS

        compression_needed = max(0, total_needed - remaining)
        fits = compression_needed == 0

        info = {
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens_needed": total_needed,
            "remaining_budget": remaining,
            "safety_margin": TokenBudgetChecker.SAFETY_MARGIN_TOKENS,
            "compression_needed_tokens": compression_needed,
            "fits_in_budget": fits,
        }

        if throw_on_exceed and not fits and remaining < 1000:
            raise TokenBudgetExceeded(
                f"Prompt ({prompt_tokens} tokens) + output ({output_tokens} tokens) "
                f"+ safety margin ({TokenBudgetChecker.SAFETY_MARGIN_TOKENS} tokens) "
                f"= {total_needed} tokens needed, but only {remaining} tokens remaining"
            )

        return fits, info

    @staticmethod
    def compress_prompt_for_budget(
        system: str,
        user: str,
        target_tokens: int,
        compression_strategy: str = "aggressive",
    ) -> tuple[str, str, dict[str, Any]]:
        """
        Intelligently compress system and user prompts to fit token budget.

        Implements 5-tier compression:
        1. Trim verbose examples from system prompt
        2. Compress context excerpts to summaries
        3. Reduce user instruction to essentials
        4. Simplify structured data (ProcessModel JSON)
        5. Hard truncation with safety buffer

        Args:
            system: System prompt text
            user: User prompt text
            target_tokens: Target token budget (after compression)
            compression_strategy: "conservative" (safe) or "aggressive" (more compression)

        Returns:
            (compressed_system, compressed_user, {
                'original_tokens': int,
                'compressed_tokens': int,
                'original_chars': int,
                'compressed_chars': int,
                'compression_ratio': float,
                'tiers_applied': [str],
                'removed_elements': [str],
            })
        """
        increment("prompt_compression_applied_total")

        original_system = system
        original_user = user
        original_system_tokens = TokenBudgetChecker.estimate_tokens(system)
        original_user_tokens = TokenBudgetChecker.estimate_tokens(user)
        original_total_tokens = original_system_tokens + original_user_tokens

        removed_elements: list[str] = []
        tiers_applied: list[str] = []

        # Tier 1: Trim verbose examples from system prompt
        if "Examples:" in system or "Example:" in system:
            system_lines = system.split("\n")
            new_lines: list[str] = []
            in_examples = False
            for line in system_lines:
                if "Example" in line and (":" in line or line.strip().endswith("Examples")):
                    in_examples = True
                    continue
                if in_examples and line.strip() and not line.startswith(" "):
                    in_examples = False
                if not in_examples:
                    new_lines.append(line)

            compressed_system = "\n".join(new_lines)
            if compressed_system.strip() and len(compressed_system) < len(system):
                system = compressed_system
                tiers_applied.append("trim_system_examples")
                removed_elements.append("verbose examples from system prompt")

        # Tier 2: Compress context excerpts in user prompt
        if "Context excerpt:" in user or "context excerpt" in user.lower():
            user_parts: list[str] = []
            current_pos = 0

            while True:
                # Find context section
                ctx_idx = user.find("context excerpt", current_pos)
                if ctx_idx == -1:
                    user_parts.append(user[current_pos:])
                    break

                # Find the start of context content (after the label)
                content_start = user.find("\n", ctx_idx) + 1
                if content_start == 0:
                    user_parts.append(user[current_pos:])
                    break

                # Add everything up to context
                user_parts.append(user[current_pos:content_start])

                # Find next section start
                next_section = len(user)
                for marker in ["\n##", "\n---", "\nProcessModel", "\nJSON"]:
                    idx = user.find(marker, content_start)
                    if idx != -1 and idx < next_section:
                        next_section = idx

                # Extract context
                context_content = user[content_start:next_section]

                # Compress to first 2000 chars (bullet points)
                if len(context_content) > 2000:
                    lines = context_content.split("\n")
                    # If we have very few lines (content is not newline-separated), truncate by chars
                    if len(lines) < 5:
                        # Content is mostly one line or tightly packed
                        compressed = context_content[:1500]
                        compressed += "\n[...context truncated for token budget...]"
                    else:
                        # Normal case: newline-separated content
                        compressed = "\n".join(lines[:15])  # Keep first 15 lines
                        compressed += "\n[...context truncated for token budget...]"
                    user_parts.append(compressed)
                    tiers_applied.append("compress_context_excerpts")
                    removed_elements.append("context excerpt details (kept key points)")
                else:
                    user_parts.append(context_content)

                current_pos = next_section

            user = "".join(user_parts)

        # Tier 3: Reduce user instruction to first 2KB
        if "user instruction" in user.lower() or "instruction" in user.lower():
            instruction_idx = user.lower().find("instruction")
            if instruction_idx != -1:
                # Find instruction section and truncate to 2000 chars
                section_start = user.rfind("\n", 0, instruction_idx)
                section_end = user.find("\n\n", instruction_idx + 200)
                if section_end == -1:
                    section_end = len(user)

                instruction_section = user[section_start:section_end]
                if len(instruction_section) > 2000:
                    truncated = instruction_section[:2000] + "\n[...instruction details truncated...]"
                    user = user[:section_start] + truncated + user[section_end:]
                    tiers_applied.append("reduce_user_instruction")
                    removed_elements.append("detailed user instruction (kept summary)")

        # Tier 4: Simplify ProcessModel JSON
        if '"process_name"' in user or "ProcessModel" in user:
            # Find JSON block
            import json
            json_idx = user.find("{")
            if json_idx != -1:
                json_end = user.rfind("}")
                if json_end > json_idx:
                    try:
                        json_str = user[json_idx:json_end + 1]
                        data = json.loads(json_str)

                        # Keep only essential fields
                        simplified = {
                            "process_name": data.get("process_name"),
                            "steps": data.get("steps", [])[:10],  # First 10 steps
                            "roles": data.get("roles", []),
                            "decisions": data.get("decisions", [])[:5],  # First 5 decisions
                        }
                        simplified_json = json.dumps(simplified, ensure_ascii=False)
                        if len(simplified_json) < len(json_str):
                            user = user[:json_idx] + simplified_json + user[json_end + 1:]
                            tiers_applied.append("simplify_processmodel_json")
                            removed_elements.append("optional ProcessModel fields")
                    except json.JSONDecodeError:
                        pass  # Not valid JSON, skip

        # Check current token count
        current_system_tokens = TokenBudgetChecker.estimate_tokens(system)
        current_user_tokens = TokenBudgetChecker.estimate_tokens(user)
        current_total_tokens = current_system_tokens + current_user_tokens

        # Tier 5: Hard truncation with safety margin
        # Note: target_tokens includes the 100-token overhead from estimate_prompt_tokens
        # So we need to compress content to (target_tokens - overhead) to stay within budget
        content_target_tokens = target_tokens - TokenBudgetChecker.SAFETY_MARGIN_TOKENS
        if current_total_tokens > content_target_tokens:
            # How much we need to remove (in tokens)
            tokens_to_remove = current_total_tokens - content_target_tokens
            # Conservative: remove 30% more tokens than calculated to account for marker overhead
            target_user_tokens = TokenBudgetChecker.estimate_tokens(user) - int(tokens_to_remove * 1.3)
            target_user_chars = int(max(1000, target_user_tokens * TokenBudgetChecker.CHARS_PER_TOKEN))

            if len(user) > target_user_chars:
                if compression_strategy == "aggressive":
                    # Keep first 40%, last 10%
                    first_chars = int(target_user_chars * 0.4)
                    last_chars = int(target_user_chars * 0.1)
                    user = (
                        user[:first_chars]
                        + "\n[...content truncated for token budget...]\n"
                        + user[-last_chars:]
                    )
                    tiers_applied.append("hard_truncation_aggressive")
                    removed_elements.append("bulk user prompt content (kept beginning and end)")
                else:
                    # Conservative: keep first 60%, last 20%
                    first_chars = int(target_user_chars * 0.6)
                    last_chars = int(target_user_chars * 0.2)
                    user = (
                        user[:first_chars]
                        + "\n[...content truncated for token budget...]\n"
                        + user[-last_chars:]
                    )
                    tiers_applied.append("hard_truncation_conservative")
                    removed_elements.append("bulk user prompt content (kept beginning and end)")

        # Calculate final metrics
        final_system_tokens = TokenBudgetChecker.estimate_tokens(system)
        final_user_tokens = TokenBudgetChecker.estimate_tokens(user)
        final_total_tokens = final_system_tokens + final_user_tokens
        compression_ratio = (
            final_total_tokens / original_total_tokens if original_total_tokens > 0 else 1.0
        )

        info = {
            "original_tokens": original_total_tokens,
            "original_system_tokens": original_system_tokens,
            "original_user_tokens": original_user_tokens,
            "original_chars": len(original_system) + len(original_user),
            "compressed_tokens": final_total_tokens,
            "compressed_system_tokens": final_system_tokens,
            "compressed_user_tokens": final_user_tokens,
            "compressed_chars": len(system) + len(user),
            "compression_ratio": round(compression_ratio, 3),
            "tiers_applied": tiers_applied,
            "removed_elements": removed_elements,
        }

        logger.info(
            f"Prompt compression: {original_total_tokens} → {final_total_tokens} tokens "
            f"({info['compression_ratio']:.1%}), tiers: {', '.join(tiers_applied)}"
        )

        return system, user, info

    @staticmethod
    def should_compress_for_call(system: str, user: str, needed_output_tokens: int = 4096) -> bool:
        """
        Determine if prompt compression should be applied for this call.

        Returns True if call would exceed remaining budget.
        """
        fits, _ = TokenBudgetChecker.check_budget(system, user, needed_output_tokens)
        return not fits
