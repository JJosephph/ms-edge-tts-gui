# AGENTS.md

## 红线规则（Red-line rules）— 必须绝对遵守

1. **禁止擅自切换仓库可见性**：不得以任何理由（包括隐私、泄漏、误操作等）自行设置 GitHub 仓库 private / public / 可见性，或删除、转移、重命名仓库。此类操作属于账号级破坏性操作，**必须先获得用户明确确认**，得到确认后才能执行。
2. 禁止未经确认执行任何会**丢失数据/粉丝/star/发布物**的操作（如删除仓库、重置历史、force-push 覆盖他人提交等）。
3. 截图/录屏只允许截取**目标软件窗口内部内容**（用窗口渲染方式，如 PrintWindow），严禁把桌面、其他窗口、聊天记录等个人隐私带入截图。
4. README / 推文 / 宣传材料中的截图必须真实对应当前软件版本，并先自检确认无隐私内容再推送。

## 仓库工作流

- 版本流程：改代码 → bump app.py APP_VERSION 与 installer/EdgeTTSGui.iss → RELEASE_NOTES 更新 → 本地 build_release.bat → commit → push main → tag vX.Y.Z → push tag（CI 自动发布）。
- 用户要求按指定版本号进行，不要擅自改动 GitHub 上的版本与 release。
