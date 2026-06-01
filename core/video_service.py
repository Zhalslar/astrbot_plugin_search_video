import asyncio
from pathlib import Path

from bs4 import BeautifulSoup

from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import Image, Video
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .api import VideoAPI
from .config import PluginConfig
from .downloader import ImageDownloader
from .draw import VideoCardRenderer
from .utils import duration_to_seconds, upload_file


class VideoService:
    def __init__(self, config: PluginConfig) -> None:
        self.cfg = config
        self.api = VideoAPI(config)
        self.image_downloader = ImageDownloader(config)
        self.renderer = VideoCardRenderer(config, self.image_downloader)
        self._background_tasks: set[asyncio.Task] = set()
        self._video_inflight_keys: set[str] = set()

    async def close(self) -> None:
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
        await self.image_downloader.close()
        await self.api.close()

    async def search_video(self, keyword: str, page: int = 1) -> list[dict] | None:
        return await self.api.search_video(keyword=keyword, page=page)

    async def get_video_info(self, bvid: str) -> dict | None:
        return await self.api.get_video_info(bvid)

    async def send_video_list_image(
        self, event: AstrMessageEvent, video_list: list[dict]
    ) -> None:
        image = await self.renderer.render_video_list_image(video_list)
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
        self, video_list: list[dict], *, limit: int = 20
    ) -> list[dict]:
        candidates: list[dict] = []

        for index, video in enumerate(video_list[:limit], start=1):
            title = self._clean_video_text(video.get("title", ""))
            tags = self._clean_video_text(video.get("tag", ""))
            duration = str(video.get("duration", "") or "").strip() or "0:00"

            candidates.append(
                {
                    "index": index,
                    "bvid": str(video.get("bvid", "") or "").strip(),
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
                        f"bvid={candidate['bvid']}",
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
    def extract_candidate_bvid(text: str, candidates: list[dict]) -> str | None:
        import re

        bvid_map = {
            str(candidate.get("bvid", "")).upper(): str(candidate.get("bvid", ""))
            for candidate in candidates
            if candidate.get("bvid")
        }
        if not bvid_map:
            return None

        content = str(text or "").strip()
        if not content:
            return None

        if content.upper() in bvid_map:
            return bvid_map[content.upper()]

        bvid_match = re.search(r"BV[0-9A-Za-z]{10}", content, re.IGNORECASE)
        if bvid_match:
            bvid = bvid_match.group(0).upper()
            if bvid in bvid_map:
                return bvid_map[bvid]

        index_match = re.search(r"\b(\d{1,2})\b", content)
        if index_match:
            index = int(index_match.group(1))
            if 1 <= index <= len(candidates):
                return str(candidates[index - 1].get("bvid", "") or "").strip() or None

        return None

    @staticmethod
    def find_video_by_bvid(video_list: list[dict], bvid: str) -> dict | None:
        target = str(bvid or "").strip().upper()
        if not target:
            return None

        for video in video_list:
            current = str(video.get("bvid", "") or "").strip().upper()
            if current == target:
                return video
        return None

    def _build_video_task_key(self, event: AstrMessageEvent, video: dict) -> str:
        video_id = str(video.get("bvid", "") or "").strip()
        if not video_id:
            video_id = str(video.get("arcurl", "") or "").strip()
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
                logger.error(f"后台视频任务状态获取失败: {callback_error}")
                return

            if exc is not None:
                logger.error(f"后台视频任务异常退出: {exc}", exc_info=exc)

        task.add_done_callback(_cleanup)

    async def _send_video_in_background(
        self, event: AstrMessageEvent, video: dict
    ) -> None:
        try:
            await self._send_video(event, video)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"后台发送视频失败: {e}", exc_info=True)
            try:
                await event.send(event.plain_result("视频处理失败，请稍后重试"))
            except Exception as send_error:
                logger.error(f"后台发送失败提示也失败: {send_error}")

    async def _send_video(self, event: AstrMessageEvent, video: dict) -> None:
        video_id = str(video.get("bvid", "") or "").strip()
        raw_title = video.get("title", "")
        title = BeautifulSoup(str(raw_title or ""), "html.parser").get_text()
        duration = duration_to_seconds(video.get("duration", "0"))

        if duration > self.cfg.max_duration:
            video_url = f"https://www.bilibili.com/video/{video_id}"
            await event.send(event.plain_result(video_url))
            return

        if self.cfg.show_download_prompt:
            await event.send(event.plain_result(f"正在下载: {title}"))

        logger.info(f"正在下载视频: {title}")
        video_path = await self.api.download_video(video_id)

        if not video_path:
            await event.send(event.plain_result("下载视频失败"))
            return

        try:
            await self._send_video_file(event, video_path)
        except Exception as e:
            logger.error(f"发送视频失败: {e}")
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

        chain = [Video.fromFileSystem(self._map_send_video_path(video_path))]
        await event.send(event.chain_result(chain))  # type: ignore[arg-type]

    def _map_send_video_path(self, video_path: Path) -> str:
        local_prefix = str(self.cfg.local_media_path_prefix or "").rstrip("/")
        send_prefix = str(self.cfg.send_media_path_prefix or "").rstrip("/")
        path = str(video_path)

        if not local_prefix or not send_prefix:
            return path

        if path == local_prefix:
            return send_prefix
        if path.startswith(f"{local_prefix}/"):
            return f"{send_prefix}{path[len(local_prefix):]}"
        return path

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
