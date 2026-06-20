import uuid

from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

from ..video_service import VideoService


class LLMVideoFlow:
    def __init__(self, context: Context, video_service: VideoService):
        self.context = context
        self.video_service = video_service

    async def search_and_send(
        self,
        event: AstrMessageEvent,
        *,
        platform: str = "bilibili",
        keyword: str = "",
        limit: int = 20,
    ) -> str | None:
        keyword = keyword.strip()
        if not keyword:
            return "未提供搜索词"

        video_list = await self.video_service.search_video(
            keyword=keyword,
            page=1,
            platform=platform,
        )
        if not video_list:
            return "视频搜索结果为空"

        selected_video = await self._choose_video_with_llm(
            event,
            keyword=keyword,
            video_list=video_list,
            limit=limit,
        )
        if not selected_video:
            return "未找到可发送的视频"

        result = self.video_service.schedule_video_send(event, selected_video)
        return result or None

    async def search_video_candidates(
        self,
        *,
        platform: str = "bilibili",
        keyword: str = "",
        limit: int = 20,
    ) -> str:
        video_list = await self.video_service.search_video(
            keyword=keyword,
            page=1,
            platform=platform,
        )
        if not video_list:
            return "视频搜索结果为空"

        candidates = self.video_service.build_video_candidates(video_list, limit=limit)
        return self.video_service.format_video_candidates_text(keyword, candidates)

    async def send_video_by_bvid(
        self,
        event: AstrMessageEvent,
        *,
        platform: str = "bilibili",
        video_id: str = "",
    ) -> str:
        video_id = video_id.strip()
        if not video_id:
            return "未提供视频 ID"

        info = await self.video_service.get_video_info(
            video_id=video_id,
            platform=platform,
        )
        if not info:
            return "获取视频详情失败"

        return self.video_service.schedule_video_send(event, info)

    async def _choose_video_with_llm(
        self,
        event: AstrMessageEvent,
        *,
        keyword: str,
        video_list: list[dict],
        limit: int,
    ) -> dict | None:
        candidates = self.video_service.build_video_candidates(video_list, limit=limit)
        if not candidates:
            return None

        fallback_video = self.video_service.find_video_by_id(
            video_list,
            candidates[0]["video_id"],
        )
        if fallback_video is None:
            fallback_video = {
                "platform": candidates[0]["platform"],
                "video_id": candidates[0]["video_id"],
                "title": candidates[0]["title"],
                "duration": candidates[0]["duration"],
            }

        try:
            provider_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=(
                    "你是视频候选筛选器。"
                    "你只能从候选列表中选择一项。"
                    "只输出一个 video_id，不要输出解释、标点、引号或其他任何文字。"
                ),
                prompt=(
                    f"用户需求: {keyword}\n"
                    f"{self.video_service.format_video_candidates_text(keyword, candidates)}\n"
                    "请选择最匹配的一项，只输出一个 video_id。"
                ),
                session_id=uuid.uuid4().hex,
                persist=False,
            )
            selected_video_id = self.video_service.extract_candidate_video_id(
                llm_resp.completion_text if llm_resp else "",
                candidates,
            )
            if selected_video_id:
                selected_video = self.video_service.find_video_by_id(
                    video_list,
                    selected_video_id,
                )
                if selected_video is not None:
                    return selected_video

            logger.warning(
                "internal AI selector returned invalid result, fallback to first candidate. keyword=%s response=%s",
                keyword,
                llm_resp.completion_text if llm_resp else "",
            )
        except Exception as exc:
            logger.warning("internal AI selector failed, fallback to first candidate: %s", exc)

        return fallback_video
