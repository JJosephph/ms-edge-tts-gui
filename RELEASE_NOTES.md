# Release Notes

## Unreleased

### Changed

- 项目默认分支和后续版本切换为 `GPL-3.0-or-later`。`v1.7.0` 及更早版本仍按其原有的 MIT License 授权，已有授权不会被追溯撤销。
- 新增 `NOTICE`、`TRADEMARKS.md` 和 `RELEASE_VERIFICATION.md`，分别说明项目版权、名称与品牌使用边界、发布哈希与构建来源验证方式。
- 安装器改为展示权威英文 GPL 原文；`LICENSE.zh.txt` 仅作为中文参考说明，不再作为正式许可证文本。
- 发布工作流新增 `SHA256SUMS.txt` 和 GitHub build provenance attestation，正式 Release 会同时附带许可证、NOTICE 和验证说明。

### Notes

- 如果你分发本项目的新版本或修改版，请保留 `LICENSE`、`NOTICE` 和原版权声明，并按 GPL 提供对应源代码。
- GPL 允许修改、再分发、商业使用和接受捐赠，但衍生版本不能改为闭源或添加与 GPL 冲突的额外限制。

## v1.7.0

### New

- 普通模式新增内嵌「批量上传」：可拖入或选择多个 `txt / md / docx / pdf`，原输入框切换为文件列表；不点击批量上传时，原有粘贴文本流程保持不变。
- 文件列表显示序号、文件名、音色、字数和生成进度。点击任意一行后，右侧音色、句间停顿、标点、SRT、时间轴、语速、音量、音调只配置该文件。
- 列表支持左侧复选框、表头全选、`Ctrl+A`、`Shift/Ctrl` 多选移除；批量生成只处理未完成项，已完成文件会保留，不会重复合成。
- 支持打包下载全部完成项；右键已完成 `100%` 的文件可单独下载 ZIP，右键未完成项可重试所选任务。单个 ZIP 包含音频、SRT、时间轴 JSON 和 `metadata.json`。
- 支持文本规则标记。紧凑写法如 `{Abeo|200ms{,.~}|srt}`，完整写法如 `{tts:Ana|pause=200ms|marks=,.!?|srt=1|json=1|rate=+0%|volume=+0%|pitch=+0Hz}`；规则可写在单独第一行，也可与正文同一行，导入时自动应用并从朗读文本中过滤。
- 「规则配置」弹窗提供音色字典和规则模拟器：按「语言 → 性别 → 音色」三级选择，字典包含中文名、语言、性别、音色代码等表头，并支持按语言、性别和关键词筛选，可直接复制生成后的规则编码。

### Changed

- 普通模式批量文件明确不包含“行末停顿”：普通模式没有“行”的概念，`line` / `fill` 不再作为普通批量规则，也不会把逐行模式的行末停顿带入批量任务。
- 打包构建补充 `tkinterdnd2`，使目录版、便携版和安装版具备批量拖入文件能力；拖拽不可用时仍可点击选择多个文件。

### Fixed

- 修复多个文件上传后规则串用、不同文本最终都使用同一个音色或配置的问题；每个文件的规则现在独立解析并保存。
- 修复普通批量误继承逐行模式 `50ms` 行末停顿的问题，避免本不需要行末静音的批量任务在合成后处理阶段失败。
- 修复中文或 Unicode 输出文件名触发 `('failed to decode file', -7)` 的问题；音频停顿处理改为从字节解码，不再依赖 Windows C 文件路径接口。

### Tests

- 增加批量规则解析、紧凑规则、同一行规则、音色别名、文件名清理、已完成项跳过和 Unicode 输出路径回归测试。
- 完整测试共 69 项，全部通过；使用真实文件验证 `1.txt -> en-US-AnaNeural`、`1 - 副本.txt -> ja-JP-NanamiNeural`，并验证中文输出文件名生成成功。

## v1.6.3

### Fixed

