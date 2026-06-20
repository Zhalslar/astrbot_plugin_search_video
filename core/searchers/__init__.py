from __future__ import annotations

from .base import BaseVideoSearcher
from .bilibili import BilibiliSearcher
from .douyin import DouyinSearcher

SEARCHER_TYPES: dict[str, type[BaseVideoSearcher]] = {
    "bilibili": BilibiliSearcher,
    "douyin": DouyinSearcher,
}

__all__ = [
    "BaseVideoSearcher",
    "BilibiliSearcher",
    "DouyinSearcher",
    "SEARCHER_TYPES",
]
