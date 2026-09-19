# Release Notes

## v1.5

### New

- **Row-oriented result browser**: “全部字幕” now uses a synchronized table where each audio item keeps its number, editable text, sentence timeline, playback controls, and regeneration action on the same row.
- **Seekable playback timeline**: every result row shows elapsed time and total duration with a draggable green slider; dragging seeks within the MP3 and playback keeps the row highlighted.
- **Line-end silence**: Line mode can append real silence after each generated line. The audio continues through the silent tail, and the timeline/slider duration includes and labels that padding.
- **Batch review and export**: edit individual rows, regenerate them, regenerate the complete batch, and export the updated collection as the final ZIP from the result browser.

### Improved

- Improved Chinese typography, checkbox spacing, hover feedback, and high-contrast result actions for smoother interactive review.
- Current/all preview switching now keeps row content and playback context aligned instead of separating text and subtitles into unrelated panes.

## v1.4.1

### Fixed

- 修复句间停顿实际上叠加 Edge TTS 原生间隔，导致设置 1ms、50ms、200ms 听起来几乎固定的问题；现在会覆盖原生句间空隙，按毫秒精确生成最终停顿。
- 修复 Edge TTS 句子边界轻微重叠时，音频和字幕时间轴可能错位的问题。

### New

- 支持 `[pause:500ms]`、`[pause:1.5s]`、`[pause:weak]`、`[pause:medium]`、`[pause:strong]` 和 `[pause]` 文本停顿指令。
- 主界面新增“句末停顿”批量插入功能，可选择常用毫秒值或输入自定义值。

## v1.4.0

### New

- **Three narration modes**: Normal mode turns the composer text into one audio file; Page mode imports documents and creates one audio file per `[分页]`-separated page; Line mode imports a file or prepared text and creates one audio file for every non-empty line.
- **Independent sentence pause**: configure silence between sentences in milliseconds without changing the speaking rate. The setting is applied to normal, page, and line generation.
- **SRT subtitles**: optionally export sentence-level SRT subtitles whose timings include the configured sentence pauses. Normal saves and batch ZIP bundles include the SRT when enabled.
- **Example TXT files**: Page and Line modes provide downloadable example files showing the exact input format.
- **Batch metadata and ZIP bundles**: page and line exports include numbered MP3 files plus `pages.json` or `lines.json`; timeline JSON and SRT files can be included together.

### Fixed

- Fixed batch export keeping only the last line/page when source indexes were duplicated. Batch results now use their unique in-batch position as the storage key while preserving source indexes in metadata.
- Fixed packaged builds failing sentence-pause processing because `miniaudio`'s `_cffi_backend` dependency was not included. Local and GitHub Actions builds now bundle `miniaudio`, `lameenc`, `cffi`, and `_cffi_backend` explicitly.
- Missing audio post-processing components now report a clear error instead of repeatedly retrying an already-generated audio file.

### Improved

- Normal mode no longer depends on pagination. Pagination and line splitting are opt-in workflow modes selected from the UI.
- Page mode recognizes an explicit standalone `[分页]` marker (and its English form) without speaking the marker; blank-line blocks remain supported when no marker is present.
- The local release script now stops immediately when either PyInstaller build fails, preventing a stale locked executable from being mistaken for a fresh artifact.
- Issue #2 is completed by the sentence-pause and SRT subtitle workflow in this release.

## v1.3.0

### Fixed

- Timeline JSON now uses the `SentenceBoundary` metadata returned by Microsoft TTS in the same synthesis stream as the MP3. Sentence start and end times are no longer estimated by grouping word boundaries, so playback highlighting stays aligned after seeking and no longer accumulates timing drift in long articles.
- Timeline generation now fails clearly and retries when sentence metadata is missing or invalid instead of saving an apparently valid but inaccurate JSON file.

### Improved

- Timeline JSON includes `"boundary": "SentenceBoundary"` while retaining the existing `sentences` array and compatibility fields.

## v1.2.0

### New

- **Import & page-by-page dubbing (work-assistant mode)** — resolves issue #1: import `txt / md / docx / pdf` and the app auto-splits the document into pages. Each page carries its own **Note** (never spoken, exported with the metadata). **Dub All Pages** synthesizes every page in order with page-level progress (page X/N) and retry/stall protection; afterwards each page can be previewed without re-rendering, and **Save Audio** bundles every page MP3 plus `pages.json` (page text, notes, per-page sentence timeline) into one ZIP.

## v1.1.2

### Fixed

- Voice-picker reliability: when the one-time voice list fetch failed or stalled (e.g. network hiccup), the Language / Gender dropdowns could stay empty with no way to recover. The app now retries the fetch up to 3 times, keeps the dropdowns populated with the default English-male **Andrew** selection as a visible fallback, shows a clear error inside the voice panel, and adds a **↻ reload** button to re-fetch the list anytime without restarting.

## v1.1.1

### New