- 修复含小数点的文本在逐行模式、行末延迟和精确停顿中偶发生成失败的问题：`49.9`、`27.01`、`v1.6.2` 等数字中的小数点不再被误判为句末标点，避免 WordBoundary 与朗读文本发生错误分段后停止后处理。
- 本版同时包含 v1.6.2 代码中的 429 限流识别与退避重试、无空格长中文切分、分段合成边界偏移补偿修复。由于 v1.6.2 未单独生成发布 tag，这些修复由 v1.6.3 一并交付。

### Tests

- 增加数字小数点和版本号断句、WordBoundary 时间轴映射回归测试；完整测试共 57 项，全部通过。
- 使用客户真实 `海豆.txt` 的前两行调用微软语音服务验证，两行时间轴均成功映射；完整生成第 1 行返回 `done`。

## v1.6.2

### Fixed

- 修复命中微软 429 限流时误报「可能是网络不通或代理设置不正确」的问题。现在会明确说明这是服务端对当前出口 IP 的临时限流，与本地网络和代理无关，不再把服务端限流甩锅给用户网络。
- 修复超长中文文本（没有空格也没有换行）不会被切分的问题：此前整段文字会被塞进一次请求（实测 24KB 中文只发一条请求），现已由客户端主动切成有界片段，避免单次请求体积失控。
- 修复分段合成时边界时间轴偏移的问题：多段音频的 WordBoundary / SentenceBoundary 会按已生成音频的精确时长累加补偿，保证逐行模式的行末延迟仍然落在正确位置。

### Changed

- 429 限流改为更长的指数退避（首次约 8 秒，上限约 30 秒）并加入随机抖动，减少连续重试继续被限流的概率。
- 429 限流与服务端 5xx 临时故障改为静默自动重试，不再中途弹窗打断批量任务；重试次数用尽后才给出结论。
- 重试次数用尽时的提示按原因区分：限流提示等待 1-2 分钟或拆分批量，服务端错误提示稍后重试，只有真正的网络故障才提示检查网络与代理。
- 批量配音中若有条目命中限流，失败项重试前的冷却时间由 8 秒延长到 20 秒。

### Tests

- 新增 429 / 5xx / 403 / 网络故障的错误分类回归测试，确保限流不再被归类为网络问题。
- 新增退避策略测试（限流等待更长、有上限、带抖动）与最终失败文案测试。
- 新增文本切分测试（不丢字符、单片段不超过上限、无标点长文本仍能切分）与跨片段边界偏移补偿测试。

## v1.6.1

### New

- 导出 SRT 字幕时新增「填充行末停顿（字幕无空隙）」选项：勾选后上一行字幕会一直持续到下一行开始，末行字幕覆盖行末延迟，导入剪辑软件时时间轴不再有空缺。
- 该选项只在逐行模式开启行末停顿后出现，默认关闭；不勾选时导出结果与之前完全一致。

### Changed

- 字幕填充只改写 SRT 文本，音频与时间轴 JSON 仍保留真实停顿时间，方便对照校对。
- 结果预览窗口里显示的字幕会跟随该选项同步切换。

### Tests

- 增加字幕填充消除行末空隙、原始时间轴不被改写、以及没有音频时长时不虚构末句结束时间的回归测试。

## v1.6.0

### New

- 逐行模式支持“精确行末停顿”：直接生成全文时，用微软词级边界定位每行真实语音末点，按采样点写入你设定的静音；按行导出时控制每个独立音频的尾部静音。
- 停顿范围明确为 `0` 或 `50–10000 ms`，界面、批量插入对话框和 README 都标注了可用范围与 MP3 帧取整说明。
- 音色、语速、音量、音调与界面语言现在会保存，下次启动自动恢复。

### Fixed

