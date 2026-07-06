# CareAction HBuilderX 打包说明

本目录是 HBuilderX 可导入的 5+ App 静态项目。

当前电脑未检测到 HBuilderX、Java、Gradle 或 adb，所以无法在本机直接生成 APK。

在有 HBuilderX 的电脑上：
1. 打开 HBuilderX。
2. 导入 `CareAction_HBuilderX` 目录。
3. 打开 `manifest.json`，确认应用名称、包名和 Android 权限。
4. 选择“发行” -> “原生 App 云打包” -> Android APK。
5. 如需语音输入权限，保留 `RECORD_AUDIO` 权限。
