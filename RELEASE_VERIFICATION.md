# Release Verification / 发布校验

每个正式 Release 都会生成 `SHA256SUMS.txt`。它用于确认下载到的文件
没有被替换或损坏，也方便用户区分官方构建和第三方重新打包。

## 下载后校验

Windows PowerShell：

```powershell
Get-FileHash .\EdgeTTSGui-Setup.exe -Algorithm SHA256
Get-FileHash .\EdgeTTSGui-Portable.exe -Algorithm SHA256
```

把结果与 Release 中的 `SHA256SUMS.txt` 对照。大小写不敏感，但哈希值
必须完全一致。

## GitHub 构建来源证明

GitHub Actions 发布会为构建产物生成 build provenance attestation。
这表示文件由本仓库的 GitHub Actions 工作流构建，并记录对应的提交和
工作流信息。它不等同于 Windows Authenticode 代码签名，但比单独发布
一个 EXE 更容易核验来源。

查看仓库的 attestations：
https://github.com/JJosephph/ms-edge-tts-gui/attestations

## 为什么还需要代码签名

Authenticode 代码签名需要单独购买 Windows 代码签名证书，并在 GitHub
Secrets 中配置证书和密码。没有证书时，本项目先提供哈希和 GitHub 构建
来源证明；以后取得证书后，可以在发布流程中增加签名步骤。
