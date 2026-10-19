# 训练告警：独立后台程序

仅当已有训练看板提供下述JSON时可直接接入；不是所有训练网页都适用。不需要Codex定时任务、不操作GPU实例、不修改训练。

## 无服务器复现

配置生成后，示例target指向本机9876端口。终端一运行合成看板：

```powershell
.\.venv\Scripts\python.exe examples/demo_dashboard.py --mode healthy
```

终端二只检查，不发送、不写状态：

```powershell
.\.venv\Scripts\python.exe training_monitor.py
```

停止合成看板（Ctrl+C），用 `--mode gpu-error`、`--mode nan` 或 `--mode complete` 重启，重做只读检查，确认产生相应告警。输出明确标示模拟数据；不会读取真实训练。

验证后，若希望把模拟告警发到自己的手机：

```powershell
.\.venv\Scripts\python.exe training_monitor.py --notify
```

此命令会实际发送。无异常不发例行进度；首轮把既往已结束阶段作为基线，当前全局完成仍会提醒。换成真实目标前编辑被Git忽略的 `training_monitor_config.json`，不要提交研究项目名、地址或运行名。

## 常驻运行（Windows）

```powershell
.\start_training_watch.ps1
# 停止，只停止本监控，不停止训练：
.\.venv\Scripts\python.exe training_watch.py --stop
```

文件锁保证同一目录单实例。每30秒启动一次只读检查，网络超时可能延长间隔。状态看 `logs/training-watch-status.json`。关闭Codex窗口不影响这个独立进程；电脑需开机联网。未安装Windows计划任务/开机启动，重启后重新运行启动脚本。核心判定测试也在Linux运行，但常驻封装使用Windows msvcrt，Linux需要自行运行单次检查或另写进程封装。

## 接口契约

`GET /api/progress`：

```json
{
  "run_id": "example-run", "status": "TRAINING", "phase": "stage1",
  "completed_steps": 100, "total_steps": 1000,
  "local_now_unix": 1800000000,
  "watcher": {"status": "CONNECTED", "updated_unix": 1800000000},
  "stages": {"stage1": {"step": 100, "loss": 0.1, "status": "TRAINING"}}
}
```

`run_id`更换会重置本次进度基线。活跃阶段的 `GET /api/loss?stage=stage1&recent=100` 返回 `{"points":[{"step":100,"loss":0.1}]}`。各阶段结束使用 `completion` 对象及可选 `completion_reason`，不能只凭某阶段暂时没推进当作全局训练完成。全局完成状态集合见 `COMPLETE`；进入EVALUATING等状态会说明训练阶段结束但评估/归档可能没结束。

时间戳注意时钟偏差：watcher.updated_unix应使用看板本机时钟，local_now_unix也是看板本机时钟；远端训练机的updated_unix不直接参与过期判定。step停滞按观察者自身时间跟踪。15分钟是默认阈值，缓存/长验证/长step任务应调整，停滞仅提示检查。

## 检测范围与局限

- 完成/阶段完成；FAILED等明确失败。
- progress/error、watcher/error、stage/error字段中的GPU/CUDA/OOM等错误。
- 活跃阶段Loss/reconstruction非有限值；最近样本NaN/Inf。
- 最近3个有效Loss绝对值都超过此前样本绝对值中位数10倍（至少23个记录）；是检查线索，不自动判定发散。
- 所有阶段step连续15分钟未推进、采集重连或本地心跳过期5分钟、看板连续2次不可访问。

**没有实时GPU温度、利用率、显存硬件遥测。** 未上报错误不等于GPU正常。不可访问只表示无法确认，不能当作训练结束。当前轮询可能错过两次检查之间快速恢复的异常。

同一持续故障发一次，恢复后再发生可再发；完成事件每run发一次，失败的完成发送保留待重试。状态持久保存在logs；删除状态会重置去重。服务器收到不代表手机收到，仍需手机后台与手环连接。检查自身崩溃会记本地错误，不能承诺它一定能通过已经损坏的通道报警。
