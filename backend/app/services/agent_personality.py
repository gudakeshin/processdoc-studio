"""Agent personality system for Sheldon - energetic execution partner.

Provides personality-infused message generation across the system with:
- Contextual catchphrases
- Strategic insights and wisdom
- Progress celebration markers
- Visual flair with emoji
"""

from typing import Dict, List, Optional


class AgentPersonality:
    """Sheldon - your energetic execution partner."""

    name = "Sheldon"
    role = "Your execution partner"

    # Context-specific catchphrases
    CATCHPHRASES = {
        "start_planning": [
            "Let's map this out!",
            "Time to architect!",
            "Let's think strategically...",
            "Alright, let's design this!",
        ],
        "confirming_plan": [
            "Blueprint locked in! 🎯",
            "Plan confirmed—let's ship it!",
            "Ready to build?",
            "We're locked and loaded!",
        ],
        "starting_execution": [
            "Here we go! 🚀",
            "Execution time!",
            "Let's make this happen...",
            "Time to work our magic!",
        ],
        "hitting_milestone": [
            "🎉 Milestone hit!",
            "Progress check—we're cooking!",
            "Nice work on that step!",
            "Momentum building!",
        ],
        "successful_completion": [
            "🚢 Shipped!",
            "Success! ✨",
            "We did it! Beautiful work.",
            "That's a wrap! 🌟",
        ],
        "handling_issue": [
            "Quick pivot needed",
            "Found a snag—let's fix it",
            "Opportunity to improve",
            "Hiccup spotted—but we got this",
        ],
        "insight_trigger": [
            "Here's what I'm seeing...",
            "Pattern note:",
            "Worth considering...",
            "Strategic angle here:",
        ],
    }

    # Celebration emoji pool
    CELEBRATION_EMOJI = ["🎯", "✨", "🚀", "💪", "🔥", "⚡", "🎉"]

    # Progress markers for visual clarity
    PROGRESS_MARKERS = {
        "phase_start": "→",
        "phase_complete": "✓",
        "milestone": "🎯",
        "success": "✨",
        "checkpoint": "📋",
        "ready": "→",
        "issue": "⚠️",
    }

    # Strategic insight templates
    INSIGHT_TEMPLATES = {
        "strategic_observation": "Here's what stands out to me: {insight}",
        "pattern_recognition": "Pattern I'm seeing: {insight}",
        "recommendation": "Worth considering: {insight}",
        "opportunity": "Opportunity here: {insight}",
    }

    @classmethod
    def get_catchphrase(cls, context: str) -> str:
        """Get a catchphrase for the given context.

        Args:
            context: One of the keys in CATCHPHRASES dict
                    (e.g., "start_planning", "confirming_plan")

        Returns:
            A catchphrase string, or empty string if context not found
        """
        phrases = cls.CATCHPHRASES.get(context, [])
        if not phrases:
            return ""
        # Return first phrase (can be randomized later)
        return phrases[0]

    @classmethod
    def get_insight(cls, insight_type: str, insight_text: str) -> str:
        """Format a strategic insight with personality.

        Args:
            insight_type: Type of insight (strategic_observation, pattern_recognition, etc.)
            insight_text: The actual insight content

        Returns:
            Formatted insight string
        """
        template = cls.INSIGHT_TEMPLATES.get(
            insight_type,
            cls.INSIGHT_TEMPLATES["strategic_observation"]
        )
        return template.format(insight=insight_text)


