from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .core.command_video_flow import CommandVideoFlow
from .core.config import PluginConfig
from .core.llm_video_flow import LLMVideoFlow
from .core.video_service import VideoService


class VideoSearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = PluginConfig(config, context)
        self.video_service = VideoService(self.cfg)
        self.command_flow = CommandVideoFlow(
            self.context, self.cfg, self.video_service
        )
        self.llm_flow = LLMVideoFlow(self.context, self.video_service)

    async def initialize(self):
        pass

    async def terminate(self):
        await self.video_service.close()

    @filter.command("搜视频")
    async def search_video_handle(self, event: AstrMessageEvent):
        """搜视频 <关键词>"""
        result = await self.command_flow.handle_search_command(event)
        if result:
            yield event.plain_result(result)

    @filter.llm_tool()
    async def llm_search_and_send_video(
        self,
        event: AstrMessageEvent,
        keyword: str = "",
        limit: int = 20,
    ):
        """
        搜索视频、内部挑选最合适的候选，并自动发送给用户。
        Args:
            keyword(string): 搜索关键词
            limit(int): 候选数量上限, 默认20
        """
        return await self.llm_flow.search_and_send(
            event,
            keyword=keyword,
            limit=limit,
        )
