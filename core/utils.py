from pathlib import Path

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


async def upload_file(event: AiocqhttpMessageEvent, video_path: Path):
    """上传文件"""
    if event.is_private_chat():
        await event.bot.upload_private_file(
            user_id=int(event.get_sender_id()),
            file=str(video_path),
            name=video_path.name,
        )
    else:
        await event.bot.upload_group_file(
            group_id=int(event.get_group_id()),
            file=str(video_path),
            name=video_path.name,
        )


def duration_to_seconds(duration_str):
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


def extract_page_number(text: str) -> int | None:
    """解析 n页 / 页n，确保页码为纯数字"""
    candidate = None
    if text.startswith("页"):
        candidate = text[1:]
    elif text.endswith("页"):
        candidate = text[:-1]

    if candidate is None or not candidate.isdigit():
        return None
    return int(candidate)
