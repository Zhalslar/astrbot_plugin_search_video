import sys
import types
from pathlib import Path

import pytest
from aiohttp import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _DummyLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass


astrbot = types.ModuleType("astrbot")
astrbot_api = types.ModuleType("astrbot.api")
astrbot_api.logger = _DummyLogger()
astrbot_core = types.ModuleType("astrbot.core")
astrbot_core_config = types.ModuleType("astrbot.core.config")
astrbot_config = types.ModuleType("astrbot.core.config.astrbot_config")
astrbot_star = types.ModuleType("astrbot.core.star")
astrbot_star_context = types.ModuleType("astrbot.core.star.context")
astrbot_star_tools = types.ModuleType("astrbot.core.star.star_tools")
astrbot_utils = types.ModuleType("astrbot.core.utils")
astrbot_path = types.ModuleType("astrbot.core.utils.astrbot_path")


class _AstrBotConfig(dict):
    def save_config(self):
        pass


class _Context:
    pass


class _StarTools:
    @staticmethod
    def get_data_dir(name):
        return Path("/tmp") / name


astrbot_config.AstrBotConfig = _AstrBotConfig
astrbot_star_context.Context = _Context
astrbot_star_tools.StarTools = _StarTools
astrbot_path.get_astrbot_plugin_path = lambda: "/tmp"
sys.modules.setdefault("astrbot", astrbot)
sys.modules.setdefault("astrbot.api", astrbot_api)
sys.modules.setdefault("astrbot.core", astrbot_core)
sys.modules.setdefault("astrbot.core.config", astrbot_core_config)
sys.modules.setdefault("astrbot.core.config.astrbot_config", astrbot_config)
sys.modules.setdefault("astrbot.core.star", astrbot_star)
sys.modules.setdefault("astrbot.core.star.context", astrbot_star_context)
sys.modules.setdefault("astrbot.core.star.star_tools", astrbot_star_tools)
sys.modules.setdefault("astrbot.core.utils", astrbot_utils)
sys.modules.setdefault("astrbot.core.utils.astrbot_path", astrbot_path)


class _Credential:
    def __init__(self, *args, **kwargs):
        pass


bilibili_api = types.ModuleType("bilibili_api")
bilibili_api.Credential = _Credential
bilibili_video = types.ModuleType("bilibili_api.video")

for name in (
    "AudioStreamDownloadURL",
    "VideoCodecs",
    "VideoDownloadURLDataDetecter",
    "VideoQuality",
    "VideoStreamDownloadURL",
):
    setattr(bilibili_video, name, type(name, (), {}))

bilibili_api.video = bilibili_video
sys.modules.setdefault("bilibili_api", bilibili_api)
sys.modules.setdefault("bilibili_api.video", bilibili_video)

from core.api import VideoAPI


class _Config:
    def __init__(self, cookie=""):
        self.cookie = cookie
        self.download_timeout = 60
        self.retry_times = 1


class _Response:
    def __init__(self, data=None):
        self.data = data or {"code": 0, "data": {"result": []}}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        pass

    async def read(self):
        return b""

    async def json(self):
        return self.data


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


class _FailingPrimingSession(_Session):
    def __init__(self, priming_url: str):
        super().__init__()
        self.priming_url = priming_url
        self.priming_failed = False

    def get(self, url, **kwargs):
        if url == self.priming_url and not self.priming_failed:
            self.priming_failed = True
            raise ClientError("priming request failed")
        return super().get(url, **kwargs)


@pytest.mark.asyncio
async def test_search_primes_anonymous_cookie_before_api_call():
    api = VideoAPI.__new__(VideoAPI)
    api.cfg = _Config()
    api.BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    api.BILIBILI_SEARCH_PAGE = "https://search.bilibili.com/all"
    api.BILIBILI_HEADER = {"User-Agent": "UA", "Accept": "application/json"}
    api._bilibili_cookie_ready = False
    api.session = _Session()

    await api.search_video("牢关打法")

    assert api.session.calls[0][0] == api.BILIBILI_SEARCH_PAGE
    assert api.session.calls[0][1]["params"] == {"keyword": "牢关打法"}
    assert api.session.calls[1][0] == api.BILIBILI_SEARCH_API
    assert api.session.calls[0][1]["headers"] == {
        "User-Agent": "UA",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    assert "Cookie" not in api.BILIBILI_HEADER


@pytest.mark.asyncio
async def test_configured_cookie_skips_cookie_priming():
    api = VideoAPI.__new__(VideoAPI)
    api.cfg = _Config(cookie="SESSDATA=abc")
    api.BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    api.BILIBILI_SEARCH_PAGE = "https://search.bilibili.com/all"
    api.BILIBILI_HEADER = {
        "User-Agent": "UA",
        "Accept": "application/json",
        "Cookie": api.cfg.cookie,
    }
    api._bilibili_cookie_ready = True
    api.session = _Session()

    await api.search_video("牢关打法")

    assert [call[0] for call in api.session.calls] == [api.BILIBILI_SEARCH_API]
    assert api.BILIBILI_HEADER["Cookie"] == "SESSDATA=abc"


@pytest.mark.asyncio
async def test_search_continues_when_cookie_priming_fails():
    api = VideoAPI.__new__(VideoAPI)
    api.cfg = _Config()
    api.BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    api.BILIBILI_SEARCH_PAGE = "https://search.bilibili.com/all"
    api.BILIBILI_HEADER = {"User-Agent": "UA", "Accept": "application/json"}
    api._bilibili_cookie_ready = False
    api.session = _FailingPrimingSession(api.BILIBILI_SEARCH_PAGE)

    await api.search_video("牢关打法")

    assert api.session.priming_failed is True
    assert [call[0] for call in api.session.calls] == [api.BILIBILI_SEARCH_API]
    assert api._bilibili_cookie_ready is False
