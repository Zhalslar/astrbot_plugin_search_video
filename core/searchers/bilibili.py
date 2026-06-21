from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from bilibili_api import Credential, video
from bilibili_api.video import (
    AudioStreamDownloadURL,
    VideoCodecs,
    VideoDownloadURLDataDetecter,
    VideoQuality,
    VideoStreamDownloadURL,
)

from astrbot.api import logger

from ..config import PluginConfig
from .base import BaseVideoSearcher, VideoItem


class BilibiliSearcher(BaseVideoSearcher):
    platform_key = "bilibili"
    platform_label = "B站"

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.search_api = "https://api.bilibili.com/x/web-interface/search/type"
        self.home_url = "https://www.bilibili.com"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Referer": "https://search.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self.cfg.bilibili_cookie.strip():
            self.headers["Cookie"] = self.cfg.bilibili_cookie.strip()
        self.session = ClientSession(
            headers=self.headers,
            timeout=ClientTimeout(total=self.cfg.download_timeout),
        )
        self._search_ready = False

    async def close(self) -> None:
        await self.session.close()

    async def search_video(
        self,
        keyword: str,
        page: int = 1,
        count: int = 18,
    ) -> list[VideoItem]:
        params = {"search_type": "video", "keyword": keyword, "page": page}
        retries = self.cfg.retry_times

        for attempt in range(1, retries + 1):
            try:
                await self._prepare_search_session(keyword)
                async with self.session.get(
                    self.search_api,
                    params=params,
                    headers=self._build_search_headers(keyword),
                ) as response:
                    response.raise_for_status()
                    text = await response.text()
                    data = self._parse_search_response(
                        text,
                        response.headers.get("content-type"),
                    )
            except Exception as exc:
                self._search_ready = False
                logger.warning(
                    "bilibili search failed (%s/%s): %s",
                    attempt,
                    retries,
                    exc,
                )
                continue

            if data.get("code") == 0:
                rows = data.get("data", {}).get("result", [])[:count]
                normalized: list[VideoItem] = []
                for row in rows:
                    item = self._normalize_search_item(row)
                    if item is not None:
                        normalized.append(item)
                return normalized

            logger.warning(
                "bilibili search returned code=%s message=%s",
                data.get("code"),
                data.get("message"),
            )

            if attempt < retries:
                await asyncio.sleep(attempt)

        return []

    async def get_video_info(self, video_id: str) -> VideoItem | None:
        try:
            client = video.Video(video_id, credential=Credential(sessdata=""))
            info = await client.get_info()
        except Exception as exc:
            logger.error("failed to get bilibili video info %s: %s", video_id, exc)
            return None

        duration_seconds = int(info.get("duration") or 0)
        return {
            "platform": self.platform_key,
            "platform_label": self.platform_label,
            "video_id": str(info.get("bvid") or video_id),
            "title": str(info.get("title") or ""),
            "author": str((info.get("owner") or {}).get("name") or ""),
            "duration": self.format_duration(duration_seconds),
            "play": self.safe_int((info.get("stat") or {}).get("view")),
            "tags": "",
            "cover": str(info.get("pic") or ""),
            "url": self.build_video_url(str(info.get("bvid") or video_id)),
            "raw": info,
        }

    async def download_video(
        self,
        video_id: str,
        *,
        video_item: VideoItem | None = None,
    ) -> Path | None:
        del video_item
        client = video.Video(video_id, credential=Credential(sessdata=""))
        download_url_data = await client.get_download_url(page_index=0)
        # 补丁
        for video_data in download_url_data.get("dash", {}).get("video", []):
            codecs = video_data.get("codecs", "")
            if isinstance(codecs, str) and codecs.startswith("hvc1"):
                video_data["codecs"] = f"hev,{codecs}"

        detector = VideoDownloadURLDataDetecter(download_url_data)
        streams = detector.detect_best_streams(
            video_max_quality=VideoQuality._720P,
            codecs=[VideoCodecs.AVC],
            no_dolby_video=True,
            no_hdr=True,
        )

        video_stream = streams[0]
        if not isinstance(video_stream, VideoStreamDownloadURL):
            logger.error("bilibili video stream unavailable: %s", video_id)
            return None

        audio_stream = streams[1] if len(streams) > 1 else None
        if not isinstance(audio_stream, AudioStreamDownloadURL):
            logger.error("bilibili audio stream unavailable: %s", video_id)
            return None

        video_file = self.cfg.videos_dir / f"bilibili-{video_id}-video.m4s"
        audio_file = self.cfg.videos_dir / f"bilibili-{video_id}-audio.m4s"
        output_file = self.cfg.videos_dir / f"bilibili-{video_id}.mp4"

        try:
            await asyncio.gather(
                self.download_stream(self.session, video_stream.url, video_file),
                self.download_stream(self.session, audio_stream.url, audio_file),
            )
        except Exception as exc:
            logger.error("bilibili media download failed: %s", exc)
            return None

        await self.merge_file_to_mp4(video_file, audio_file, output_file)

        for temp_file in (video_file, audio_file):
            if temp_file.exists():
                temp_file.unlink()

        if not output_file.exists():
            logger.error("bilibili output file missing: %s", output_file)
            return None
        return output_file

    def build_video_url(self, video_id: str) -> str:
        return f"https://www.bilibili.com/video/{video_id}"

    async def _prepare_search_session(self, keyword: str) -> None:
        if self._search_ready:
            return

        async with self.session.get(
            self.home_url,
            headers=self._build_home_headers(keyword),
        ) as response:
            response.raise_for_status()
            await response.read()
        self._search_ready = True

    def _build_home_headers(self, keyword: str) -> dict[str, str]:
        headers = dict(self.headers)
        headers["Referer"] = f"https://search.bilibili.com/all?keyword={keyword}"
        return headers

    def _build_search_headers(self, keyword: str) -> dict[str, str]:
        headers = dict(self.headers)
        headers["Referer"] = f"https://search.bilibili.com/all?keyword={keyword}"
        return headers

    def build_cover_headers(self, url: str) -> dict[str, str]:
        del url
        headers = self._default_cover_headers()
        headers["Referer"] = "https://www.bilibili.com/"
        return headers

    @staticmethod
    def _parse_search_response(
        text: str,
        content_type: str | None,
    ) -> dict[str, Any]:
        if content_type and "json" in content_type.lower():
            return json.loads(text)
        if text.lstrip().startswith("{"):
            return json.loads(text)
        preview = " ".join(text.strip().split())[:160]
        raise ValueError(
            "unexpected bilibili search response content type: "
            f"{content_type or 'unknown'}; preview={preview}"
        )

    def _normalize_search_item(self, raw: dict[str, Any]) -> VideoItem | None:
        video_id = str(raw.get("bvid") or "").strip()
        if not video_id:
            return None

        cover = str(raw.get("pic") or "").strip()
        if cover.startswith("//"):
            cover = "https:" + cover

        return {
            "platform": self.platform_key,
            "platform_label": self.platform_label,
            "video_id": video_id,
            "title": str(raw.get("title") or ""),
            "author": str(raw.get("author") or ""),
            "duration": str(raw.get("duration") or "0:00"),
            "play": self.safe_int(raw.get("play")),
            "tags": str(raw.get("tag") or ""),
            "cover": cover,
            "url": str(raw.get("arcurl") or self.build_video_url(video_id)),
            "raw": raw,
        }
