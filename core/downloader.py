import asyncio
import hashlib
from io import BytesIO
from pathlib import Path

import aiofiles
from aiohttp import ClientSession, ClientTimeout
from PIL import Image

from .config import PluginConfig


class ImageDownloader:
    """
    图片下载器
    """

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/100.0.4896.127 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        self.semaphore = asyncio.Semaphore(self.cfg.max_concurrency)
        self.session = ClientSession(timeout=ClientTimeout(total=self.cfg.download_timeout))

    async def close(self):
        await self.session.close()

    def _cache_path(self, url: str) -> Path:
        name = hashlib.md5(url.encode()).hexdigest() + ".jpg"
        return self.cfg.renderer_dir / name

    async def fetch(self, url: str) -> Image.Image:
        cache_path = self._cache_path(url)
        if cache_path.exists():
            return Image.open(cache_path).convert("RGB")

        async with self.semaphore:
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    raise ValueError(f"下载失败({resp.status}): {url}")

                data = await resp.read()
                async with aiofiles.open(cache_path, "wb") as f:
                    await f.write(data)

                return Image.open(BytesIO(data)).convert("RGB")
