"""Base class for pluggable skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SkillBase(ABC):
    """Each skill exposes metadata and a typed execute entrypoint.

    Class-level attributes for intent scoring
    -----------------------------------------
    priority : int
        Tie-breaker when two skills have the same keyword score.
        Higher value wins. Default 0.
    keywords : list[str]
        Lower-cased words/phrases that strongly indicate this skill.
        The router adds +2 per keyword found in the user message.
    """

    name: str = ""
    description: str = ""
    priority: int = 0
    keywords: list[str] = []

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for parameters accepted by execute()."""

    @abstractmethod
    async def execute(self, action: str, parameters: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the skill action and return a serializable result."""

    def to_meta(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "priority": self.priority,
            "keywords": self.keywords,
        }
