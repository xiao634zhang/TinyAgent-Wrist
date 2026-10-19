# 定位与已有项目

核对日期：2026-10-19。以下只比较阅读到的项目定位；未列出不代表对方不支持，功能可能更新。这不是速度或可靠性基准测试。

| 项目 | 官方介绍的重点 | 本项目的定位差异 |
|---|---|---|
| [scrcpy](https://github.com/Genymobile/scrcpy) | Android画面镜像与鼠标键盘控制 | 本项目复用ADB/scrcpy作调试，重点是Codex正文最终到达手环的链路 |
| [adbutils](https://github.com/openatx/adbutils) | Python封装ADB操作 | 本项目提供较小的subprocess封装，无意取代通用Android自动化库 |
| [ntfy-hooks](https://github.com/zbiljic/ntfy-hooks) | POSIX shell形式的编码代理ntfy提醒 | 本项目以Windows/Python和手环配套App排障为主要实测环境 |
| [codex-ntfy-notifications](https://github.com/shcherbatkin-pavel/codex-ntfy-notifications) | Codex完成、询问和权限手机提醒 | 核心通知能力有重叠；这里补充USB诊断、手环转发和训练告警教程 |
| [codex-ntfy-notifier](https://github.com/ravhello/codex-ntfy-notifier) | 多环境、idle-aware通知、持久重试和兜底 | 不声称兜底通知独有；本项目侧重vivo/Keep的分段证据及轻量训练接口 |

## 工程特色

1. **把验证终点推进到手腕。** 服务器接收、手机列表、系统通知、配套App、手环分别记录，避免用ntfy的常驻通知冒充实际提醒。
2. **Windows两端的内容体验。** 最终回复和问题选项通过统一格式化、内容去重和显式兜底发送；默认压低自动审批与预测建议噪声。
3. **可复制的故障知识。** 将主题前台抑制、主题优先级继承、vivo对ntfy的后台限制等案例写成可验证的分段排障树。
4. **代理工作和训练事件共用传输。** 看板适配器独立运行，不需要为每次检查唤醒大模型或Codex自动任务；提供合成看板复现。

这些是集成与易用性上的特色，不构成新网络协议、新蓝牙协议或算法首创。ADB、ntfy及Android系统承担基础能力，Keep完成其专有手环协议转发。本项目不含Keep逆向代码。单一真机组合实测成功不等于所有Android/手环均兼容。