- **ZIP bundle on save**: when the timeline option is on, Save now produces a single ZIP containing the MP3 and .timeline.json (each sentence's start/end seconds) — no more loose files. With the option off, saving stays a plain MP3 as before.

### Improved

- Play / Save buttons are now always visible and enabled; clicking them before generating shows a friendly "generate first" prompt, so they can no longer be mistaken for missing.
- The voice deck is now scrollable and the default window is taller (1000x800, min 880x700), so the Generate / Play / Save buttons never get clipped on small or high-DPI screens.
- README now promotes the timeline JSON + live sentence highlight as a key feature, with a JSON example in both Chinese and English.

### Fixed

- v1.1.0 regression: the bottom action buttons (Play / Save) could be cut off when the window was too short or DPI scaling was high — resolved with the scrollable deck and larger default window.

## v1.1.0

### New

- **Multi-level voice picker**: voices are fetched from the server once and grouped locally into Language → Gender → Voice (a dedicated grouping engine). Language and gender filter drop-downs replace the long single voice list; the default stays **Andrew (en-US, male)**, and any voice is one short step away.
- **Timeline JSON + playback highlight**: the timeline option is now a first-class toggle on the main UI (not hidden in Settings) with a " ? " help button showing a sample `.timeline.json` and a live highlight demo. When enabled, saving/downloading an MP3 also writes a `.timeline.json` (sentence start/end seconds), and during Play the sentence being read is highlighted in the article in real time.
- **Restore defaults button**: renamed to "恢复初始设置 / Restore defaults" and restyled to match the rest of the UI; it resets the voice to Andrew and rate/volume/pitch to +0%/+0%/+0Hz.
- Fixed the Markdown/plain-text helper text that overflowed the composer panel; it now wraps cleanly.


## v1.0.9

### New

- New toggle in Settings (设置): **"Save a .timeline.json beside the MP3"**. When enabled, saving/downloading an MP3 also writes a sentence-timeline JSON with the same base name (e.g. `my-audio.timeline.json`), listing each sentence's start/end seconds from Edge TTS metadata — no extra render is needed.


## v1.0.8

### Improved

- Lengthened the stall detection: the app now waits a full **3 minutes** (up from 20 seconds) of silence before it asks if generation is stuck, and won't keep re-prompting while you keep waiting. The network receive timeout was raised to match, so a brief network pause is no longer misreported as a stall or error.

### Fixed

- Fixed the **WinError 32 "another program is using this file"** popup loop after generating audio: the file was still locked by the playback session. The player now unloads the audio file when stopping, and the engine retries writing the output file (up to ~1.8s) if the target is temporarily locked, so preview/download no longer fail with a locked-file error.


## v1.0.7

### Fixed

- Fixed the stalled-generation **“Keep waiting”** option: it no longer breaks the audio stream or repeatedly re-opens the stall dialog (the infinite-loop feel). The async iterator is no longer cancelled on timeout; after choosing to keep waiting, the app waits quietly with a longer grace period instead of popping the dialog again.

## v1.0.6

### New and improved

- The installer's **"Open GitHub and Star the open-source project / 打开 GitHub 为开源项目点 Star"** option is now **checked by default**.
- Fixed the installer failing to open the GitHub page: the URL entry now uses `shellexec runasoriginaluser`, so it opens in the default browser as the normal user.

## v1.0.5

### New and improved

- Added a Chinese version of the MIT License (`LICENSE.zh.txt`); the installer now shows the Chinese license when 中文 is selected, and the copyright is unified to **WangYufan**.
- Refreshed the README interface screenshots with real captures of the new Generate → Play / Save UI.

## v1.0.4

### New and improved

- Reworked the workflow to **Generate Audio → ▶ Play / Save Audio**: the full audio is synthesized once, then previewing or saving reuses it without re-rendering.
- Fixed the progress bar bug: it no longer resets to 0% when generation finishes — it now stays at 100%.
- Generated audio is automatically invalidated when text, voice, rate, volume, or pitch changes, so Play/Save always match the current settings.
- Fixed the Inno Setup installer encoding (UTF-8 with BOM) so the Chinese app name renders correctly; the wizard now shows **免费开源 / Free & Open Source (MIT License)** and **developer WangYufan**, is bilingual (中文 / English), and keeps full uninstall support.
- Added a bilingual **“求点赞 · 请先读我 / Star Us · Please Read First”** section with the repository address to the README.
- Updated README and release notes for v1.0.4.

## v1.0.3

### Fixed

- Standardized the Windows UI font to Microsoft YaHei UI for clear Chinese labels, controls, and logs.
- Removed glyph-based button labels and replaced them with clear GitHub repository, GitHub Star, settings, theme, and language labels.
- Fixed English activity-log localization and repaired the corrupted bilingual README navigation links.

## v1.0.2

**Release date:** August 4, 2026

### Fixed and improved

- Reworked the Voice Deck so **rate, volume, and pitch** display together in a compact row at normal window sizes.
- Moved the shared **Preview / Export progress status and progress bar** above the action buttons so both are always visible during synthesis.
- Restored a visible upper-right **Free · Open Source / 免费 · 开源** badge alongside repository controls.
- Added a Chinese interface preview and a Chinese quick-start section to the bilingual README.
- Updated the public GitHub repository description to serve both Chinese and English users.

## v1.0.1

**Release date:** August 4, 2026

### New and improved

- Redesigned the desktop UI into a distinct **Composer + Voice Deck** workspace.
- Added **day** and **night** themes, persisted in local settings.
- Added **中文 / English** UI switching; English mode now localizes the Activity log and stalled-generation dialog.
- Added real, approximate `0–100%` generation progress for both **Preview** and **Export MP3**.
- Added Chinese labels for the currently loaded Edge voice catalog: voice name, locale, and gender.
- Added preview cache settings: choose a folder, open it, clear it, automatically overwrite one temporary preview MP3, and delete it when the app closes.
- Restored explicit compatibility defaults for the existing RPA workflow:
  - `en-US-AndrewMultilingualNeural`
  - rate `+0%`, volume `+0%`, pitch `+0Hz`
- Added a recommended Chinese female voice entry: `zh-CN-XiaoxiaoNeural`.
- Reworked README into a complete open-source project homepage with interface previews, downloads, privacy notes, build steps, and release guidance.

## v1.0.0

**Release date:** August 4, 2026

Initial public release.

### Included

- Modern Windows GUI for text-to-MP3 synthesis
- Preview playback and full MP3 export
- Network checks, proxy awareness, stalled-generation recovery, and retries
- Custom Inno Setup installer plus portable EXE packaging
- MIT license and GitHub Actions release automation