- 修复逐行模式下“行末停顿”只追加到文件尾部、无法改变行与行之间原生停顿的问题；现在使用词级边界定位真实语音末点，并替换行间与尾部静音。
- 修复不同声音原生尾静音长短导致同一停顿设置听感差异明显的问题；`Guy`、`Brian` 及中文语音在相同设置下得到一致的逻辑间隔。
- 修复从普通模式切到逐行模式时输入框被清空、看起来像文字丢失的问题；首次切换会把普通模式草稿带入逐行工作区。
- 修复音色、语速、音量、音调与界面语言不会保存、每次启动都回到默认值的问题。

### Changed

- 句间/行末停顿明确支持 `0` 或 `50–10000 ms`；`1–49 ms` 不再开放，避免展示 MP3 编码帧无法稳定兑现的精度。
- 精确停顿时改用 `WordBoundary` 时间轴；无法可靠映射到朗读文本时停止后处理并提示，不再猜测位置。
- 生成、试听、保存等主操作固定在设置栏底部，短窗口或高 DPI 下无需滚动即可触达。
- 窗口尺寸按屏幕自适应，最小尺寸下调，避免在 1366×768 等小屏上超出显示区域。

### Tests

- 增加词级边界映射、行尾索引、0 ms 删除原生间隔、最小可支持停顿和边界映射失败的安全回归测试。

## v1.5.4

### New

- 试听按钮现在会明确显示播放状态：播放中变为红色「■ 停止播放」，音频结束后自动恢复，结果预览里的每行按钮也会同步显示「停止」。
- README 补充普通、逐页、逐行三种工作模式，字幕与「查看结果」预览说明，并新增“请作者喝咖啡”的微信收款码。

### Fixed

- 批量逐页 / 逐行配音增加请求间隔；失败项会在短暂冷却后自动重试一轮，减少微软新端点短时限流导致的连续失败。
- 生成卡住或连接中断时先静默自动重试最多 2 次，仍失败后才弹窗询问，避免批量任务频繁打断。
- 修复缓存预览目录被清理后，生成时找不到临时输出目录而失败的问题。

### Tests

- 增加静默流自动重试、瞬时失败自动重试和输出目录自动重建的回归测试。

## v1.5.3

### New

- 启动时自动检查 GitHub 最新正式版；发现新版本后弹出更新内容、发布页和安装包下载入口。
- 顶部新增“检查更新”按钮，可随时手动检查，并明确显示“已是最新”或检查失败原因。

### Fixed

- 适配 Microsoft Edge 155 的新语音合成端点，修复 2026 年 10 月起旧端点返回 403 后无法生成音频的问题。
- 网络检测现在会对真实合成 WebSocket 做一次握手，不再出现“检测通过但生成立即失败”的状态不一致。
- HTTP 403 不再被当作普通网络卡顿或继续等待，而是直接提示微软服务端拒绝连接，避免无效重试。
- 自动重试增加 2 秒起的短暂退避，给网络和服务端恢复留出时间。

### Tests

- 增加新端点切换、403 不弹卡住对话框和 GitHub Release 版本比较测试。

## v1.5.2

### Fixed

- 修复点击“继续等待”后几乎立刻再次弹出卡住提示的问题；等待计时现在从用户点击的时刻重新开始。
- “继续等待”增加“不再提醒（本次任务）”选项；勾选后本次任务不再弹窗，后台继续等待，连接中断时自动重试。
- 将再次提醒间隔延长到 10 分钟，并放宽底层接收超时，为慢速网络留出更多恢复时间。

### Tests

- 增加卡住等待计时和“不再提醒”回归测试，覆盖旧结果立即再次触发提示的场景。

## v1.5.1

### Fixed

- 修复查看结果页只显示整秒，导致 1ms、50ms 等短停顿看起来没有变化的问题。
- 结果页进度条现在按毫秒显示和拖动，并使用最终 MP3 解码后的实际播放时长。
- 时间轴同时保留逻辑停顿时长和实际音频时长，字幕时间不会被 MP3 编码帧长覆盖。

### Tests

- 增加小于 100ms 行末停顿的回归测试，验证逻辑时间轴和实际音频时长都被记录。

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
