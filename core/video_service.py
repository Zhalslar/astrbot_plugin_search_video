import asyncio
from pathlib import Path
from typing import cast

from bs4 import BeautifulSoup
from PIL import Image as PILImage

from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import Image, Video
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .config import PluginConfig
from .renderer import VideoCardRenderer
from .searchers import SEARCHER_TYPES, BaseVideoSearcher
from .utils import duration_to_seconds, upload_file


class VideoService:
    def __init__(self, config: PluginConfig) -> None:
        self.cfg = config
        self.searchers = {
            platform: searcher_type(config)
            for platform, searcher_type in SEARCHER_TYPES.items()
        }
        self.renderer = VideoCardRenderer(config)
        self._background_tasks: set[asyncio.Task] = set()
        self._video_inflight_keys: set[str] = set()

    async def close(self) -> None:
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
        await asyncio.gather(
            *(searcher.close() for searcher in self.searchers.values()),
            return_exceptions=True,
        )

    def get_searcher(self, platform: str) -> BaseVideoSearcher:
        searcher = self.searchers.get(platform)
        if searcher is None:
            raise ValueError(f"unsupported platform: {platform}")
        return searcher

    async def search_video(
        self,
        *,
        keyword: str,
        page: int = 1,
        platform: str = "bilibili",
    ) -> list[dict]:
        return await self.get_searcher(platform).search_video(
            keyword=keyword, page=page
        )

    async def get_video_info(
        self,
        *,
        video_id: str,
        platform: str = "bilibili",
    ) -> dict | None:
        return await self.get_searcher(platform).get_video_info(video_id)

    async def send_video_list_image(
        self,
        event: AstrMessageEvent,
        video_list: list[dict],
    ) -> None:
        cover_map = await self._fetch_cover_map(video_list)
        image = await self.renderer.render_video_list_image(video_list, cover_map)
        await event.send(event.chain_result([Image.fromBytes(image)]))

    def schedule_video_send(self, event: AstrMessageEvent, video: dict) -> str:
        task_key = self._build_video_task_key(event, video)
        if task_key in self._video_inflight_keys:
            return "该视频已经在后台处理中，完成后会自动发送给用户，请勿重复调用。"

        self._video_inflight_keys.add(task_key)
        try:
            self._create_background_task(
                self._send_video_in_background(event, video),
                task_key=task_key,
            )
        except Exception:
            self._video_inflight_keys.discard(task_key)
            raise
        return ""

    def build_video_candidates(
        self,
        video_list: list[dict],
        *,
        limit: int = 20,
    ) -> list[dict]:
        candidates: list[dict] = []

        for index, video in enumerate(video_list[:limit], start=1):
            title = self._clean_video_text(video.get("title", ""))
            tags = self._clean_video_text(video.get("tags", video.get("tag", "")))
            duration = str(video.get("duration", "") or "").strip() or "0:00"

            candidates.append(
                {
                    "index": index,
                    "platform": str(video.get("platform", "") or "").strip(),
                    "video_id": str(video.get("video_id", "") or "").strip(),
                    "title": self._trim_text(title, limit=60),
                    "tags": self._trim_text(tags, limit=60),
                    "author": str(video.get("author", "") or "").strip(),
                    "duration": duration,
                    "play": self._safe_int(video.get("play")),
                }
            )

        return candidates

    def format_video_candidates_text(self, keyword: str, candidates: list[dict]) -> str:
        lines = [f"搜索词: {keyword}", "候选视频列表:"]
        for candidate in candidates:
            lines.append(
                " | ".join(
                    [
                        f"{candidate['index']}.",
                        f"platform={candidate['platform']}",
                        f"id={candidate['video_id']}",
                        f"标题={candidate['title']}",
                        f"标签={candidate['tags'] or '-'}",
                        f"作者={candidate['author'] or '-'}",
                        f"时长={candidate['duration']}",
                        f"播放={candidate['play']}",
                    ]
                )
            )
        return "\n".join(lines)

    @staticmethod
    def extract_candidate_video_id(text: str, candidates: list[dict]) -> str | None:
        import re

        id_map = {
            str(candidate.get("video_id", "")).upper(): str(
                candidate.get("video_id", "")
            )
            for candidate in candidates
            if candidate.get("video_id")
        }
        if not id_map:
            return None

        content = str(text or "").strip()
        if not content:
            return None

        if content.upper() in id_map:
            return id_map[content.upper()]

        for matched_id in re.findall(
            r"(BV[0-9A-Za-z]{10}|\d{8,20})", content, re.IGNORECASE
        ):
            candidate_id = matched_id.upper()
            if candidate_id in id_map:
                return id_map[candidate_id]

        index_match = re.search(r"\b(\d{1,2})\b", content)
        if index_match:
            index = int(index_match.group(1))
            if 1 <= index <= len(candidates):
                return (
                    str(candidates[index - 1].get("video_id", "") or "").strip() or None
                )

        return None

    @staticmethod
    def find_video_by_id(video_list: list[dict], video_id: str) -> dict | None:
        target = str(video_id or "").strip().upper()
        if not target:
            return None

        for video in video_list:
            current = str(video.get("video_id", "") or "").strip().upper()
            if current == target:
                return video
        return None

    def _build_video_task_key(self, event: AstrMessageEvent, video: dict) -> str:
        video_id = str(video.get("video_id", "") or "").strip()
        if not video_id:
            video_id = str(video.get("url", "") or "").strip()
        if not video_id:
            video_id = str(video.get("title", "") or "").strip()

        umo = str(getattr(event, "unified_msg_origin", "") or "").strip() or "unknown"
        sender_id = str(event.get_sender_id() or "").strip() or "unknown"
        return f"{umo}:{sender_id}:{video_id}"

    def _create_background_task(self, coro, *, task_key: str | None = None) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _cleanup(done_task: asyncio.Task) -> None:
            self._background_tasks.discard(done_task)
            if task_key:
                self._video_inflight_keys.discard(task_key)

            if done_task.cancelled():
                return

            try:
                exc = done_task.exception()
            except Exception as callback_error:
                logger.error("后台视频任务状态获取失败: %s", callback_error)
                return

            if exc is not None:
                logger.error("后台视频任务异常退出: %s", exc, exc_info=exc)

        task.add_done_callback(_cleanup)

    async def _send_video_in_background(
        self,
        event: AstrMessageEvent,
        video: dict,
    ) -> None:
        try:
            await self._send_video(event, video)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("后台发送视频失败: %s", exc, exc_info=True)
            try:
                await event.send(event.plain_result("视频处理失败，请稍后重试"))
            except Exception as send_error:
                logger.error("后台发送失败提示也失败: %s", send_error)

    async def _send_video(self, event: AstrMessageEvent, video: dict) -> None:
        platform = str(video.get("platform", "") or "bilibili").strip()
        searcher = self.get_searcher(platform)
        video_id = searcher.extract_video_id(video)
        raw_title = video.get("title", "")
        title = BeautifulSoup(str(raw_title or ""), "html.parser").get_text()
        duration = duration_to_seconds(video.get("duration", "0"))

        if duration > self.cfg.max_duration:
            video_url = str(video.get("url") or searcher.build_video_url(video_id))
            await event.send(event.plain_result(video_url))
            return

        if self.cfg.show_download_prompt:
            await event.send(event.plain_result(f"正在下载: {title}"))

        logger.info("正在下载视频: %s", title)
        video_path = await searcher.download_video(video_id, video_item=video)

        if not video_path:
            await event.send(event.plain_result("下载视频失败"))
            return

        try:
            await self._send_video_file(event, video_path)
        except Exception as exc:
            logger.error("发送视频失败: %s", exc)
        finally:
            if not self.cfg.is_save and video_path.exists():
                video_path.unlink()

    async def _send_video_file(self, event: AstrMessageEvent, video_path: Path) -> None:
        if (
            isinstance(event, AiocqhttpMessageEvent)
            and video_path.stat().st_size > 100 * 1024 * 1024
        ):
            await upload_file(event, video_path)
            return

        chain = [Video.fromFileSystem(str(video_path))]
        await event.send(event.chain_result(chain))  # type: ignore[arg-type]

    @staticmethod
    def _clean_video_text(value: str) -> str:
        text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ")
        return " ".join(text.split())

    @staticmethod
    def _trim_text(value: str, *, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3].rstrip()}..."

    @staticmethod
    def _safe_int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def _fetch_cover_map(
        self, video_list: list[dict]
    ) -> dict[str, PILImage.Image]:
        unique_items: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for video in video_list:
            platform = str(video.get("platform", "") or "bilibili").strip()
            raw_url = str(video.get("cover") or video.get("pic") or "").strip()
            if not raw_url:
                continue
            item = (platform, raw_url)
            if item in seen:
                continue
            seen.add(item)
            unique_items.append(item)

        cover_map: dict[str, PILImage.Image] = {}
        pending_items = list(unique_items)
        max_attempts = max(1, int(self.cfg.retry_times or 0))

        for attempt in range(1, max_attempts + 1):
            results = await asyncio.gather(
                *(
                    self._fetch_single_cover(platform, url)
                    for platform, url in pending_items
                ),
                return_exceptions=True,
            )

            next_pending_items: list[tuple[str, str]] = []
            for (platform, raw_url), result in zip(
                pending_items, results, strict=False
            ):
                if isinstance(result, BaseException):
                    next_pending_items.append((platform, raw_url))
                    if attempt == max_attempts:
                        logger.warning(
                            "cover fetch failed after %s attempts. platform=%s url=%s error=%s",
                            max_attempts,
                            platform,
                            raw_url,
                            result,
                        )
                    continue

                normalized_url = self.get_searcher(platform).normalize_cover_url(
                    raw_url
                )
                cover_map[normalized_url] = cast(PILImage.Image, result)

            if not next_pending_items:
                break

            pending_items = next_pending_items
            if attempt < max_attempts:
                logger.debug(
                    "retrying %s failed cover downloads (%s/%s)",
                    len(pending_items),
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(attempt)

        return cover_map

    async def _fetch_single_cover(self, platform: str, url: str) -> PILImage.Image:
        searcher = self.get_searcher(platform)
        return await searcher.fetch_cover_image(url)
