"""
memory/smart_memory.py — Smart memory management with importance scoring.

Features:
- Importance scoring (1-10) for each memory
- Auto-summarization of memories with score < 4 after N days
- Maximum 50 high-importance memories per project
- TTL-based cleanup: low-value memories expire after 7 days
- Explicit "remember" vs "context" distinction
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Try to import mem0 components
try:
    from memory.mem0_client import InMemoryFallback, MCPMemoryClient, build_memory_client
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False


# Importance scoring keywords
IMPORTANT_KEYWORDS = {
    # High importance (score 8-10)
    10: ["critical", "urgent", "security", "vulnerability", "breach", "production down"],
    9: ["bug", "fix", "error", "crash", "fail", "important", "key", "must", "remember"],
    8: ["feature", "api", "endpoint", "architecture", "design", "decision"],
    
    # Medium importance (score 5-7)
    7: ["config", "setting", "install", "setup", "deploy", "release"],
    6: ["refactor", "improve", "optimize", "performance", "test", "coverage"],
    5: ["document", "docs", "comment", "readme", "changelog"],
    
    # Low importance (score 1-4)
    4: ["log", "debug", "trace", "minor", "cosmetic"],
    3: ["temp", "temporary", "workaround", "hack"],
    2: ["todo", "later", "maybe", "optional"],
    1: ["context", "session", "ephemeral", "transient"],
}

# Default settings
DEFAULT_MAX_HIGH_IMPORTANCE = 50
DEFAULT_LOW_VALUE_DAYS = 7
DEFAULT_SUMMARIZE_THRESHOLD = 4


@dataclass
class ImportanceMemory:
    """
    A memory entry with importance scoring.
    
    Attributes:
        key: Memory identifier
        value: Memory content
        score: Importance score (1-10)
        created_at: Creation timestamp
        project_id: Associated project
        memory_type: "important" or "context"
    """
    key: str
    value: str
    score: int = 5
    created_at: datetime = field(default_factory=datetime.now)
    project_id: str = ""
    memory_type: str = "important"  # "important" or "context"
    
    def __post_init__(self):
        # Clamp score to 1-10
        self.score = max(1, min(10, self.score))
        
        # Set memory type based on score
        if self.score < 5:
            self.memory_type = "context"
        else:
            self.memory_type = "important"
    
    def days_old(self) -> int:
        """Return number of days since creation."""
        return (datetime.now() - self.created_at).days
    
    def is_low_value(self) -> bool:
        """Check if this is a low-value memory that should be cleaned up."""
        return self.score < DEFAULT_SUMMARIZE_THRESHOLD and self.days_old() >= DEFAULT_LOW_VALUE_DAYS


def calculate_importance(text: str) -> int:
    """
    Calculate importance score based on text content.
    
    Args:
        text: Text to analyze
        
    Returns:
        Importance score (1-10)
    """
    text_lower = text.lower()
    
    # Start with neutral score
    score = 5
    
    # Check each importance level
    for importance_level, keywords in IMPORTANT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                # Use highest matching importance
                score = max(score, importance_level)
    
    return score


class SmartMemory:
    """
    Enhanced memory client with importance scoring and auto-cleanup.
    
    Features:
    - remember_important(): Store with high score (7-10)
    - remember_context(): Store with low score (1-4)
    - cleanup_low_value(): Remove old low-value memories
    - summarize_old_memories(): Compress old memories
    - recall_by_importance(): Get only important memories
    - recall_recent(): Get recent memories
    """
    
    def __init__(
        self,
        backend=None,
        max_high_importance: int = DEFAULT_MAX_HIGH_IMPORTANCE,
        low_value_days: int = DEFAULT_LOW_VALUE_DAYS,
        summarize_threshold: int = DEFAULT_SUMMARIZE_THRESHOLD,
    ):
        """
        Initialize smart memory.
        
        Args:
            backend: Optional underlying memory client
            max_high_importance: Max important memories per project
            low_value_days: Days before low-value memories are cleaned up
            summarize_threshold: Score below which memories are summarized
        """
        self._backend = backend or InMemoryFallback()
        self._max_high_importance = max_high_importance
        self._low_value_days = low_value_days
        self._summarize_threshold = summarize_threshold
        
        # In-memory store for importance metadata
        self._metadata: dict[str, ImportanceMemory] = {}
    
    def remember_important(
        self,
        key: str,
        value: str,
        project_id: str = "",
        score: int | None = None,
    ) -> ImportanceMemory:
        """
        Store an important memory (score 7-10).
        
        Args:
            key: Memory identifier
            value: Memory content
            project_id: Associated project
            score: Optional explicit score (default: auto-calculated)
            
        Returns:
            Created ImportanceMemory
        """
        if score is None:
            score = calculate_importance(value)
            # Ensure it's in important range
            score = max(7, min(10, score))
        
        memory = ImportanceMemory(
            key=key,
            value=value,
            score=score,
            project_id=project_id,
            memory_type="important",
        )
        
        self._metadata[key] = memory
        
        # Store in backend
        self._backend.add(
            messages=[{"role": "assistant", "content": value}],
            user_id=f"project:{project_id}" if project_id else "default",
            metadata={
                "key": key,
                "project": project_id,
                "importance": score,
                "memory_type": "important",
            },
        )
        
        # Enforce limit for high-importance memories
        self._enforce_limit(project_id)
        
        logger.info(f"Stored important memory: {key} (score={score})")
        return memory
    
    def remember_context(
        self,
        key: str,
        value: str,
        project_id: str = "",
    ) -> ImportanceMemory:
        """
        Store a context/ephemeral memory (score 1-4).
        
        Args:
            key: Memory identifier
            value: Memory content
            project_id: Associated project
            
        Returns:
            Created ImportanceMemory
        """
        score = calculate_importance(value)
        # Clamp to context range
        score = max(1, min(4, score))
        
        memory = ImportanceMemory(
            key=key,
            value=value,
            score=score,
            project_id=project_id,
            memory_type="context",
        )
        
        self._metadata[key] = memory
        
        # Store in backend
        self._backend.add(
            messages=[{"role": "assistant", "content": value}],
            user_id=f"project:{project_id}" if project_id else "default",
            metadata={
                "key": key,
                "project": project_id,
                "importance": score,
                "memory_type": "context",
            },
        )
        
        logger.info(f"Stored context memory: {key} (score={score})")
        return memory
    
    def _enforce_limit(self, project_id: str) -> None:
        """Enforce maximum high-importance memories per project."""
        # Get all important memories for this project
        project_memories = [
            (k, m) for k, m in self._metadata.items()
            if m.project_id == project_id and m.memory_type == "important"
        ]
        
        # Sort by score (highest first), then by age (newest first)
        project_memories.sort(key=lambda x: (-x[1].score, -x[1].created_at.timestamp()))
        
        # Remove excess memories (keep only max_high_importance)
        if len(project_memories) > self._max_high_importance:
            excess = project_memories[self._max_high_importance:]
            for key, memory in excess:
                logger.info(f"Evicting memory due to limit: {key}")
                del self._metadata[key]
    
    def cleanup_low_value(self) -> int:
        """
        Remove low-value memories older than configured days.
        
        Returns:
            Number of memories cleaned up
        """
        cleaned = 0
        to_remove = []
        
        for key, memory in self._metadata.items():
            if memory.is_low_value():
                to_remove.append(key)
        
        for key in to_remove:
            del self._metadata[key]
            cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} low-value memories")
        
        return cleaned
    
    def summarize_old_memories(self) -> int:
        """
        Summarize old memories with score below threshold.
        
        Creates condensed versions of old low-importance memories.
        
        Returns:
            Number of memories summarized
        """
        summarized = 0
        
        for key, memory in self._metadata.items():
            if memory.score < self._summarize_threshold and memory.days_old() >= 1:
                # In a real implementation, this would use LLM summarization
                original = memory.value
                summary = f"[Summary of {memory.key}]: {original[:100]}..."
                
                # Update with summary
                memory.value = summary
                memory.score = max(memory.score, 3)  # Bump score after summarization
                summarized += 1
        
        if summarized > 0:
            logger.info(f"Summarized {summarized} old memories")
        
        return summarized
    
    def recall_by_importance(
        self,
        min_score: int = 5,
        project_id: str = "",
    ) -> list[ImportanceMemory]:
        """
        Retrieve memories with score >= min_score.
        
        Args:
            min_score: Minimum importance score
            project_id: Optional project filter
            
        Returns:
            List of matching ImportanceMemory objects
        """
        results = []
        
        for memory in self._metadata.values():
            if memory.score >= min_score:
                if not project_id or memory.project_id == project_id:
                    results.append(memory)
        
        # Sort by score (highest first)
        results.sort(key=lambda m: (-m.score, -m.created_at.timestamp()))
        
        return results
    
    def recall_recent(
        self,
        days: int = 7,
        project_id: str = "",
    ) -> list[ImportanceMemory]:
        """
        Retrieve memories created within the last N days.
        
        Args:
            days: Number of days to look back
            project_id: Optional project filter
            
        Returns:
            List of recent ImportanceMemory objects
        """
        cutoff = datetime.now() - timedelta(days=days)
        results = []
        
        for memory in self._metadata.values():
            if memory.created_at >= cutoff:
                if not project_id or memory.project_id == project_id:
                    results.append(memory)
        
        # Sort by creation date (newest first)
        results.sort(key=lambda m: -m.created_at.timestamp())
        
        return results
    
    def search(self, query: str, project_id: str = "") -> list[dict]:
        """
        Search memories using backend's native search.
        
        Args:
            query: Search query
            project_id: Optional project filter
            
        Returns:
            List of search results
        """
        filters = {"project": project_id} if project_id else {}
        
        try:
            results = self._backend.search(query, filters=filters)
            return results.get("results", [])
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return []
    
    def get_stats(self, project_id: str = "") -> dict[str, Any]:
        """
        Get memory statistics.
        
        Args:
            project_id: Optional project filter
            
        Returns:
            Statistics dict
        """
        memories = self._metadata.values()
        
        if project_id:
            memories = [m for m in memories if m.project_id == project_id]
        
        total = len(memories)
        important = sum(1 for m in memories if m.memory_type == "important")
        context = sum(1 for m in memories if m.memory_type == "context")
        
        avg_score = sum(m.score for m in memories) / total if total > 0 else 0
        
        # Count by score ranges
        high = sum(1 for m in memories if m.score >= 7)
        medium = sum(1 for m in memories if 4 <= m.score <= 6)
        low = sum(1 for m in memories if m.score <= 3)
        
        return {
            "total": total,
            "important": important,
            "context": context,
            "average_score": round(avg_score, 2),
            "high_importance": high,
            "medium_importance": medium,
            "low_importance": low,
            "max_per_project": self._max_high_importance,
        }
    
    def delete(self, key: str) -> bool:
        """
        Delete a specific memory.
        
        Args:
            key: Memory key to delete
            
        Returns:
            True if deleted, False if not found
        """
        if key in self._metadata:
            del self._metadata[key]
            return True
        return False


def build_smart_memory(settings) -> SmartMemory:
    """
    Factory to build SmartMemory with appropriate backend.
    
    Args:
        settings: Settings object
        
    Returns:
        SmartMemory instance
    """
    backend = build_memory_client(settings)
    return SmartMemory(backend=backend)


# Convenience function for backward compatibility
def create_smart_memory(
    max_high_importance: int = DEFAULT_MAX_HIGH_IMPORTANCE,
    low_value_days: int = DEFAULT_LOW_VALUE_DAYS,
) -> SmartMemory:
    """
    Create a standalone SmartMemory instance.
    
    Args:
        max_high_importance: Max important memories per project
        low_value_days: Days before cleanup
        
    Returns:
        SmartMemory instance
    """
    return SmartMemory(
        max_high_importance=max_high_importance,
        low_value_days=low_value_days,
    )