def format_plan_with_personality(
    plan_summary: str,
    outputs: List[str],
    custom_outputs: Optional[List[str]] = None,
    rationale: Optional[str] = None,
) -> str:
    """Format a plan with Jimmy's personality.

    Args:
        plan_summary: Core plan description
        outputs: List of output types (e.g., ["pptx", "docx"])
        custom_outputs: Optional custom output definitions
        rationale: Optional reasoning for the plan

    Returns:
        Personality-infused plan message
    """
    catchphrase = AgentPersonality.get_catchphrase("confirming_plan")
    progress_marker = AgentPersonality.PROGRESS_MARKERS["milestone"]

    lines = [
        f"{progress_marker} **Plan Ready**",
        f"Here's our blueprint: {plan_summary}",
        "",
    ]

    if rationale:
        lines.append(f"**Why this approach:** {rationale}")
        lines.append("")

    # Format deliverables
    if outputs:
        outputs_str = ", ".join(f"**{out}**" for out in outputs)
        lines.append(f"**Deliverables:** {outputs_str}")

    if custom_outputs:
        custom_str = ", ".join(custom_outputs)
        lines.append(f"**Add-ons:** {custom_str}")

    lines.append("")
    lines.append(f"**We're set!** {catchphrase} No blockers—let's confirm and ship this.")

    return "\n".join(lines)


def add_milestone_celebration(message: str, milestone_type: str = "success") -> str:
    """Add celebration markers to a message.

    Args:
        message: The base message
        milestone_type: Type of milestone (success, checkpoint, milestone)

    Returns:
        Message with celebration markers
    """
    marker = AgentPersonality.PROGRESS_MARKERS.get(milestone_type, "✨")
    if not message.startswith(marker):
        return f"{marker} {message}"
    return message


def format_question_with_personality(question: str, context_hint: str = "") -> str:
    """Format a decision question with personality.

    Args:
        question: The core question
        context_hint: Optional hint about context/importance

    Returns:
        Personality-infused question
    """
    if context_hint:
        return f"🎯 {question} ({context_hint})"
    return f"🎯 {question}"


def format_remediation_with_personality(
    issues: List[str],
    action_items: List[str],
) -> str:
    """Format QA remediation feedback with collaborative personality.

    Args:
        issues: List of issues found
        action_items: List of specific fixes needed

    Returns:
        Supportive remediation message
    """
    catchphrase = AgentPersonality.get_catchphrase("handling_issue")
    progress_marker = AgentPersonality.PROGRESS_MARKERS["issue"]

    lines = [
        f"{progress_marker} **Quick optimization round:**",
        f"We're close! {catchphrase}. A few targeted fixes and we're golden:",
        "",
    ]

    # Format action items with visual markers
    for item in action_items:
        lines.append(f"→ {item}")

    lines.append("")
    lines.append("Let's make it shine! 🚀")

    return "\n".join(lines)


def format_insight_with_personality(
    insight_text: str,
    insight_type: str = "strategic_observation",
) -> str:
    """Format an insight with strategic personality.

    Args:
        insight_text: The insight content
        insight_type: Type of insight (strategic_observation, pattern_recognition, etc.)

    Returns:
        Formatted insight
    """
    return AgentPersonality.get_insight(insight_type, insight_text)


def format_success_message(message: str, details: Optional[str] = None) -> str:
    """Format a success message with celebration.

    Args:
        message: Core success message
        details: Optional additional details

    Returns:
        Celebratory success message
    """
    catchphrase = AgentPersonality.get_catchphrase("successful_completion")

    lines = [
        f"✨ **{message}**",
        catchphrase,
    ]

    if details:
        lines.append("")
        lines.append(details)

    return "\n".join(lines)


def inject_personality_markers(text: str, context: str = "checkpoint") -> str:
    """Inject personality markers into existing text.

    Args:
        text: The text to enhance
        context: Context for marker selection (checkpoint, milestone, etc.)

    Returns:
        Text with injected personality markers
    """
    marker = AgentPersonality.PROGRESS_MARKERS.get(context, "→")
    return f"{marker} {text}"


def format_phase_transition(
    phase_name: str,
    description: str = "",
) -> str:
    """Format a phase transition message with energy.

    Args:
        phase_name: Name of the phase starting
        description: Optional description

    Returns:
        Energetic phase transition message
    """
    catchphrase = AgentPersonality.get_catchphrase("starting_execution")
    marker = AgentPersonality.PROGRESS_MARKERS["phase_start"]

    lines = [
        f"{marker} **{phase_name}**",
    ]

    if description:
        lines.append(description)

    lines.append(f"{catchphrase}")

    return "\n".join(lines)
