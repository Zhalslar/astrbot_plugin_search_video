from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from yarl import URL

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

Cookies = "ttwid=1%7CufU2AV0XbzAJdZhXH5g6Tm3EHCKnqIaiarg8HFoXlzk%7C1781850091%7C7c7850c735c67d37235e10d2ecec2d75d2b9b8790dc18e2d0261044b4961aa7c; odin_tt=38ba580328e051b7b8b6783e2f29e64670d529c88cf37470dd26673adb0b01f56cfb4af194034a45a9bc29af757d942f; login_time=1781850093929; sid_guard=9223c3e9892c13a3e4242ad4166ce0bd%7C1781850094%7C5184000%7CTue%2C+18-Aug-2026+06%3A21%3A34+GMT; SelfTabRedDotControl=%5B%7B%22id%22%3A%227640915972429187124%22%2C%22u%22%3A24%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227613044971720984576%22%2C%22u%22%3A198%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227618524087740024867%22%2C%22u%22%3A83%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227588527949381371954%22%2C%22u%22%3A25%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227628096047877490730%22%2C%22u%22%3A28%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227587806391285319714%22%2C%22u%22%3A23%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227608884222891296831%22%2C%22u%22%3A30%2C%22c%22%3A0%7D%2C%7B%22id%22%3A%227206753175439673348%22%2C%22u%22%3A62%2C%22c%22%3A0%7D%5D; hevc_supported=true; enter_pc_once=1; uid_tt=4b097d64fb74633011822e0e633ade78; uid_tt_ss=4b097d64fb74633011822e0e633ade78; sid_tt=9223c3e9892c13a3e4242ad4166ce0bd; sessionid=9223c3e9892c13a3e4242ad4166ce0bd; sessionid_ss=9223c3e9892c13a3e4242ad4166ce0bd; session_tlb_tag=sttt%7C11%7CkiPD6YksE6PkJCrUFmzgvf_________aqE4dhAkJIqBHRnN9jXnNe3tOZSljD4OQmln8Ll4DUsI%3D; is_staff_user=false; sid_ucp_v1=1.0.0-KGE2NDYwZmIxNGU3YjNjN2Q0Njk0ZDcwYjI2N2E3MTA4NTk1ODFkYWEKHwiS1d3r6AIQ7r_T0QYY7zEgDDCQ2bLWBTgFQPsHSAQaAmxmIiA5MjIzYzNlOTg5MmMxM2EzZTQyNDJhZDQxNjZjZTBiZA; ssid_ucp_v1=1.0.0-KGE2NDYwZmIxNGU3YjNjN2Q0Njk0ZDcwYjI2N2E3MTA4NTk1ODFkYWEKHwiS1d3r6AIQ7r_T0QYY7zEgDDCQ2bLWBTgFQPsHSAQaAmxmIiA5MjIzYzNlOTg5MmMxM2EzZTQyNDJhZDQxNjZjZTBiZA; bd_ticket_guard_client_web_domain=2; bd_ticket_guard_client_data_v2=eyJyZWVfcHVibGljX2tleSI6IkJDcnBtUGFYK0wra2hFN2pUM1NicDhvb3U4U2ZQdEpmVjN1VHd2YTdCUUhjTVovOGV2N3RGWEpEckp0RXZscDhUZWlkc1RTdVQvaHZJMWRNRldlQ3Vxaz0iLCJ0c19zaWduIjoidHMuMi5hM2RhZjZkYWQyNGRhNzJjMmE2NjczYzBlY2FlNWM4Yzc5NGJhZWY4YzM2YjA4ZmM4ZGIyZGY3ODUxZjM1ZTllYzRmYmU4N2QyMzE5Y2YwNTMxODYyNGNlZGExNDkxMWNhNDA2ZGVkYmViZWRkYjJlMzBmY2U4ZDRmYTAyNTc1ZCIsInJlcV9jb250ZW50Ijoic2VjX3RzIiwicmVxX3NpZ24iOiI4Rm81SHVHTHFYSWtMdlJnTU03clZWSjZnbTdNSzBaV3drUm12dGJ4WXJJPSIsInNlY190cyI6IiNtVW9oOEpCbVhXR0lTV0hPQUlJYXFiMS9CT1diUFhYMFIxL1pjN1dyWjBwVnloN3FlbzhwUWNZNERGbHYifQ%3D%3D; d_ticket=5ce6bc8a52c2c428e43f941e5194590071d23; UIFID_TEMP=a8ba86e673712b7e1f7d182287ae016258de270594e5d0b1b173d0638a9cd7e51803779891c3699349fdf23e81ad224c3ecd8deee1d1c2b3efac001c4e5951ada80b69917d571c45d457bc84bd699dec; fpk1=U2FsdGVkX18/QjTzMjgL2QEeflK62zos3KRHJkLPBCw8/Hs+J53Ox13opThEq+L4mmKl6cMSSfpt00nLCfS+jA==; fpk2=a95ad5176e3cf1a9135a7afeab51572b; UIFID=3c02612a32301e3b85167514a231df4f30ee4810b08c2ee4cebb44ad646cb06f501fcf38f986ef08b77496cc230e04a63c1cf23d059aab3877511ca3f49f008ce1b25bec12bbe6d1f3b826d267e4757fe0259d8562c03f95a51d4bb38d4857f40d1c227a4a23dc9684fffbb057f3864431a0b7b9a52babf37452b857ca15bc008ed81a537a41da60cdabca9e4b3f62484b0a779df30f5bda0ca5a76593deb113; __security_mc_1_s_sdk_crypt_sdk=9bccfad9-4169-a37c; __security_mc_1_s_sdk_cert_key=2079aa0a-443c-a4d9; __security_mc_1_s_sdk_sign_data_key_web_protect=9173fc0c-49b2-bd43; _bd_ticket_crypt_cookie=3c7d6ab9e862860b07e746f21b778b98; xgplayer_device_id=71175857309; xgplayer_user_id=286570275585; PhoneResumeUidCacheV1=%7B%2296862694034%22%3A%7B%22time%22%3A1771552220203%2C%22noClick%22%3A1%7D%7D; s_v_web_id=verify_mo77jcga_PjkE8RiQ_kLbU_4s3A_9Y8D_fODdmX25GQZX; passport_csrf_token=a72f5da666eae613f7ea5d834921f362; passport_csrf_token_default=a72f5da666eae613f7ea5d834921f362; has_biz_token=false; IsDouyinActive=false; home_can_add_dy_2_desktop=%220%22; dy_swidth=1536; dy_sheight=864; stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1536%2C%5C%22screen_height%5C%22%3A864%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A0%2C%5C%22downlink%5C%22%3A%5C%22%5C%22%2C%5C%22effective_type%5C%22%3A%5C%22%5C%22%2C%5C%22round_trip_time%5C%22%3A0%7D%22; is_dash_user=1; volume_info=%7B%22isUserMute%22%3Afalse%2C%22isMute%22%3Afalse%2C%22volume%22%3A1%7D; strategyABtestKey=%221781850059.774%22; publish_badge_show_info=%220%2C0%2C0%2C1781432025193%22; __ac_nonce=06a34df9c0084b3fa2ccf; __ac_signature=_02B4Z6wo00f01suGVXgAAIDA47KStCO-XBrLt1HAANji24; is_support_rtm_web_ts=0; my_rd=2; FOLLOW_NUMBER_YELLOW_POINT_INFO=%22MS4wLjABAAAAIO5ggyIrgvNn6zDDqWOuOVc32CX92lpSEixaSoK7fko%2F1781884800000%2F0%2F1781850034772%2F0%22; biz_trace_id=8c2dc20b; SEARCH_UN_LOGIN_PV_CURR_DAY=%7B%22date%22%3A1781850069768%2C%22count%22%3A2%7D; passport_assist_user=CjwxU9v_4Zm9yJTWfcdZ_z3nmAXOPYqQB184POjV03ylug8ohnonbNJgIyN_Chhdb0lmfXsKi-YaCnIfaL4aSgo8AAAAAAAAAAAAAFCP1oPtEWMZ_mBCfuy-avTdJ5o6EGOjefSKesKcbLo6qoSaDyCjT9mR571Qd_K1FqiDELLJlA4Yia_WVCABIgEDGyO9sA%3D%3D; n_mh=nqdGWqJeqedHXYcMRBmc6ukyf_nP2hlj_HyQtKBOVz4; SEARCH_RESULT_LIST_TYPE=%22single%22; csrf_session_id=a4ac6d3b122afc65a1455fbecc3cfa46; download_guide=%221%2F20260619%2F0%22; douyin.com=; xg_device_score=7.898857142857143; device_web_cpu_core=16; device_web_memory_size=-1; architecture=amd64; FOLLOW_LIVE_POINT_INFO=%22MS4wLjABAAAAIO5ggyIrgvNn6zDDqWOuOVc32CX92lpSEixaSoK7fko%2F1781884800000%2F0%2F1781851094846%2F0%22; bd_ticket_guard_client_data=eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCQ3JwbVBhWCtMK2toRTdqVDNTYnA4b291OFNmUHRKZlYzdVR3dmE3QlFIY01aLzhldjd0RlhKRHJKdEV2bHA4VGVpZHNUU3VUL2h2STFkTUZXZUN1cWs9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D"

