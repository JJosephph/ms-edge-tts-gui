# Release Notes

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
