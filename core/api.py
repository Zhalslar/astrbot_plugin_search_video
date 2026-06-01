import asyncio
import shutil
import sys
from pathlib import Path

import aiofiles
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

from .config import PluginConfig


class VideoAPI:
    """
    视频API类
    """

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.BILIBILI_SEARCH_API = (
            "https://api.bilibili.com/x/web-interface/search/type"
        )
        self.BILIBILI_SEARCH_PAGE = "https://search.bilibili.com/all"

        self.BILIBILI_HEADER = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://search.bilibili.com/",
            "Origin": "https://search.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        }
        if self.cfg.cookie:
            self.BILIBILI_HEADER["Cookie"] = self.cfg.cookie
        self._bilibili_cookie_ready = bool(self.cfg.cookie)
        self.session = ClientSession(
            headers=self.BILIBILI_HEADER,
            timeout=ClientTimeout(total=self.cfg.download_timeout),
        )

    async def close(self):
        await self.session.close()

    async def search_video(self, keyword: str, page: int = 1) -> list[dict] | None:
        """
        搜索视频
        """
        params = {"search_type": "video", "keyword": keyword, "page": page}
        await self._ensure_bilibili_cookie(keyword)

        retries = self.cfg.retry_times
        for attempt in range(1, retries + 1):
            try:
                async with self.session.get(
                    self.BILIBILI_SEARCH_API,
                    params=params,
                    headers=self.BILIBILI_HEADER,
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                if data.get("code") == 0:
                    video_list = data["data"].get("result", [])
                    logger.debug(video_list)
                    return video_list

                logger.warning(
                    f"搜索接口返回异常 code={data.get('code')} msg={data.get('message')}"
                )
            except Exception as e:
                logger.warning(f"第 {attempt}/{retries} 次搜索失败: {e}")

            if attempt < retries:
                await asyncio.sleep(1 * attempt)

        logger.error("多次尝试后仍未获取到搜索结果")
        return []

    async def _ensure_bilibili_cookie(self, keyword: str) -> None:
        """Prime anonymous Bilibili cookies before calling the search API."""
        if self._bilibili_cookie_ready:
            return

        try:
            async with self.session.get(
                self.BILIBILI_SEARCH_PAGE,
                params={"keyword": keyword},
                headers={
                    "User-Agent": self.BILIBILI_HEADER["User-Agent"],
                    "Referer": "https://www.bilibili.com/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            ) as response:
                response.raise_for_status()
                await response.read()
            self._bilibili_cookie_ready = True
        except Exception as e:
            logger.warning(f"预热 B站匿名 Cookie 失败: {e}")

    async def get_video_info(self, video_id: str) -> dict | None:
        """获取单个视频的基础信息"""
        try:
            v = video.Video(video_id, credential=Credential(sessdata=""))
            info = await v.get_info()
        except Exception as e:
            logger.error(f"获取视频详情失败: {video_id}, error: {e}")
            return None

        duration_seconds = int(info.get("duration") or 0)
        return {
            "bvid": str(info.get("bvid") or video_id),
            "title": str(info.get("title") or ""),
            "duration": self._format_duration(duration_seconds),
        }

    async def download_video(self, video_id: str) -> Path | None:
        """下载视频"""
        v = video.Video(video_id, credential=Credential(sessdata=""))
        download_url_data = await v.get_download_url(page_index=0)
        detector = VideoDownloadURLDataDetecter(download_url_data)
        streams = detector.detect_best_streams(
            video_max_quality=VideoQuality._720P,
            codecs=[VideoCodecs.AVC],
            no_dolby_video=True,
            no_hdr=True,
        )

        video_stream = streams[0]
        if not isinstance(video_stream, VideoStreamDownloadURL):
            logger.error(f"未找到可下载的视频流：{video_id}")
            return None

        logger.debug(
            f"视频流质量: {video_stream.video_quality.name}, 编码: {video_stream.video_codecs}"
        )

        audio_stream = streams[1] if len(streams) > 1 else None
        if not isinstance(audio_stream, AudioStreamDownloadURL):
            logger.error(f"未找到可下载的音频流：{video_id}")
            return None

        logger.debug(f"音频流质量: {audio_stream.audio_quality.name}")

        video_url, audio_url = video_stream.url, audio_stream.url

        # 构建文件路径
        videos_dir = self.cfg.videos_dir
        video_file = videos_dir / f"{video_id}-video.m4s"
        audio_file = videos_dir / f"{video_id}-audio.m4s"
        output_file = videos_dir / f"{video_id}-res.mp4"

        # 下载视频和音频
        try:
            await asyncio.gather(
                self._download_b_file(video_url, video_file),
                self._download_b_file(audio_url, audio_file),
            )
        except Exception as e:
            logger.error(f"视频/音频下载失败: {e}")
            return None

        # 合并视频和音频
        await self._merge_file_to_mp4(video_file, audio_file, output_file)

        # 删除临时文件
        for f in [video_file, audio_file]:
            if f.exists():
                f.unlink()

        if not output_file.exists():
            logger.error(f"输出文件不存在：{output_file}")
            return None

        return output_file

    async def _download_b_file(self, url: str, save_path: Path):
        async with self.session.get(url) as resp:
            resp.raise_for_status()
            current_len = 0
            total_len = int(resp.headers.get("content-length", 0))
            last_percent = -1

            async with aiofiles.open(save_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    current_len += len(chunk)
                    await f.write(chunk)

                    if total_len:
                        percent = int(current_len / total_len * 100)
                        if percent != last_percent:
                            last_percent = percent
                            self._print_progress_bar(percent, save_path)
            # 下载完成后换行
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _print_progress_bar(self, percent: int, path: Path):
        bar_length = 50
        filled_length = int(bar_length * percent // 100)
        bar = "█" * filled_length + "-" * (bar_length - filled_length)

        # 提取文件名并限制长度，避免刷屏
        file_name = path.name
        if len(file_name) > 30:
            file_name = "..." + file_name[-27:]

        sys.stdout.write(f"\r{file_name:<30} [{bar}] {percent:3d}%")
        sys.stdout.flush()

    async def _merge_file_to_mp4(
        self,
        video_file: Path,
        audio_file: Path,
        output_file: Path,
        log_output: bool = False,
    ) -> None:
        """
        合并视频文件和音频文件
        :param video_file: 视频文件路径
        :param audio_file: 音频文件路径
        :param output_file: 输出文件路径
        :param log_output: 是否显示 ffmpeg 输出日志，默认忽略
        :return:
        """
        logger.info(f"正在合并：{output_file}")

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
            logger.error("合并失败：ffmpeg 未安装或无法找到可执行文件")
            shutil.copy(video_file, output_file)
            logger.warning(f"未找到 ffmpeg，回退为仅视频：{output_file}")
            return

        _, stderr_output = await process.communicate()
        stderr_output = stderr_output.decode().strip() if stderr_output else ""

        if process.returncode != 0:
            logger.error(f"合并失败，FFmpeg 返回码：{process.returncode}")
            if stderr_output:
                logger.error(f"FFmpeg 错误输出：{stderr_output}")
            # 回退为仅发送视频文件
            shutil.copy(video_file, output_file)
            logger.warning(f"合并视频音频失败，回退为仅视频：{output_file}")
        else:
            logger.info(f"合并完成：{output_file}")

    @staticmethod
    def _format_duration(seconds: int) -> str:
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