HOME_URL = "https://www.douyin.com/"
SEARCH_CASES: list[dict[str, Any]] = [
    {
        "name": "general_search_single",
        "url": "https://www.douyin.com/aweme/v1/web/general/search/single/",
        "params": {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "search_channel": "aweme_general",
            "enable_history": "1",
            "keyword": "python",
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "1",
            "offset": "0",
            "count": "10",
            "list_type": "multi",
            "pc_client_type": "1",
            "version_code": "190600",
            "version_name": "19.6.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "137.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "137.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "8",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
        },
    },
    {
        "name": "discover_search",
        "url": "https://www.douyin.com/aweme/v1/web/discover/search/",
        "params": {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "search_channel": "aweme_general",
            "keyword": "python",
            "search_source": "tab_search",
            "query_correct_type": "1",
            "offset": "0",
            "count": "10",
        },
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/search/python?source=switch_tab&type=video",
    "Accept": "application/json, text/plain, */*",
}


def print_section(title: str) -> None:
    print(f"\n{'=' * 20} {title} {'=' * 20}")


def preview_text(text: str, limit: int = 1000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...<truncated>"


async def fetch_homepage(session: ClientSession) -> None:
    print_section("Homepage")
    async with session.get(HOME_URL, headers=HEADERS) as response:
        body = await response.text()
        print(f"status: {response.status}")
        print(f"content-type: {response.headers.get('content-type')}")
        print(f"set-cookie count: {len(response.headers.getall('set-cookie', []))}")
        print(f"cookie jar: {session.cookie_jar.filter_cookies(URL(HOME_URL))}")
        print(f"body preview: {preview_text(body, 200)}")


async def test_search_case(session: ClientSession, case: dict[str, Any]) -> None:
    print_section(case["name"])
    async with session.get(
        case["url"],
        headers=HEADERS,
        params=case["params"],
    ) as response:
        body = await response.text()
        print(f"url: {response.url}")
        print(f"status: {response.status}")
        print(f"content-type: {response.headers.get('content-type')}")
        print(f"body preview: {preview_text(body)}")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            print("json parse: failed")
            return

        print("json parse: success")
        print(f"top-level keys: {list(data.keys())}")
        print(
            "status fields: "
            f"status_code={data.get('status_code')} "
            f"code={data.get('code')} "
            f"status_msg={data.get('status_msg')} "
            f"message={data.get('message')}"
        )

        data_field = data.get("data")
        if isinstance(data_field, dict):
            print(f"data keys: {list(data_field.keys())[:20]}")
        elif isinstance(data_field, list):
            print(f"data list length: {len(data_field)}")


async def main() -> None:
    print(f"plugin root: {PLUGIN_ROOT}")
    timeout = ClientTimeout(total=30)
    async with ClientSession(timeout=timeout) as session:
        await fetch_homepage(session)
        for case in SEARCH_CASES:
            await test_search_case(session, case)


if __name__ == "__main__":
    asyncio.run(main())
