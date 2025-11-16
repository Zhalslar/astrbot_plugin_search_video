import os

from bs4 import BeautifulSoup

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Image, Video
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from .api import VideoAPI
from .draw import VideoCardRenderer


@register("astrbot_plugin_search_video", "Zhalslar", "...", "...")
class VideoPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 哔哩哔哩限制的最大视频时长（默认8分钟），单位：秒
        self.max_duration: int = config.get("max_duration", 600)
        # B站cookie
        self.cookie: str = config.get("cookie", "")
        # 实例化api
        self.api = VideoAPI(self.cookie)
        # 画图类
        self.renderer = VideoCardRenderer()
        # 候选菜单的列数
        self.cards_per_row: int = config.get("cards_per_row", 18)
        # 超时时间
        self.timeout: int = config.get("timeout", 60)
        # 是否保存视频
        self.is_save: bool = config.get("is_save", True)
        # 视频缓存路径
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_search_video")

    @filter.command("搜视频")
    async def search_video_handle(self, event: AstrMessageEvent):
        """搜索视频"""

        # 获取用户输入的视频名称
        video_name = event.message_str.replace("搜视频", "")

        # 获取搜索结果
        video_list = await self.api.search_video(keyword=video_name, page=1)
        if not video_list:
            yield event.plain_result("没有找到相关视频")
            return
        videos: list[list] = [video_list]
        # 展示搜索结果
        image: bytes = await self.renderer.render_video_list_image(
            videos[0],
            cards_per_row=self.cards_per_row,
        )
        await event.send(event.chain_result([Image.fromBytes(image)]))

        umo = event.unified_msg_origin
        sender_id = event.get_sender_id()

        # 等待用户选择视频
        @session_waiter(timeout=self.timeout)  # type: ignore
        async def empty_mention_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            if umo != event.unified_msg_origin or sender_id != event.get_sender_id():
                return
            input = event.message_str

            # 翻页机制
            if input.startswith("页") and input[-1].isdigit():
                # 重置超时时间
                controller.keep(timeout=self.timeout, reset_timeout=True)
                video_list_new = await self.api.search_video(
                    keyword=video_name, page=int(input[-1])
                )
                if not video_list_new:
                    await event.send(event.plain_result("没有找到更多相关视频"))
                    return
                videos.append(video_list_new)
                image: bytes = await self.renderer.render_video_list_image(
                    video_list_new,
                    cards_per_row=self.cards_per_row,
                )
                await event.send(event.chain_result([Image.fromBytes(image)]))
                return

            # 验证输入序号
            elif not input.isdigit() or int(input) < 1 or int(input) > len(videos[-1]):
                await event.send(event.plain_result("已退出视频搜索！"))
                controller.stop()
                return

            # 先停止会话，防止下载视频时出现“再次输入”
            controller.stop()
            # 获取视频信息
            video = videos[-1][int(input) - 1]
            video_id: str = video.get("bvid", "")
            raw_title = video["title"]
            title = BeautifulSoup(raw_title, "html.parser").get_text()[0:9]
            duration_str: str = video.get("duration", "0")

            # 视频时长是否超过最大时长时发链接，否则发送视频
            duration = self.convert_duration_to_seconds(duration_str)
            if duration > self.max_duration:
                video_url = f"https://www.bilibili.com/video/{video_id}"
                await event.send(
                    event.plain_result(
                        f"视频超过{self.max_duration / 60}分钟改用链接：{video_url}"
                    )
                )
            else:
                await event.send(event.plain_result(f"正在下载: {raw_title}"))
                logger.info(f"正在下载视频:{raw_title}")
                data_path = await self.api.download_video(
                    video_id, str(self.plugin_data_dir)
                )
                if data_path:
                    await self.send_video(event, data_path)

        try:
            await empty_mention_waiter(event)  # type: ignore
        except TimeoutError as _:
            yield event.plain_result("操作超时！")
        except Exception as e:
            logger.error("搜索视频发生错误" + str(e))
        finally:
            event.stop_event()

    async def send_video(self, event: AstrMessageEvent, data_path: str):
        """发送视频"""
        try:
            # 检测文件大小(如果视频大于 100 MB 自动转换为群文件)
            file_size_mb = int(os.path.getsize(data_path) / (1024 * 1024))
            if file_size_mb > 100:
                if event.get_platform_name() == "aiocqhttp":
                    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                        AiocqhttpMessageEvent,
                    )

                    assert isinstance(event, AiocqhttpMessageEvent)
                    client = event.bot
                    group_id = event.get_group_id()
                    name = data_path.split("/")[-1]
                    if group_id:
                        # 上传群文件
                        await client.upload_group_file(
                            group_id=group_id, file=data_path, name=name
                        )
                    else:
                        # 上传私聊文件
                        await client.upload_private_file(
                            user_id=int(event.get_sender_id()),
                            file=data_path,
                            name=name,
                        )
                    return
            await event.send(event.chain_result([Video.fromFileSystem(data_path)]))
        except Exception as e:
            logger.error(f"解析发送出现错误，具体为\n{e}")
        finally:
            if not self.is_save and os.path.exists(data_path):
                os.unlink(data_path)

    @staticmethod
    def convert_duration_to_seconds(duration_str):
        """将视频时长从 'HH:MM:SS'、'MM:SS' 或 'SS' 格式转换为秒"""
        if not duration_str:
            return 0
        seconds = 0
        parts = duration_str.split(":")
        for i, part in enumerate(reversed(parts)):
            if i == 0:
                seconds += int(part)
            elif i == 1:
                seconds += int(part) * 60
            elif i == 2:
                seconds += int(part) * 3600
        return seconds
