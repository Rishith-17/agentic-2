"""Auto-discover and register skills from app.skills package."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType
from typing import Any

from app.skills.base import SkillBase

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillBase] = {}

    def register(self, skill: SkillBase) -> None:
        if not skill.name:
            raise ValueError("Skill must define name")
        self._skills[skill.name] = skill
        logger.info("Registered skill: %s", skill.name)

    def get(self, name: str) -> SkillBase | None:
        return self._skills.get(name)

    def all_meta(self) -> list[dict[str, Any]]:
        return [s.to_meta() for s in self._skills.values()]

    def list_names(self) -> list[str]:
        return sorted(self._skills.keys())


def _iter_skill_modules(package_name: str) -> list[ModuleType]:
    import app.skills as skills_pkg

    modules: list[ModuleType] = []
    for finder, name, ispkg in pkgutil.iter_modules(skills_pkg.__path__):
        if name.startswith("_") or name in ("base",):
            continue
        full = f"{package_name}.{name}"
        try:
            modules.append(importlib.import_module(full))
        except Exception as e:
            logger.warning("Skip skill module %s: %s", full, e)
    return modules


def load_skills(registry: SkillRegistry) -> None:
    """Import all modules under app.skills and register SkillBase subclasses."""
    modules = _iter_skill_modules("app.skills")
    for mod in modules:
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if obj is SkillBase:
                continue
            try:
                if not issubclass(obj, SkillBase):
                    continue
            except TypeError:
                continue

            if obj.__module__ != mod.__name__:
                logger.debug("Skipping %s: module mismatch (%s != %s)", name, obj.__module__, mod.__name__)
                continue
            try:
                instance = obj()
                registry.register(instance)
            except Exception as e:
                logger.warning("Could not instantiate %s: %s", obj, e)
