# 发布说明（Release Notes）

## v1.0.0

**发布日期**：2026-08-04

首个正式版本发布 🎉

### ✨ 新功能

- 现代深色 GUI：文章输入、语音选择、参数调节一屏完成
- 一键试听（前 400 字）与全文导出 MP3
- Daily Manna RPA 原工作流默认：Andrew Multilingual、语速 / 音量 / 音调均为 0；另提供推荐中文女声「晓晓」
- 中英文界面一键切换，支持英文文章、英文语音与 English UI
- 操作按钮固定在语音选择下方，小尺寸窗口也始终可见
- 400+ Edge 语音库，支持搜索、语速 / 音量 / 音调调节
- 网络检测：启动自动探测 Edge TTS 服务连通性，顶部指示灯实时显示状态
- 卡住检测：连续 15 秒无音频数据自动弹窗，提示网络/代理问题并提供「重试 / 取消 / 继续等待」
- 自动重试机制（最多 3 次）与错误分类提示

### 🧡 开源信息

- 开源协议：MIT License
- 开发者：WangYufan
- 仓库：[https://github.com/JJosephph/ms-edge-tts-gui](https://github.com/JJosephph/ms-edge-tts-gui)

### 🛠️ 技术栈

- Python 3.10+ / CustomTkinter / edge-tts / pygame / PyInstaller
- GitHub Actions 自动构建 Windows 单文件版
