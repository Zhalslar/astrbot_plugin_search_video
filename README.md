
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_search_video?name=astrbot_plugin_search_video&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_search_video

_✨ 搜视频插件 ✨_  

[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)
</div>

## 🤝 介绍

搜索视频并下载，让你和群友直接在群内一起刷视频

## 📦 安装

- 安装ffmpeg：本插件依赖于ffmpeg合并视频和音频。

```bash
# Linux（Ubuntu / Debian）系统安装ffmpeg示例：
# 打开终端输入下面的命令
sudo apt update
sudo apt install ffmpeg

# 其他系统自己上网查
```

- 安装本插件：直接在astrbot的插件市场搜索astrbot_plugin_search_video，点击安装，等待完成即可


## ⚙️ 配置

### 插件配置

请在astrbot面板配置，插件管理 -> astrbot_plugin_search_video -> 操作 -> 插件配置

### Docker 部署配置

如果您是 Docker 部署，请务必将消息平台容器和AstrBot挂载容器到同一个文件夹，否则消息平台将无法解析文件路径。

示例挂载方式(NapCat)：

- 对 **AstrBot**：`/vol3/1000/dockerSharedFolder -> /app/sharedFolder`
- 对 **NapCat**：`/vol3/1000/dockerSharedFolder -> /app/sharedFolder`

## ⌨️ 使用说明

指令表

|     命令      |      说明       |
|:-------------:|:-----------------------------:|
| /搜视频 关键词     | 根据关键词搜索视频，然后发送序号“1” “2”等进行选择，发“页2” “页3”等进行翻页  |

示例图
![download](https://github.com/user-attachments/assets/8d2fe20d-bf74-4411-b96c-0ab8da2a5910)

## 👥 贡献指南

- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

## 📌 注意事项

- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561（不点star不给进）
- 本插件依赖ffmpeg，出现合并视频音频失败的报错时，说明ffmpeg没正确安装。
