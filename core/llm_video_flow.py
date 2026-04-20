import uuid

from astrbot import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

from .video_service import VideoService


class LLMVideoFlow:
    def __init__(self, context: Context, video_service: VideoService):
        self.context = context
        self.video_service = video_service

    async def search_and_send(
        self,
        event: AstrMessageEvent,
        *,
        keyword: str = "",
        limit: int = 20,
    ) -> str | None:
        keyword = keyword.strip()
        if not keyword:
            return "未提供搜索词"

        video_list = await self.video_service.search_video(keyword=keyword, page=1)
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
        keyword: str = "",
        limit: int = 20,
    ) -> str:
        video_list = await self.video_service.search_video(keyword=keyword, page=1)
        if not video_list:
            return "视频搜索结果为空"

        candidates = self.video_service.build_video_candidates(video_list, limit=limit)
        return self.video_service.format_video_candidates_text(keyword, candidates)

    async def send_video_by_bvid(
        self,
        event: AstrMessageEvent,
        *,
        bvid: str = "",
    ) -> str:
        bvid = bvid.strip()
        if not bvid:
            return "未提供 bvid"

        info = await self.video_service.get_video_info(bvid)
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

        fallback_video = self.video_service.find_video_by_bvid(
            video_list, candidates[0]["bvid"]
        )
        if fallback_video is None:
            fallback_video = {
                "bvid": candidates[0]["bvid"],
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
                    "只输出一个 bvid，不要输出解释、标点、引号或其他任何文字。"
                ),
                prompt=(
                    f"用户需求: {keyword}\n"
                    f"{self.video_service.format_video_candidates_text(keyword, candidates)}\n"
                    "请选择最匹配的一项，只输出一个 bvid。"
                ),
                session_id=uuid.uuid4().hex,
                persist=False,
            )
            selected_bvid = self.video_service.extract_candidate_bvid(
                llm_resp.completion_text if llm_resp else "",
                candidates,
            )
            if selected_bvid:
                selected_video = self.video_service.find_video_by_bvid(
                    video_list, selected_bvid
                )
                if selected_video is not None:
                    return selected_video

            logger.warning(
                "内部 AI 选片返回无效结果，回退首个候选。keyword=%s response=%s",
                keyword,
                llm_resp.completion_text if llm_resp else "",
            )
        except Exception as e:
            logger.warning(f"内部 AI 选片失败，回退首个候选: {e}")

        return fallback_video
