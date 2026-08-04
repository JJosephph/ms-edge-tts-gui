# Edge TTS Voice Studio

<p align="center">
  <strong>Turn text into clear, natural voice.</strong><br>
  A polished, open-source desktop client for Microsoft Edge Text-to-Speech.
</p>

<p align="center">
  <a href="https://github.com/JJosephph/ms-edge-tts-gui/releases"><img src="https://img.shields.io/github/v/release/JJosephph/ms-edge-tts-gui?display_name=tag&sort=semver&color=5A8CFF" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-61D69C.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-356FEB.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Platform-Windows-5A8CFF.svg" alt="Windows">
  <a href="https://github.com/JJosephph/ms-edge-tts-gui/stargazers"><img src="https://img.shields.io/github/stars/JJosephph/ms-edge-tts-gui?style=flat&color=F6C66C" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#downloads">Downloads</a> ·
  <a href="#network-and-proxy">Network & proxy</a> ·
  <a href="#build-and-release">Build</a>
</p>

---

## Overview

**Edge TTS Voice Studio** is a modern Windows desktop application for turning articles, notes, scripts, documentation, and other text into high-quality MP3 audio. It is powered by the open-source [`edge-tts`](https://github.com/rany2/edge-tts) library and Microsoft Edge online voices—**no API key is required**.

The project is designed as a general-purpose open-source tool. It includes practical safeguards for real-world network conditions, including service reachability checks, proxy-aware diagnostics, retry controls, and a stalled-generation prompt.

## Interface Preview

<p align="center">
  <img src="assets/ui-preview-dark.svg" alt="Dark theme preview" width="900">
</p>

<p align="center">
  <sub>Night theme · Composer + Voice Deck workflow</sub>
</p>

<p align="center">
  <img src="assets/ui-preview-light.svg" alt="Light theme preview" width="900">
</p>

<p align="center">
  <sub>Day theme · Same focused layout, optimized for bright environments</sub>
</p>

## Features

| Area | What it provides |
| --- | --- |
| **Text to MP3** | Paste Markdown, plain text, or HTML-derived text and export a full MP3 file. |
| **Instant preview** | Quickly synthesize and play the first 400 characters before exporting the complete audio. |
| **Real progress** | Preview and export both show live, approximate `0–100%` synthesis progress plus received audio size. |
| **Voice catalog** | Loads hundreds of Edge voices; Chinese mode renders locale and gender labels in Chinese, while English mode preserves Microsoft’s original naming. |
| **Original workflow compatibility** | Default settings mirror the existing RPA workflow: `en-US-AndrewMultilingualNeural`, rate `+0%`, volume `+0%`, pitch `+0Hz`. |
| **Recommended female voice** | `zh-CN-XiaoxiaoNeural` is prominently listed as a recommended Chinese female voice. |
| **Network protection** | Checks Edge TTS service availability and detects proxy environment variables before generation. |
| **Stall recovery** | If audio stops arriving, offers **Keep waiting**, **Retry**, or **Cancel** with a network/proxy explanation. |
| **Bilingual interface** | Toggle the desktop UI between **中文** and **English** at any time. English articles and international voices are fully supported. |
| **Day / night themes** | Switch between a bright reading-friendly theme and a focused dark workspace. |
| **Preview cache control** | Choose a preview cache folder, open it, or clear it immediately. Only one temporary preview MP3 is reused and it is deleted when the app closes. |

## Downloads

Open the [Releases](https://github.com/JJosephph/ms-edge-tts-gui/releases) page and choose the package that fits your use case:

| Package | Best for | Notes |
| --- | --- | --- |
| `EdgeTTSGui-Setup.exe` | Most Windows users | Modern installer, choose any drive/folder, desktop shortcut option, uninstaller, and a GitHub Star prompt after installation. |
| `EdgeTTSGui-Portable.exe` | Portable use | Single-file executable; double-click to run. |
| `EdgeTTSGui/EdgeTTSGui.exe` | Advanced users | Directory build for manual deployment. |

### Is Python included?

**Yes.** Published EXE packages bundle the Python runtime and required libraries through PyInstaller. On Windows 10 or later, users can install or run the program without installing Python separately.

## Quick Start

### Option A — Install the Windows release

1. Download `EdgeTTSGui-Setup.exe` from [Releases](https://github.com/JJosephph/ms-edge-tts-gui/releases).
2. Run the installer and choose any destination drive or folder.
3. Launch **Edge TTS Voice Studio** from the Start menu or desktop shortcut.
4. Paste text, preview it, and export the final MP3.

### Option B — Run from source

```bash
git clone https://github.com/JJosephph/ms-edge-tts-gui.git
cd ms-edge-tts-gui

py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

On Windows, you can also double-click `run.bat` for first-run setup and launch.

## Using the App

1. **Paste your text** into the Composer panel.
2. **Choose a voice** from the Voice Deck. The default already matches the existing RPA configuration; use **Restore workflow defaults** at any time.
3. **Adjust rate, volume, and pitch** if needed.
4. Click **Preview** to generate a short audio sample.
5. Click **Export MP3** to select a save location and synthesize the complete text.
6. Watch the status line and progress bar during generation.

## Network and Proxy

Edge TTS is an online service. The application performs a reachability test against the Edge speech endpoint and reads common proxy variables:

```text
HTTPS_PROXY   HTTP_PROXY   ALL_PROXY
https_proxy   http_proxy   all_proxy
```

If the service cannot be reached, the app reports the condition in the Activity log. If a generation stalls (no new audio data for 15 seconds), it presents a recovery dialog:

- **Keep waiting** — for a short-lived slow connection;
- **Retry** — starts the current synthesis again (up to three attempts);
- **Cancel** — stops the task and removes the partial file.

## Preview Cache and Disk Usage

Preview audio is deliberately designed not to accumulate:

- The default location is the operating system temporary folder.
- Only one file, `edge_tts_preview.mp3`, is reused for previews.
- It is overwritten on every new preview.
- It is removed automatically when the application exits.
- Use **⚙ Settings** to set another cache folder, open it, or clear the preview file immediately.

Exported MP3 files are written only to the location the user explicitly selects.

## Defaults and Voice Recommendations

The compatibility preset is intentionally explicit:

```text
Voice:   en-US-AndrewMultilingualNeural
Rate:    +0%
Volume:  +0%
Pitch:   +0Hz
```

This lets existing users of the related RPA workflow start synthesizing immediately without re-entering settings. For a Chinese female voice, select the recommended `zh-CN-XiaoxiaoNeural` entry.

## Project Structure

```text
ms-edge-tts-gui/
├── app.py                       # Desktop UI, themes, localization, cache settings
├── tts_engine.py                # Edge TTS streaming, progress, network and stall handling
├── text_utils.py                # Markdown/HTML cleanup and preview text extraction
├── assets/                      # Icon and README interface previews
├── installer/EdgeTTSGui.iss     # Inno Setup installer definition
├── run.bat                      # Windows source launcher
├── build_release.bat            # Builds directory app, portable EXE, and installer
└── .github/workflows/           # Tagged-release automation
```

## Build and Release

### Local Windows build

```bat
build_release.bat
```

The script builds:

```text
dist\EdgeTTSGui\EdgeTTSGui.exe
dist\EdgeTTSGui-Portable.exe
dist\EdgeTTSGui-Setup.exe
```

The installer is generated with Inno Setup and includes the bundled application runtime.

### GitHub release automation

Pushing a version tag matching `v*` runs `.github/workflows/build-release.yml`. The workflow builds the Windows directory app, the portable EXE, and the Inno Setup installer, then uploads them to a GitHub Release.

```bash
git tag v1.0.1
git push origin v1.0.1
```

## Privacy and Service Notice

- Text is sent to Microsoft Edge’s online speech service only to synthesize the requested audio.
- This application does not require an API key and does not add its own telemetry service.
- The project is not affiliated with or endorsed by Microsoft.
- Please use online voices in accordance with the applicable service terms and local laws.

## Contributing

Issues, feature requests, and pull requests are welcome. If this project helps you, please consider giving it a **Star** on GitHub—it makes the project easier for other users to discover.

## License

Released under the [MIT License](LICENSE).

- **Maintainer:** WangYufan
- **Repository:** https://github.com/JJosephph/ms-edge-tts-gui