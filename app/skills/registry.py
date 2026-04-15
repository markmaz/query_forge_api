from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Dict, List, Optional, Type

from app.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class SkillRegistry:
    _registry: Dict[str, Type[BaseSkill]] = {}

    @classmethod
    def register(cls, skill_cls: Type[BaseSkill]) -> Type[BaseSkill]:
        cls._registry[skill_cls.skill_type] = skill_cls
        return skill_cls

    @classmethod
    def get(cls, skill_type: str) -> Optional[Type[BaseSkill]]:
        return cls._registry.get(skill_type)

    @classmethod
    def exists(cls, skill_type: str) -> bool:
        return skill_type in cls._registry

    @classmethod
    def all_types(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def all_skills(cls) -> List[Dict]:
        return [
            {"skill_type": skill_type, "cls": skill_cls}
            for skill_type, skill_cls in cls._registry.items()
        ]

    @classmethod
    def autodiscover(cls, package_name: str) -> None:
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.exception("SkillRegistry.autodiscover: failed to import package %s", package_name)
            return
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            if module_name.startswith("_"):
                continue
            full_name = f"{package_name}.{module_name}"
            try:
                importlib.import_module(full_name)
                logger.debug("SkillRegistry: discovered %s", full_name)
            except ImportError:
                logger.exception("SkillRegistry.autodiscover: failed to import %s", full_name)
