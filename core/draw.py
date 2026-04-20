import asyncio
from io import BytesIO

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

from astrbot import logger

from .config import PluginConfig
from .downloader import ImageDownloader


class VideoCardTheme:
    """视频卡片主题"""

    # 尺寸
    card_width: int = 300
    card_height: int = 250
    thumb_height: int = 168
    margin: int = 16
    corner_radius: int = 10

    # 字体
    font_size: int = 16

    # 颜色
    card_bg: str = "#ffffff"
    canvas_bg: str = "#f5f5f5"
    title_color: str = "#000000"
    sub_text_color: str = "#666666"
    overlay_text_color: str = "#ffffff"

    # 渐变
    gradient_height: int = 40
    gradient_max_alpha: int = 180

    def load_font(self, font_path: str) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(font_path, self.font_size)


class VideoCardRenderer:
    """
    视频卡片渲染器
    """

    def __init__(
        self,
        config: PluginConfig,
        downloader: ImageDownloader,
        theme: VideoCardTheme | None = None,
    ):
        self.cfg = config
        self.downloader = downloader
        self.theme = theme or VideoCardTheme()
        self.font = self.theme.load_font(str(self.cfg.font_path))

    def format_count(self, count: int) -> str:
        if count >= 10000:
            return f"{count / 10000:.1f}万"
        elif count >= 1000:
            return f"{count / 1000:.1f}千"
        return str(count)

    async def draw_card(self, video: dict, index: int) -> Image.Image:
        try:
            t = self.theme
            font = self.font

            # 卡片底图
            card = Image.new(
                "RGBA",
                (t.card_width, t.card_height),
                t.card_bg,
            )
            draw = ImageDraw.Draw(card)

            # 封面
            raw_url = video.get("pic", "")
            pic_url = raw_url if raw_url.startswith("http") else ("https:" + raw_url)
            thumb = await self.downloader.fetch(pic_url)
            thumb = thumb.resize((t.card_width, t.thumb_height))
            card.paste(thumb, (0, 0))

            # 渐变遮罩
            alpha_gradient = Image.new(
                "L",
                (t.card_width, t.gradient_height),
                color=0,
            )
            gradient_draw = ImageDraw.Draw(alpha_gradient)
            for y in range(t.gradient_height):
                alpha = int(t.gradient_max_alpha * (y / t.gradient_height))
                gradient_draw.line(
                    [(0, y), (t.card_width, y)],
                    fill=alpha,
                )

            overlay = Image.new(
                "RGBA",
                (t.card_width, t.gradient_height),
                color=(0, 0, 0, 255),
            )
            overlay.putalpha(alpha_gradient)
            card.paste(
                overlay,
                (0, t.thumb_height - t.gradient_height),
                overlay,
            )

            # 播放量
            draw.text(
                (8, t.thumb_height - 20),
                self.format_count(video["play"]),
                font=font,
                fill=t.overlay_text_color,
            )

            # 时长
            draw.text(
                (t.card_width - 40, t.thumb_height - 20),
                video["duration"],
                font=font,
                fill=t.overlay_text_color,
            )

            # 标题
            raw_title = BeautifulSoup(video["title"], "html.parser").get_text()
            title = (
                raw_title[:18] + "\n" + raw_title[18:36] + "..."
                if len(raw_title) > 36
                else raw_title[:18] + "\n" + raw_title[18:]
            )
            draw.text(
                (8, t.thumb_height + 8),
                title,
                font=font,
                fill=t.title_color,
            )

            # 作者
            draw.text(
                (8, t.thumb_height + 60),
                f"UP {video['author']}",
                font=font,
                fill=t.sub_text_color,
            )

            # 序号
            draw.text(
                (t.card_width - 30, t.card_height - 20),
                str(index),
                font=font,
                fill=t.sub_text_color,
            )

            # 圆角遮罩
            mask = Image.new("L", (t.card_width, t.card_height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                (0, 0, t.card_width, t.card_height),
                radius=t.corner_radius,
                fill=255,
            )
            card.putalpha(mask)

            return card

        except Exception as e:
            logger.error(f"[错误] 渲染卡片失败: {e}")
            return Image.new(
                "RGBA",
                (self.theme.card_width, self.theme.card_height),
                self.theme.card_bg,
            )

    async def render_video_list_image(self, video_list: list) -> bytes:
        t = self.theme
        tasks = [
            self.draw_card(video, index=i + 1) for i, video in enumerate(video_list)
        ]
        cards = await asyncio.gather(*tasks)

        # 拼接行
        rows: list[Image.Image] = []
        per_row = self.cfg.cards_per_row
        for i in range(0, len(cards), per_row):
            row_cards = cards[i : i + per_row]
            row_width = per_row * t.card_width + (per_row + 1) * t.margin
            row_img = Image.new(
                "RGBA",
                (row_width, t.card_height + 2 * t.margin),
                t.canvas_bg,
            )
            for j, card in enumerate(row_cards):
                x = t.margin + j * (t.card_width + t.margin)
                row_img.paste(card, (x, t.margin), card)
            rows.append(row_img)

        # 合并所有行
        total_width = rows[0].width
        total_height = sum(row.height for row in rows)
        canvas = Image.new(
            "RGBA",
            (total_width, total_height),
            t.canvas_bg,
        )

        y_offset = 0
        for row in rows:
            canvas.paste(row, (0, y_offset), row)
            y_offset += row.height

        # 转 JPEG
        final_image = Image.new("RGB", canvas.size, t.canvas_bg)
        final_image.paste(canvas, mask=canvas.split()[3])

        buffer = BytesIO()
        final_image.save(buffer, format="JPEG", quality=self.cfg.jpeg_quality)
        return buffer.getvalue()
