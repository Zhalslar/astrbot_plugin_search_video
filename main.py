import copy
from bs4 import BeautifulSoup

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Image, Video
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .core.api import VideoAPI
from .core.draw import VideoCardRenderer
from .core.config import PluginConfig
from .core.utils import extract_page_number, duration_to_seconds, upload_file
from .core.downloader import ImageDownloader

class VideoSearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config)
        self.api = VideoAPI(self.cfg)
        self.image_downloader = ImageDownloader(self.cfg)
        self.renderer = VideoCardRenderer(self.cfg, self.image_downloader)

    async def _send_video_list_image(
        self, event: AstrMessageEvent, video_list: list[dict]
    ):
        image = await self.renderer.render_video_list_image(video_list)
        await event.send(event.chain_result([Image.fromBytes(image)]))

    @filter.command("搜视频")
    async def search_video_handle(self, event: AstrMessageEvent):
        """搜视频 <关键词>"""
        keyword = event.message_str.partition(" ")[2].strip()
        if not keyword:
            yield event.plain_result("未提供搜索词")
            return

        video_list = await self.api.search_video(keyword=keyword, page=1)
        if not video_list:
            yield event.plain_result("搜索结果为空")
            return

        await self._send_video_list_image(event, video_list)

        if self.cfg.show_guidance_prompt:
            await event.send(
                event.plain_result(
                    f"请在{self.cfg.timeout}秒内回复序号进行下载，回复'n页'以跳转"
                )
            )

        try:
            await self._wait_user_selection(event, keyword, [video_list])
        except TimeoutError:
            logger.info("搜索视频：用户选择超时")
        except Exception as e:
            logger.error(f"搜索视频发生错误: {e}")
        finally:
            event.stop_event()


    # ==========================================================
    # 会话等待 & 分发
    # ==========================================================
    async def _wait_user_selection(
        self,
        event: AstrMessageEvent,
        keyword: str,
        videos: list[list[dict]],
    ):
        timeout = self.cfg.timeout
        umo = event.unified_msg_origin
        sender_id = event.get_sender_id()

        @session_waiter(timeout=timeout)  # type: ignore
        async def waiter(controller: SessionController, event: AstrMessageEvent):
            if not self._is_same_session(umo, sender_id, event):
                return

            arg = event.message_str.strip()

            if await self._handle_page_turn(event, controller, keyword, videos, arg):
                return

            if await self._handle_video_select(event, controller, videos, arg):
                return

            await self._fallback_to_llm(event, controller)

        await waiter(event)  # type: ignore

    def _is_same_session(
        self, umo: str, sender_id: str, event: AstrMessageEvent
    ) -> bool:
        return umo == event.unified_msg_origin and sender_id == event.get_sender_id()


    async def _handle_page_turn(
        self,
        event: AstrMessageEvent,
        controller: SessionController,
        keyword: str,
        videos: list[list[dict]],
        arg: str,
    ) -> bool:
        page = extract_page_number(arg)
        if page is None:
            return False

        if page < 1:
            await event.send(event.plain_result("请输入大于等于 1 的页码"))
            return True

        controller.keep(timeout=self.cfg.timeout, reset_timeout=True)

        new_videos = await self.api.search_video(keyword=keyword, page=page)
        if not new_videos:
            await event.send(event.plain_result("没有找到更多相关视频"))
            return True

        videos.append(new_videos)
        await self._send_video_list_image(event, new_videos)
        return True

    async def _handle_video_select(
        self,
        event: AstrMessageEvent,
        controller: SessionController,
        videos: list[list[dict]],
        arg: str,
    ) -> bool:
        if not arg.isdigit():
            return False

        index = int(arg) - 1
        current_page = videos[-1]

        if index < 0 or index >= len(current_page):
            return False

        controller.stop()
        await self._send_video(event, current_page[index])
        return True

    async def _fallback_to_llm(
        self, event: AstrMessageEvent, controller: SessionController
    ):
        new_event = copy.copy(event)
        new_event.clear_result()
        self.context.get_event_queue().put_nowait(new_event)
        event.stop_event()
        controller.stop()

    # ==========================================================
    # 视频发送逻辑
    # ==========================================================
    async def _send_video(self, event: AstrMessageEvent, video: dict):
        video_id = video.get("bvid", "")
        raw_title = video.get("title", "")
        title = BeautifulSoup(raw_title, "html.parser").get_text()
        duration = duration_to_seconds(video.get("duration", "0"))

        if duration > self.cfg.max_duration:
            video_url = f"https://www.bilibili.com/video/{video_id}"
            await event.send(
                event.plain_result(
                    f"视频超过{self.cfg.max_duration / 60:.0f}分钟，改用链接：{video_url}"
                )
            )
            return

        if self.cfg.show_download_prompt:
            await event.send(event.plain_result(f"正在下载: {title}"))

        logger.info(f"正在下载视频: {title}")
        video_path = await self.api.download_video(video_id)

        if not video_path:
            await event.send(event.plain_result("下载视频失败"))
            return

        try:
            if (
                isinstance(event, AiocqhttpMessageEvent)
                and video_path.stat().st_size > 100 * 1024 * 1024
            ):
                await upload_file(event, video_path)
            else:
                chain = [Video.fromFileSystem(str(video_path))]
                await event.send(event.chain_result(chain))  # type: ignore
        except Exception as e:
            logger.error(f"发送视频失败: {e}")
        finally:
            if not self.cfg.is_save and video_path.exists():
                video_path.unlink()
