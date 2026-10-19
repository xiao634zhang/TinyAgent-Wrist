# 从零复现

## 1. 分清两条路径

通知路径是电脑→ntfy服务器→Android系统通知→Keep→蓝牙手环。ADB路径是电脑→USB→手机，作用是诊断和控制。第一条打通后可拔USB。手机离电脑远没关系，但手机需要联网、和手环保持连接；电脑需要开机联网。

Python建议3.11及以上。先完成README中的克隆、venv和 `configure.py`。可以把仓库放在任意普通路径（例如 `D:\codex-wrist-notify`），路径不接受双引号、美元符、反引号或换行；安装后移动目录需重新生成配置和审查新命令。

`configure.py` 只写本项目的本地配置，默认不改Codex。重复运行保留现有主题。`--server https://your-ntfy.example` 可在首次生成时选服务器；改变已存在配置时直接在本地编辑配置。`notification_config.example.json` 只是模板，不包含可用个人主题。

## 2. 安装手机端并逐段验证

1. ntfy从[官方来源](https://docs.ntfy.sh/subscribe/phone/)安装，订阅本地配置中的服务器和主题。不要复制别人的随机主题。
2. 允许ntfy的Android通知权限，检查“高优先级”通知通道，开启实时推送（若该发行版提供选项）。主题最低优先级设置为默认或更高（3），测试消息使用4；主题静音和全局静音应关闭。
3. vivo上给**ntfy本身**选择“允许后台耗电”，允许后台数据/WLAN/移动网络；菜单随系统版本变化。不要假设Keep已配置就等于ntfy也配置了。
4. Keep中完成手环配对，授予通知读取权限，启用支持的应用提醒或“其他通知”。这些步骤需要手机用户自行授权。勿扰时间段和手环蓝牙连接也需要核对。
5. 手机回桌面、熄屏，再发送 `WRIST-TEST-1`。确认系统通知和手环，**再**打开ntfy。

测试记录至少包含：测试编号、手机是否熄屏、ntfy主题是否前台、服务器回执是否成功、系统通知有无、手环有无。不要把消息正文、截图和私人主题贴到公开Issue。提供脱敏结果表即可。

## 3. 安装Codex hooks与显式兜底

阅读并审查 `codex_notify_hook.py`、`notify_question.py`、`notify_completion.py` 和生成的规则。明确同意正文离开电脑后执行：

```powershell
.\.venv\Scripts\python.exe configure.py --install-hooks --install-rules
```

默认目标为当前 `CODEX_HOME` 或 `~/.codex`，也可传 `--codex-home`。新增Stop、PermissionRequest、PreToolUse配置；合并时保留其他条目，不覆写信任哈希。请在Codex里完成原生信任流程。原生事件定义以[官方Hooks文档](https://learn.chatgpt.com/docs/hooks)为准。

默认 `permission_notifications=false`、`include_commands=false`。原始PermissionRequest可能在自动审批时就触发，无法可靠当作“正在等人点击允许”，所以默认静音。若明确需要，可手动开启；项目不会自动允许或拒绝操作，hook只输出 `{}`。

默认 `only_user_thread_completions=true`：读取当前hook会话在本地 `state_5.sqlite` 的source/originator/thread_source分类，不读取其他聊天正文；未知分类宁可不发送。该文件名和字段属于版本相关实现，Codex更新后可能需要适配。日志出现 `not-a-user-thread-completion` 时先核对版本及当前CODEX_HOME，而非关闭系统安全保护。

显式兜底读取指定文件和当前会话环境变量，在提问/最终回复前由代理执行。需代理载入生成的AGENTS规则；它不保证所有未来版本都执行。原生与兜底按会话、标题、截断后内容进行60秒去重。这个窗口内相同文本即使属于不同轮次，也可能只发送一次；不是永久去重或端到端回执。

手动样本测试仅证明格式化/传输，不能证明真实hook触发。真实验证请在桌面端和VS Code各完成一次小任务、提出一次带选项的问题，再检查本地 `logs/hook-delivery.log` 的 `route` 和接收结果。`route=hook` 才是原生触发，`question-fallback`/`completion-fallback` 是显式兜底。

## 4. 查看日志与卸载

`logs/hook-delivery.log` 记录开始/失败、发送回执和抑制原因，包含会话ID等本地元数据，不应公开。`logs/controller.log`、截图、UI XML和训练检查日志也可能涉及隐私。参考 [SECURITY.md](../SECURITY.md)。

停用：从Codex的hooks界面停用本项目条目；编辑用户hooks.json仅移除指向本项目脚本的组，保留其他组；从用户AGENTS.md删除 `codex-wrist-notify:start/end` 标记内的规则。安装前备份位于本项目logs目录，恢复前核对备份后是否还有其他配置修改，避免覆盖它们。关闭独立监控见训练教程。可以保留手机App和手环原有功能。

## Android 控制

只在需要调试时安装[Google官方Platform-Tools](https://developer.android.com/tools/releases/platform-tools)。将解压后的 `platform-tools` 放在项目 `tools/` 下，或设置本PowerShell会话的 `ANDROID_ADB` 为adb可执行文件完整路径，或使用PATH上的adb。

手机用数据线连接、解锁；开启开发者选项及USB调试，核对并允许这台电脑。不能绕过 `unauthorized`。仅有模拟器时默认拒绝；多台真机用 `--serial` 明确选择。

```powershell
.\.venv\Scripts\python.exe test_connection.py
.\.venv\Scripts\python.exe test_connection.py --capture --show
.\.venv\Scripts\python.exe test_ui.py --launch io.heckel.ntfy --execute
# 看过刚获取的截图后，替换为当前设备上的安全坐标：
.\.venv\Scripts\python.exe test_ui.py --tap 100 200 --execute
```

`AndroidController` 提供connect、screenshot、tap、swipe、input_text、press_back、press_home、launch_app、get_ui_hierarchy。滑动duration单位毫秒；坐标由当前截图确定，不跨设备照搬。ASCII输入也可能被中文输入法改写，Unicode和百分号明确拒绝；中文需另行验证输入法或剪贴板方案。

截图通过ADB取得PNG，UI XML由uiautomator生成。动态页面可能dump失败；不能把旧XML当作本次界面。日志和手机文件只按需读取，不需要Root、刷机或解锁Bootloader。

可选[scrcpy官方发行版](https://github.com/Genymobile/scrcpy/releases)，解压后传入完整路径：

```powershell
.\start_scrcpy.ps1 -Scrcpy 'D:\tools\scrcpy\scrcpy.exe'
```

脚本关闭音频和剪贴板自动同步。scrcpy窗口启动不代表Codex看到了窗口，代理应读取实际截图/XML。第三方工具不包含在本仓库中。
