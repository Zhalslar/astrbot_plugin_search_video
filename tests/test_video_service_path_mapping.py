from pathlib import Path

from test_bilibili_cookie import _DummyLogger

import sys
import types


astrbot = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
astrbot.logger = _DummyLogger()

astrbot_api_event = types.ModuleType("astrbot.api.event")
astrbot_api_event.AstrMessageEvent = type("AstrMessageEvent", (), {})
astrbot_components = types.ModuleType("astrbot.core.message.components")
astrbot_components.Image = type("Image", (), {})
astrbot_components.Video = type("Video", (), {})
astrbot_aiocq = types.ModuleType(
    "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event"
)
astrbot_aiocq.AiocqhttpMessageEvent = type("AiocqhttpMessageEvent", (), {})

sys.modules.setdefault("astrbot.api.event", astrbot_api_event)
sys.modules.setdefault("astrbot.core.message.components", astrbot_components)
sys.modules.setdefault(
    "astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event", astrbot_aiocq
)

from core.video_service import VideoService


class DummyConfig:
    local_media_path_prefix = ""
    send_media_path_prefix = ""


def test_map_send_video_path_is_disabled_by_default():
    service = VideoService.__new__(VideoService)
    service.cfg = DummyConfig()

    path = "/host/data/videos/a.mp4"

    assert service._map_send_video_path(Path(path)) == path


def test_map_send_video_path_rewrites_configured_prefix():
    service = VideoService.__new__(VideoService)
    service.cfg = DummyConfig()
    service.cfg.local_media_path_prefix = "/host/data/"
    service.cfg.send_media_path_prefix = "/container/data/"

    assert (
        service._map_send_video_path(Path("/host/data/videos/a.mp4"))
        == "/container/data/videos/a.mp4"
    )
