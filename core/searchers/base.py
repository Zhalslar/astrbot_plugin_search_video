from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import Any

import aiofiles
from aiohttp import ClientSession
from PIL import Image

from astrbot.api import logger

from ..config import PluginConfig

VideoItem = dict[str, Any]


class BaseVideoSearcher(ABC):
    platform_key: str = ""
    platform_label: str = ""

    def __init__(self, config: PluginConfig) -> None:
        self.cfg = config

    async def close(self) -> None:
        return None

    @abstractmethod
    async def search_video(
        self, keyword: str, page: int = 1, count: int = 18
    ) -> list[VideoItem]:
        raise NotImplementedError

    @abstractmethod
    async def get_video_info(self, video_id: str) -> VideoItem | None:
        raise NotImplementedError

    @abstractmethod
    async def download_video(
        self,
        video_id: str,
        *,
        video_item: VideoItem | None = None,
    ) -> Path | None:
        raise NotImplementedError

    @abstractmethod
    def build_video_url(self, video_id: str) -> str:
        raise NotImplementedError

    def extract_video_id(self, video_item: VideoItem) -> str:
        return str(video_item.get("video_id") or "").strip()

    async def fetch_cover_image(self, url: str) -> Image.Image:
        normalized_url = self.normalize_cover_url(url)
        if not normalized_url:
            raise ValueError("empty cover url")

        cache_path = self._cover_cache_path(normalized_url)
        if cache_path.exists():
            return Image.open(cache_path).convert("RGB")

        async with self.get_cover_session().get(
            normalized_url,
            headers=self.build_cover_headers(normalized_url),
        ) as response:
            response.raise_for_status()
            data = await response.read()

        async with aiofiles.open(cache_path, "wb") as file:
            await file.write(data)

        return Image.open(BytesIO(data)).convert("RGB")

    def normalize_cover_url(self, url: str) -> str:
        normalized_url = str(url or "").strip()
        if normalized_url.startswith("//"):
            return "https:" + normalized_url
        return normalized_url

    def build_cover_headers(self, url: str) -> dict[str, str]:
        del url
        return self._default_cover_headers()

    @staticmethod
    def _default_cover_headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }

    def get_cover_session(self) -> ClientSession:
        session = getattr(self, "session", None)
        if not isinstance(session, ClientSession):
            raise RuntimeError(
                f"{self.__class__.__name__} has no available client session"
            )
        return session

    @staticmethod
    def format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def first_url(*candidates: Any) -> str:
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
        return ""

    async def download_stream(
        self,
        session: ClientSession,
        url: str,
        save_path: Path,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            current_len = 0
            total_len = int(response.headers.get("content-length", 0))
            last_percent = -1

            async with aiofiles.open(save_path, "wb") as file:
                async for chunk in response.content.iter_chunked(1024 * 64):
                    current_len += len(chunk)
                    await file.write(chunk)

                    if total_len:
                        percent = int(current_len / total_len * 100)
                        if percent != last_percent:
                            last_percent = percent
                            self._print_progress_bar(percent, save_path)

        sys.stdout.write("\n")
        sys.stdout.flush()

    def _print_progress_bar(self, percent: int, path: Path) -> None:
        bar_length = 50
        filled_length = int(bar_length * percent // 100)
        bar = "#" * filled_length + "-" * (bar_length - filled_length)

        file_name = path.name
        if len(file_name) > 30:
            file_name = "..." + file_name[-27:]

        sys.stdout.write(f"\r{file_name:<30} [{bar}] {percent:3d}%")
        sys.stdout.flush()

    async def merge_file_to_mp4(
        self,
        video_file: Path,
        audio_file: Path,
        output_file: Path,
        *,
        log_output: bool = False,
    ) -> None:
        logger.info("merging media into %s", output_file)
        stdout = None if log_output else asyncio.subprocess.DEVNULL
        stderr = None if log_output else asyncio.subprocess.PIPE

        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(video_file),
                "-i",
                str(audio_file),
                "-c",
                "copy",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                str(output_file),
                stdout=stdout,
                stderr=stderr,
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found, fallback to video stream only")
            shutil.copy(video_file, output_file)
            return

        _, stderr_output = await process.communicate()
        stderr_text = stderr_output.decode().strip() if stderr_output else ""
        if process.returncode != 0:
            logger.error("ffmpeg merge failed with return code %s", process.returncode)
            if stderr_text:
                logger.error("ffmpeg stderr: %s", stderr_text)
            shutil.copy(video_file, output_file)
            return

        logger.info("merge completed: %s", output_file)

    def _cover_cache_path(self, url: str) -> Path:
        name = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
        return self.cfg.renderer_dir / name
