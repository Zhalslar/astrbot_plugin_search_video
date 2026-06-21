from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from astrbot.api import logger

from ..config import PluginConfig
from .base import BaseVideoSearcher, VideoItem


class DouyinSearcher(BaseVideoSearcher):
    platform_key = "douyin"
    platform_label = "抖音"

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.search_api = "https://www.douyin.com/aweme/v1/web/search/item/"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/search/python?source=switch_tab&type=video",
            "Origin": "https://www.douyin.com",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.cfg.douyin_cookie,
        }
        self.session = ClientSession(
            headers=self.headers,
            timeout=ClientTimeout(total=self.cfg.download_timeout),
        )

    async def close(self) -> None:
        await self.session.close()

    async def search_video(
        self,
        keyword: str,
        page: int = 1,
        count: int = 18,
    ) -> list[VideoItem]:
        if not self.cfg.douyin_cookie.strip():
            logger.warning("douyin cookie is empty, skip douyin search")
            return []

        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "search_channel": "aweme_video_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "keyword": keyword,
            "offset": str(max(page - 1, 0) * 10),
            "count": count,
            "sort_type": "0",
        }
        webid = self._extract_webid(self.cfg.douyin_cookie)
        if webid:
            params["webid"] = webid

        retries = self.cfg.retry_times
        for attempt in range(1, retries + 1):
            try:
                async with self.session.get(self.search_api, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

                if data.get("status_code") == 0:
                    rows = data.get("data") or []
                    normalized: list[VideoItem] = []
                    for row in rows:
                        item = self._normalize_search_row(row)
                        if item is not None:
                            normalized.append(item)
                    return normalized

                logger.warning(
                    "douyin search returned status_code=%s status_msg=%s",
                    data.get("status_code"),
                    data.get("status_msg"),
                )
            except Exception as exc:
                logger.warning(
                    "douyin search failed (%s/%s): %s",
                    attempt,
                    retries,
                    exc,
                )

            if attempt < retries:
                await asyncio.sleep(attempt)

        return []

    async def get_video_info(self, video_id: str) -> VideoItem | None:
        aweme = await self._fetch_aweme_from_detail_page(video_id)
        if aweme is None:
            return None
        return self._normalize_aweme(aweme)

    async def download_video(
        self,
        video_id: str,
        *,
        video_item: VideoItem | None = None,
    ) -> Path | None:
        aweme = self._extract_aweme(video_item) if video_item else None
        if aweme is None:
            aweme = await self._fetch_aweme_from_detail_page(video_id)
        if aweme is None:
            return None

        video_url = self._extract_video_url(aweme)
        if not video_url:
            logger.error("failed to extract douyin video url: %s", video_id)
            return None

        output_file = self.cfg.videos_dir / f"douyin-{video_id}.mp4"
        if output_file.exists():
            return output_file

        try:
            await self.download_stream(
                self.session,
                video_url,
                output_file,
                headers=self.headers,
            )
        except Exception as exc:
            logger.error("douyin download failed: %s", exc)
            if output_file.exists():
                output_file.unlink()
            return None

        return output_file if output_file.exists() else None

    def build_video_url(self, video_id: str) -> str:
        return f"https://www.douyin.com/video/{video_id}"

    def build_cover_headers(self, url: str) -> dict[str, str]:
        del url
        headers = self._default_cover_headers()
        headers["Referer"] = "https://www.douyin.com/"
        if self.cfg.douyin_cookie.strip():
            headers["Cookie"] = self.cfg.douyin_cookie.strip()
        return headers

    @staticmethod
    def _extract_webid(cookie: str) -> str:
        matched = re.search(r"(?:^|;\s*)s_v_web_id=verify_([^;]+)", cookie)
        if matched:
            return matched.group(1).strip()
        return ""

    def _normalize_search_row(self, row: dict[str, Any]) -> VideoItem | None:
        aweme = row.get("aweme_info")
        if not isinstance(aweme, dict):
            return None
        item = self._normalize_aweme(aweme)
        item["raw"] = row
        return item

    def _normalize_aweme(self, aweme: dict[str, Any]) -> VideoItem:
        author = aweme.get("author") or {}
        video_data = aweme.get("video") or {}
        stats = aweme.get("statistics") or {}
        video_id = str(aweme.get("aweme_id") or "").strip()
        cover = self.first_url(
            (video_data.get("cover") or {}).get("url_list"),
            (video_data.get("origin_cover") or {}).get("url_list"),
            (video_data.get("dynamic_cover") or {}).get("url_list"),
        )
        duration_ms = self.safe_int(video_data.get("duration"))

        return {
            "platform": self.platform_key,
            "platform_label": self.platform_label,
            "video_id": video_id,
            "title": str(aweme.get("desc") or ""),
            "author": str(author.get("nickname") or ""),
            "duration": self.format_duration(duration_ms // 1000),
            "play": self.safe_int(stats.get("play_count") or stats.get("digg_count")),
            "tags": "",
            "cover": cover,
            "url": self.build_video_url(video_id),
            "raw": aweme,
        }

    def _extract_aweme(self, video_item: VideoItem | None) -> dict[str, Any] | None:
        if not video_item:
            return None
        raw = video_item.get("raw")
        if isinstance(raw, dict):
            aweme = raw.get("aweme_info")
            if isinstance(aweme, dict):
                return aweme
            if "video" in raw or "author" in raw:
                return raw
        return None

    def _extract_video_url(self, aweme: dict[str, Any]) -> str:
        video_data = aweme.get("video") or {}
        candidates: list[str] = []

        for key in ("play_addr", "play_addr_h264", "download_addr"):
            addr = video_data.get(key)
            if isinstance(addr, dict):
                candidates.extend(
                    str(url).strip()
                    for url in addr.get("url_list", [])
                    if str(url).strip()
                )

        for bit_rate in video_data.get("bit_rate", []) or []:
            if isinstance(bit_rate, dict):
                play_addr = bit_rate.get("play_addr") or {}
                candidates.extend(
                    str(url).strip()
                    for url in play_addr.get("url_list", [])
                    if str(url).strip()
                )

        for candidate in candidates:
            if "playwm" in candidate:
                return candidate.replace("playwm", "play")
            return candidate
        return ""

    async def _fetch_aweme_from_detail_page(
        self,
        video_id: str,
    ) -> dict[str, Any] | None:
        detail_url = self.build_video_url(video_id)
        try:
            async with self.session.get(detail_url, headers=self.headers) as response:
                response.raise_for_status()
                html = await response.text()
        except Exception as exc:
            logger.error("failed to request douyin detail page %s: %s", video_id, exc)
            return None

        matched = re.search(
            r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
            html,
            re.DOTALL,
        )
        if not matched:
            logger.error("failed to extract douyin router data: %s", video_id)
            return None

        try:
            router_data = json.loads(matched.group(1).strip())
        except json.JSONDecodeError as exc:
            logger.error("failed to decode douyin router data %s: %s", video_id, exc)
            return None

        loader_data = router_data.get("loaderData") or {}
        for page_data in loader_data.values():
            if not isinstance(page_data, dict):
                continue
            video_info = page_data.get("videoInfoRes") or {}
            item_list = video_info.get("item_list") or []
            if item_list and isinstance(item_list[0], dict):
                return item_list[0]
        return None
