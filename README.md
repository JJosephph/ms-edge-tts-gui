# 🎙️ Edge TTS 语音合成助手

> 把文章一键变成自然语音：输入文本，**试听**满意后**导出 MP3** 到电脑。
> 基于微软 Edge 在线语音合成引擎（`edge-tts`），免费、无需 API Key。

![License](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
[![GitHub](https://img.shields.io/badge/GitHub-JJosephph%2Fms--edge--tts--gui-181717?logo=github)](https://github.com/JJosephph/ms-edge-tts-gui)

---

## ✨ 功能特性

- 📝 **文本转语音**：粘贴文章（支持 Markdown / 纯文本 / HTML），一键合成自然语音。
- ▶️ **试听**：生成前 400 字快速试听，满意再导出，不浪费流量。
- ⬇️ **导出 MP3**：全文合成并保存到电脑任意位置。
- 🗣️ **原工作流默认 + 女声推荐**：默认保持 Daily Manna RPA 的 `Andrew Multilingual`、语速 `+0%`、音量 `+0%`、音调 `+0Hz`；同时将中文女声「晓晓」置于推荐语音，随时一键切换。
- 🌍 **双语界面**：右上角 `EN / 中文` 一键切换；同时支持英文文章、英文语音与英文界面。
- 🌐 **网络检测**：实时探测 Edge TTS 服务连通性；网络不通或代理异常时明确提示。
- ⏱️ **卡住检测**：长时间收不到音频数据时，弹窗提示「可能是网络问题」，可选重试 / 取消 / 继续等待。
- 🧡 **开源软件**：MIT 许可，仓库地址与开发者信息已在界面展示。

## 🖼️ 界面预览

> 截图占位：启动 `run.bat` 或 `python app.py` 即可看到现代化深色界面。

## ⚙️ 环境要求

- Python 3.10 或更高（建议 3.11+）
- 可正常访问微软 Edge 语音服务（国内网络通常无需代理；如使用代理请确保代理可用）

## 🚀 快速开始

### 方式一：源码运行（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/JJosephph/ms-edge-tts-gui.git
cd ms-edge-tts-gui

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt

# 3. 启动
python app.py
```

### 方式二：一键启动（Windows）

双击根目录的 **`run.bat`**，脚本会自动创建虚拟环境、安装依赖并启动程序。

### 方式三：下载发布版（推荐给普通用户）

到 [Releases](https://github.com/JJosephph/ms-edge-tts-gui/releases) 下载，无需安装 Python，**内置运行环境，下载即用**：

- **`EdgeTTSGui-Setup.exe`** —— 定制安装程序（推荐）：
  - 欢迎页说明「来自开源项目，制作人 WangYufan」；
  - 可选择安装到任意盘符 / 目录；
  - 自动创建桌面与开始菜单快捷方式；
  - 安装完成引导「去 GitHub ⭐ Star」支持开源；
  - 自带卸载程序。
- **`EdgeTTSGui-Portable.exe`** —— 便携单文件版，双击即用，适合绿色免安装。

## 🧑‍💻 使用说明

1. **输入文章**：在左侧输入框粘贴文章内容。
2. **选择语音**：默认已经选中原 Daily Manna 工作流的 Andrew Multilingual；也可在右侧选择推荐中文女声「晓晓」或搜索任意发音人。
3. **调节参数**：原工作流的语速、音量、音调默认均为 `0`；如已改动，可点击「恢复原工作流默认」。
4. **试听**：点击「▶ 试听」，应用会合成前 400 字并立即播放。
5. **导出**：点击「⬇ 导出音频」，选择保存位置，应用将全文合成为 MP3。
6. **网络状态与语言**：顶部指示灯显示网络连通性；点击「检测网络」复查，右上角 `EN / 中文` 可切换界面语言。

### 卡住 / 网络异常怎么办？

- 生成过程中若超过 15 秒没有收到新音频数据，会弹出提示框：
  - **继续等待**：网络可能只是短暂波动；
  - **重试**：重新发起本次生成（推荐，最多自动重试 3 次）；
  - **取消**：终止当前任务。
- 网络指示灯变红时，请检查：
  - 系统是否联网；
  - 是否开启了代理（应用会读取系统代理环境变量）；
  - 代理是否可用、证书是否正确。

## 🗂️ 项目结构

```text
ms-edge-tts-gui/
├── app.py              # GUI 入口（CustomTkinter 界面）
├── tts_engine.py       # TTS 引擎：网络探测 / 卡住检测 / 重试
├── text_utils.py       # 文本清洗与试听截取
├── requirements.txt    # 运行依赖
├── requirements-dev.txt# 构建依赖（PyInstaller）
├── run.bat             # Windows 一键启动
├── build_release.bat   # Windows 本地打包脚本
└── .github/workflows/  # 自动构建 Release 的 GitHub Actions
```

## 🔨 构建发布版

### 是否内置 Python？安装就能用吗？

**是的。** 项目使用 [PyInstaller](https://pyinstaller.org) 把 Python 运行时、`edge-tts`、界面库一起打包进 EXE，
安装程序自带全部运行环境，**安装到任何电脑（Windows 10+）即可直接使用，无需单独安装 Python**。

```batch
:: Windows 本地一键构建：生成绿色版目录 + 安装程序
build_release.bat
```

产物说明：

- `dist\\EdgeTTSGui\\EdgeTTSGui.exe` —— 绿色（目录）版；
- `dist\\EdgeTTSGui-Setup.exe` —— 定制安装程序（Inno Setup，含定制欢迎页 / Star 引导）；
- `dist\\EdgeTTSGui-Portable.exe` —— 便携单文件版。

手动构建：

```batch
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean --onedir --windowed --name EdgeTTSGui --icon assets\\app.ico app.py
"C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" installer\\EdgeTTSGui.iss
```

GitHub Actions 会在推送 `v*` 标签时自动构建并发布以上三种产物（见 [.github/workflows/build-release.yml](.github/workflows/build-release.yml)）。

```bash
git tag v1.0.0
git push origin v1.0.0
```

发布说明见 [RELEASE_NOTES.md](RELEASE_NOTES.md)。

## ❓ 常见问题

| 问题 | 说明 |
| --- | --- |
| 生成很慢 / 卡住 | 通常是网络问题，可点「检测网络」确认；出现卡住弹窗时选择「重试」。 |
| 提示网络不可达 | 检查系统代理设置；如有代理请确认代理地址、端口、证书正确。 |
| 试听没有声音 | 确认系统音量；若运行环境无音频设备，试听可能不可用，请改用「导出音频」。 |
| 语音列表为空 | 语音列表需联网拉取；离线时仍可使用内置的常用语音。 |
| 打包体积较大 | 属于正常现象（PyInstaller 单文件包含 Python 运行时）。 |

## 📄 开源许可

本项目采用 [MIT License](LICENSE)，完全开源，欢迎使用、修改与分发。

- **开发者**：WangYufan
- **仓库地址**：[https://github.com/JJosephph/ms-edge-tts-gui](https://github.com/JJosephph/ms-edge-tts-gui)
- **鸣谢**：[edge-tts](https://github.com/rany2/edge-tts) 开源库与微软 Edge 在线语音服务

> ⚠️ 声明：本项目与微软公司无关，语音服务由微软 Edge 提供，请合理、合规地使用。
