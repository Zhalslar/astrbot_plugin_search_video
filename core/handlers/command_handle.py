import copy

from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from ..config import PluginConfig
from ..utils import extract_page_number
from ..video_service import VideoService


class CommandVideoFlow:
    def __init__(
        self,
        context: Context,
        config: PluginConfig,
        video_service: VideoService,
    ):
        self.context = context
        self.cfg = config
        self.video_service = video_service

    async def handle_search_command(
        self,
        event: AstrMessageEvent,
        *,
        platform: str,
    ) -> str | None:
        keyword = event.message_str.partition(" ")[2].strip()
        if not keyword:
            return "未提供搜索词"

        video_list = await self.video_service.search_video(
            keyword=keyword,
            page=1,
            platform=platform,
        )
        if not video_list:
            return "搜索结果为空"

        await self.video_service.send_video_list_image(event, video_list)

        if self.cfg.show_guidance_prompt:
            await event.send(
                event.plain_result(
                    f"请在{self.cfg.select_timeout}秒内回复序号进行下载，回复 n页 进行翻页"
                )
            )

        try:
            await self._wait_user_selection(event, platform, keyword, [video_list])
        except TimeoutError:
            logger.info("搜索视频：用户选择超时")
        except Exception as exc:
            logger.error("搜索视频发生错误: %s", exc)
        finally:
            event.stop_event()

        return None

    async def _wait_user_selection(
        self,
        event: AstrMessageEvent,
        platform: str,
        keyword: str,
        videos: list[list[dict]],
    ) -> None:
        umo = event.unified_msg_origin
        sender_id = event.get_sender_id()

        @session_waiter(timeout=self.cfg.select_timeout)  # type: ignore
        async def waiter(controller: SessionController, event: AstrMessageEvent):
            if not self._is_same_session(umo, sender_id, event):
                return

            arg = event.message_str.strip()

            if await self._handle_page_turn(
                event,
                controller,
                platform,
                keyword,
                videos,
                arg,
            ):
                return

            if await self._handle_video_select(event, controller, videos, arg):
                return

            await self._fallback_to_llm(event, controller)

        await waiter(event)  # type: ignore

    @staticmethod
    def _is_same_session(umo: str, sender_id: str, event: AstrMessageEvent) -> bool:
        return umo == event.unified_msg_origin and sender_id == event.get_sender_id()

    async def _handle_page_turn(
        self,
        event: AstrMessageEvent,
        controller: SessionController,
        platform: str,
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

        controller.keep(timeout=self.cfg.select_timeout, reset_timeout=True)

        new_videos = await self.video_service.search_video(
            keyword=keyword,
            page=page,
            platform=platform,
        )
        if not new_videos:
            await event.send(event.plain_result("没有找到更多相关视频"))
            return True

        videos.append(new_videos)
        await self.video_service.send_video_list_image(event, new_videos)
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
        result = self.video_service.schedule_video_send(event, current_page[index])
        if result:
            await event.send(event.plain_result(result))
        return True

    async def _fallback_to_llm(
        self,
        event: AstrMessageEvent,
        controller: SessionController,
    ) -> None:
        new_event = copy.copy(event)
        new_event.clear_result()
        self.context.get_event_queue().put_nowait(new_event)
        event.stop_event()
        controller.stop()
