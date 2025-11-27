import asyncio
import os
import platform
import shutil
import subprocess
import sys

import aiofiles
import httpx
from bilibili_api import Credential, video
from bilibili_api.video import VideoDownloadURLDataDetecter

from astrbot import logger


class VideoAPI():
    """
    视频API类
    """
    def __init__(self, cookie: str):
        self.BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"

        self.BILIBILI_HEADER = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Cookie": cookie,
        }

    async def search_video(self, keyword: str,  page: int = 1) -> list[dict] | None:
        """
        搜索视频
        """
        params = {"search_type": "video", "keyword": keyword, "page": page}
        # B 站偶发 412/超时，做重试
        retries = 3
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(
                        self.BILIBILI_SEARCH_API,
                        params=params,
                        headers=self.BILIBILI_HEADER,
                    )
                response.raise_for_status()
                data = response.json()

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

    async def download_video(self, video_id: str, temp_dir: str) -> str | None:
        """下载视频"""
        # 确保临时目录存在
        os.makedirs(temp_dir, exist_ok=True)

        # 获取视频流和音频流下载链接
        v = video.Video(video_id, credential=Credential(sessdata=""))
        download_url_data = await v.get_download_url(page_index=0)
        detector = VideoDownloadURLDataDetecter(download_url_data)
        streams = detector.detect_best_streams()
        video_url, audio_url = streams[0].url, streams[1].url

        # 构建文件路径
        video_file = os.path.join(temp_dir, f"{video_id}-video.m4s")
        audio_file = os.path.join(temp_dir, f"{video_id}-audio.m4s")
        output_file = os.path.join(temp_dir, f"{video_id}-res.mp4")

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
            if os.path.exists(f):
                os.remove(f)

        if not os.path.exists(output_file):
            logger.error(f"输出文件不存在：{output_file}")
            return None

        return output_file

    async def _download_b_file(
        self, url: str, full_file_name: str
    ):
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=self.BILIBILI_HEADER) as resp:
                current_len = 0
                total_len = int(resp.headers.get("content-length", 0))
                last_percent = -1

                async with aiofiles.open(full_file_name, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        current_len += len(chunk)
                        await f.write(chunk)

                        percent = int(current_len / total_len * 100)
                        if percent != last_percent:
                            last_percent = percent
                            self._print_progress_bar(percent, full_file_name)
                # 下载完成后换行
                sys.stdout.write("\n")
                sys.stdout.flush()


    def _print_progress_bar(self, percent: int, label: str = ""):
        bar_length = 50
        filled_length = int(bar_length * percent // 100)
        bar = "█" * filled_length + "-" * (bar_length - filled_length)

        # 提取文件名并限制长度，避免刷屏
        file_name = os.path.basename(label)
        if len(file_name) > 30:
            file_name = "..." + file_name[-27:]

        sys.stdout.write(f"\r{file_name:<30} [{bar}] {percent:3d}%")
        sys.stdout.flush()


    async def _merge_file_to_mp4(
        self,
        v_full_file_name: str,
        a_full_file_name: str,
        output_file_name: str,
        log_output: bool = False,
    ) -> None:
        """
        合并视频文件和音频文件
        :param v_full_file_name: 视频文件路径
        :param a_full_file_name: 音频文件路径
        :param output_file_name: 输出文件路径
        :param log_output: 是否显示 ffmpeg 输出日志，默认忽略
        :return:
        """
        logger.info(f"正在合并：{output_file_name}")

        # 构建 ffmpeg 命令
        command = f'ffmpeg -y -i "{v_full_file_name}" -i "{a_full_file_name}" -c copy "{output_file_name}"'
        stdout = None if log_output else subprocess.DEVNULL
        stderr = None if log_output else subprocess.PIPE

        if platform.system() == "Windows":
            # Windows 下使用 run_in_executor
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(command, shell=True, stdout=stdout, stderr=stderr),  # noqa: ASYNC221
            )
            stderr_output = process.stderr.decode().strip() if process.stderr else ""
        else:
            # 其他平台使用 create_subprocess_shell
            process = await asyncio.create_subprocess_shell(
                command, shell=True, stdout=stdout, stderr=stderr
            )
            _, stderr_output = await process.communicate()
            stderr_output = stderr_output.decode().strip() if stderr_output else ""

        if process.returncode != 0:
            logger.error(f"合并失败，FFmpeg 返回码：{process.returncode}")
            if stderr_output:
                logger.error(f"FFmpeg 错误输出：{stderr_output}")
            # 回退为仅发送视频文件
            shutil.copy(v_full_file_name, output_file_name)
            logger.warning(f"合并视频音频失败，回退为仅视频：{output_file_name}")
        else:
            logger.info(f"合并完成：{output_file_name}")
