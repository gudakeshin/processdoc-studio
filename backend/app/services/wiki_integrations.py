"""
Wiki integrations with existing ProcessDoc v2 systems.

Connects wiki operations to memory items, run events, conversations, and coordinator.
Enables automatic knowledge capture and bidirectional learning across the platform.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WikiMemoryIntegration:
    """Integrate wiki with memory items (facts, preferences, decisions, constraints)."""

    @staticmethod
    def ingest_memory_item_to_wiki(
        memory_item: Dict[str, Any],
        wiki_type: str = "project",
        project_id: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Convert a MemoryItem to a wiki page and add to wiki.

        Args:
            memory_item: Memory item record (id, type, content, metadata)
            wiki_type: "leading_practice" or "project"
            project_id: Project ID for project wikis

        Returns:
            Tuple[wiki_page_dict, error_string]
        """
        try:
            # Handle empty/missing memory item
            if not memory_item:
                memory_item = {}

            # Extract memory item fields
            item_id = memory_item.get("id", "unknown")
            item_type = memory_item.get("type", "concept")  # "fact", "preference", "decision", "constraint"
            content = memory_item.get("content", "")
            metadata = memory_item.get("metadata") or {}

            # Map memory type to wiki category
            category_map = {
                "fact": "entity",
                "preference": "decision",
                "decision": "decision",
                "constraint": "concept",
            }
            category = category_map.get(item_type, "concept")

            # Create wiki page from memory item
            wiki_page = {
                "title": metadata.get("title", f"{item_type.title()}: {content[:50]}"),
                "category": category,
                "content": content,
                "source_memory_ids": [item_id],
                "confidence": metadata.get("confidence", "medium"),
                "source_count": 1,
                "frontmatter": json.dumps({
                    "category": category,
                    "source_count": 1,
                    "confidence": metadata.get("confidence", "medium"),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "source_memory_id": item_id,
                    "memory_type": item_type,
                }),
            }

            logger.info(f"Created wiki page from memory item {item_id} ({item_type})")
            return wiki_page, None

        except Exception as e:
            logger.error(f"Failed to ingest memory item: {e}")
            return None, str(e)

    @staticmethod
    def sync_memory_item_updates_to_wiki(
        memory_item: Dict[str, Any],
        wiki_page: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Update wiki page when memory item changes.

        Args:
            memory_item: Updated memory item
            wiki_page: Existing wiki page to update

        Returns:
            Tuple[updated_wiki_page, error_string]
        """
        try:
            # Update page content from memory item
            wiki_page["content"] = memory_item.get("content", wiki_page.get("content", ""))
            wiki_page["title"] = memory_item.get("metadata", {}).get("title", wiki_page.get("title"))

            # Update frontmatter with new timestamp
            frontmatter = json.loads(wiki_page.get("frontmatter", "{}"))
            frontmatter["last_updated"] = datetime.now(timezone.utc).isoformat()
            wiki_page["frontmatter"] = json.dumps(frontmatter)

            logger.info(f"Updated wiki page from memory item {memory_item.get('id')}")
            return wiki_page, None

        except Exception as e:
            logger.error(f"Failed to sync memory item update: {e}")
            return None, str(e)


class WikiRunIntegration:
    """Integrate wiki with run events and artifacts."""

    @staticmethod
    def ingest_run_artifact_to_wiki(
        run_id: str,
        run_summary: Dict[str, Any],
        artifacts: List[Dict[str, Any]],
        project_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Ingest run artifacts and learnings into project wiki.

        Args:
            run_id: Run ID
            run_summary: Execution summary with outcomes
            artifacts: Output artifacts (process maps, financial models, etc.)
            project_id: Project ID

        Returns:
            Tuple[ingest_result, error_string]
        """
        try:
            pages_created = []
            errors = []

            # 1. Create overview page for run
            overview_page = {
                "title": f"Run {run_id}: {run_summary.get('name', 'Execution')}",
                "category": "artifact",
                "content": f"""
# Run Execution Summary

**Run ID:** {run_id}
**Date:** {run_summary.get('executed_at', 'N/A')}
**Status:** {run_summary.get('status', 'Unknown')}

## Outcomes
{run_summary.get('outcomes', 'No outcomes recorded')}

## Key Findings
{run_summary.get('key_findings', 'No findings recorded')}

## Next Steps
{run_summary.get('next_steps', 'None')}
""",
                "source_run_ids": [run_id],
                "confidence": "high",
                "frontmatter": json.dumps({
                    "category": "artifact",
                    "source_count": len(artifacts) + 1,
                    "confidence": "high",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "source_run_id": run_id,
                }),
            }
            pages_created.append(overview_page)

            # 2. Create pages for learnings
            learnings = run_summary.get("learnings", [])
            for learning in learnings:
                learning_page = {
                    "title": f"Learning: {learning.get('title', 'Untitled')}",
                    "category": "concept",
                    "content": learning.get("description", ""),
                    "source_run_ids": [run_id],
                    "confidence": "medium",
                    "frontmatter": json.dumps({
                        "category": "concept",
                        "source_count": 1,
                        "confidence": "medium",
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                        "source_run_id": run_id,
                    }),
                }
                pages_created.append(learning_page)

            # 3. Create artifact catalog page
            artifact_page = {
                "title": f"Run {run_id} Artifacts",
                "category": "artifact",
                "content": _generate_artifact_catalog(run_id, artifacts),
                "source_run_ids": [run_id],
                "confidence": "high",
                "frontmatter": json.dumps({
                    "category": "artifact",
                    "source_count": len(artifacts),
                    "confidence": "high",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }),
            }
            pages_created.append(artifact_page)

            result = {
                "pages_created": len(pages_created),
                "pages": pages_created,
                "run_id": run_id,
                "project_id": project_id,
            }

            logger.info(f"Ingested run {run_id} into wiki: {len(pages_created)} pages created")
            return result, None

        except Exception as e:
            logger.error(f"Failed to ingest run artifacts: {e}")
            return None, str(e)

    @staticmethod
    def extract_run_learnings(run_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract learnings and insights from run event log.

        Args:
            run_events: List of run events

        Returns:
            List of learning objects with title and description
        """
        learnings = []

        # Simple heuristic: extract events marked as "learning" or "insight"
        for event in run_events:
            event_type = event.get("event_type", "").lower()
            if "learning" in event_type or "insight" in event_type:
                learning = {
                    "title": event.get("summary", "Untitled Learning"),
                    "description": event.get("details", ""),
                    "timestamp": event.get("timestamp", ""),
                }
                learnings.append(learning)

        return learnings


class WikiConversationIntegration:
    """Integrate wiki with conversation history and digests."""

    @staticmethod
    def digest_conversation_to_wiki(
        conversation_id: str,
        messages: List[Dict[str, Any]],
        project_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Create a wiki page from conversation digest.

        Args:
            conversation_id: Conversation ID
            messages: List of conversation messages
            project_id: Project ID

        Returns:
            Tuple[wiki_page_dict, error_string]
        """
        try:
            # Generate summary from conversation
            summary = _summarize_conversation(messages)
            key_decisions = _extract_decisions_from_conversation(messages)
            questions = _extract_questions_from_conversation(messages)

            # Create wiki page
            content = f"""
# Conversation {conversation_id}

## Summary
{summary}

## Key Decisions
{format_list(key_decisions) if key_decisions else "None"}

## Questions Discussed
{format_list(questions) if questions else "None"}

## Messages
Total messages: {len(messages)}
Participants: {len(set(m.get('user_id') for m in messages))}
"""

            wiki_page = {
                "title": f"Conversation: {conversation_id}",
                "category": "synthesis",
                "content": content,
                "source_run_ids": [],  # Could add if conversation is part of a run
                "confidence": "medium",
                "frontmatter": json.dumps({
                    "category": "synthesis",
                    "source_count": len(messages),
                    "confidence": "medium",
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "conversation_id": conversation_id,
                    "message_count": len(messages),
                }),
            }

            logger.info(f"Created wiki page from conversation {conversation_id}")
            return wiki_page, None

        except Exception as e:
            logger.error(f"Failed to digest conversation: {e}")
            return None, str(e)


class WikiCoordinatorIntegration:
    """Integrate wiki with coordinator for run planning."""

    @staticmethod
    def query_wiki_for_context(
        question: str,
        wiki_type: str = "project",
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Query wiki to get context for coordinator planning.

        Args:
            question: Planning question or task description
            wiki_type: "leading_practice" or "project"
            project_id: Project ID

        Returns:
            Context dict with relevant pages and learnings
        """
        try:
            # This will be called by wiki_query_with_retry() in real implementation
            # For now, return stub context
            context = {
                "question": question,
                "relevant_pages": [],
                "past_learnings": [],
                "recommendations": [],
                "confidence": "low",  # No real query yet
            }

            logger.debug(f"Queried wiki for context: {question}")
            return context

        except Exception as e:
            logger.error(f"Failed to query wiki for context: {e}")
            return {"question": question, "error": str(e)}

    @staticmethod
    def apply_learnings_to_run_plan(
        plan: Dict[str, Any],
        wiki_learnings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Enhance run plan with learnings from wiki.

        Args:
            plan: Initial run plan
            wiki_learnings: Relevant learnings from wiki

        Returns:
            Enhanced plan with learning recommendations
        """
        try:
            # Add learning recommendations to plan
            plan["learning_recommendations"] = wiki_learnings
            plan["learning_count"] = len(wiki_learnings)

            # If learnings suggest avoiding certain approaches, flag them
            cautions = [l for l in wiki_learnings if "avoid" in l.get("title", "").lower()]
            if cautions:
                plan["cautions"] = cautions

            logger.info(f"Applied {len(wiki_learnings)} learnings to run plan")
            return plan

        except Exception as e:
            logger.error(f"Failed to apply learnings: {e}")
            return plan


class WikiLeadingPracticesIntegration:
    """Integrate wiki with leading practices service."""

    @staticmethod
    def get_leading_practices_from_wiki(
        topic: str,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve leading practices from LP wiki for a topic.

        Args:
            topic: Topic keyword
            category: Optional category filter

        Returns:
            List of relevant LP pages
        """
        try:
            # This will query the LP wiki
            # For now, return stub
            practices = {
                "topic": topic,
                "category": category,
                "pages": [],
                "count": 0,
            }

            logger.debug(f"Retrieved leading practices for {topic}")
            return practices

        except Exception as e:
            logger.error(f"Failed to retrieve leading practices: {e}")
            return {"topic": topic, "error": str(e)}

    @staticmethod
    def propose_learning_to_lp_wiki(
        project_wiki_page: Dict[str, Any],
        project_id: str,
    ) -> Tuple[bool, str]:
        """
        Propose a project learning as a new leading practice.

        Args:
            project_wiki_page: Page from project wiki to promote
            project_id: Source project ID

        Returns:
            Tuple[success, message]
        """
        try:
            # Create approval request for LP review
            proposal = {
                "source_project_id": project_id,
                "source_page_id": project_wiki_page.get("id"),
                "source_page_title": project_wiki_page.get("title"),
                "content": project_wiki_page.get("content"),
                "status": "pending_review",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(f"Proposed learning from {project_id} for LP wiki review")
            return True, f"Proposal created: {proposal['timestamp']}"

        except Exception as e:
            logger.error(f"Failed to propose learning: {e}")
            return False, str(e)


# ===== Helper Functions =====

def _generate_artifact_catalog(run_id: str, artifacts: List[Dict[str, Any]]) -> str:
    """Generate markdown catalog of run artifacts."""
    if not artifacts:
        return "No artifacts produced."

    catalog = "## Artifacts\n\n"
    for artifact in artifacts:
        name = artifact.get("name", "Unknown")
        artifact_type = artifact.get("type", "unknown")
        path = artifact.get("path", "")
        catalog += f"- **{name}** ({artifact_type})\n"
        if path:
            catalog += f"  - Path: `{path}`\n"

    return catalog


def _summarize_conversation(messages: List[Dict[str, Any]]) -> str:
    """Generate summary of conversation."""
    if not messages:
        return "No messages."

    # Simple approach: extract key topics from first and last messages
    first_topic = messages[0].get("content", "")[:100] if messages else ""
    last_msg = messages[-1].get("content", "")[:100] if messages else ""

    return f"Conversation with {len(messages)} messages covering discussion topics."


def _extract_decisions_from_conversation(messages: List[Dict[str, Any]]) -> List[str]:
    """Extract decisions from conversation."""
    decisions = []

    for msg in messages:
        content = msg.get("content", "").lower()
        if any(word in content for word in ["decided", "decision", "will", "agreed", "chose"]):
            decisions.append(msg.get("content", "")[:100])

    return decisions[:5]  # Top 5 decisions


def _extract_questions_from_conversation(messages: List[Dict[str, Any]]) -> List[str]:
    """Extract questions from conversation."""
    questions = []

    for msg in messages:
        content = msg.get("content", "")
        if content.strip().endswith("?"):
            questions.append(content[:100])

    return questions[:5]  # Top 5 questions


def format_list(items: List[str]) -> str:
    """Format list of items as markdown bullet list."""
    if not items:
        return "None"
    return "\n".join(f"- {item}" for item in items)
