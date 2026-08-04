# Release Notes

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
