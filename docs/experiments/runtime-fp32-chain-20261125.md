# runtime改名、FP32切换与全链路离线检查

## 实施结果

2026-11-25，按用户确认将GuideBot/host_bridge整体改为GuideBot/runtime。
更新main.py、业务适配、ROS节点、工具、测试和当前结构文档的导入及子进程模块路径。
没有旧host_bridge兼容转发。archive中的历史路径不改写为当前路径。
保留本机ROS/SDK环境隔离、本地Unix IPC、Enter授权、资源进程及故障释放。
这些职责仍为当前本机方案所需；本轮没有把资源进程重新实现为ROS节点。

正式动作时间戳BACKEND_OPTIONS改为quantized=False，即FP32；threads1、reuse_predictor=True、count_offset=-1及完整前缀策略不变。
纯语音可选时间戳的默认后端原本也是非量化，本轮不改变其其他默认参数。
StepFun、LocalVQE v1.2→AGC2、关闭gate、参考延迟0、SDK播放和原生运动规则未改变。

## 与旧环境的差异及证据

| 链路 | 检查与结论 |
| --- | --- |
| Python业务 | 当前3.8与旧3.10备份分别138项主测试通过，覆盖播放/打断/旧音频丢弃/参考/时间戳/动作适配/资源授权；两边运行当前代码，不代表保存了旧版本完整源码快照 |
| 音频前端 | 同一12秒输入、同一零参考，两环境最终PCM SHA256相同；此次并行ROS启动存在争用，耗时不作为空闲基准，不声称真实AEC效果相同 |
| ROS通信 | 当前原生离线验收八项checks与旧Docker历史验收相同，覆盖类型、规划、执行、上下文过期、取消、旧回复拒绝、心跳失联及退出 |
| 事件延迟 | 旧Docker历史基线P99 4.478ms，本次本机4.751ms，相差0.274ms；不是同日同负载统计显著性实验 |
| 时间戳 | 明确改变为FP32；前轮两独立进程6s final热运行中位数0.648s，旧FP32 0.657s，新INT8 3.415s。旧INT8还有调用历史依赖，不宣称FP32与旧INT8结果相同 |
| 实际模型到ROS | 新增--real-aligner验收，启动真实StreamingTimestamps后台进程、加载正式FP32配置、提交本地录音及控制文本、取得final锚点后经ROS调度模拟动作；旧版本锚点拒绝检查也通过 |
| 生命周期 | voice、simulation、激活失败、节点退出四组均通过 |
| 正式入口 | EOF取消待命，无WAV/语音事件、无资源激活，临时planner凭证删除，六节点使用正式GuideBot解释器，未留运行进程 |
| 依赖和驱动 | ROS/SDK分别正确导入，pip check通过，38项运动Python测试通过；未实际初始化机器人DDS |

业务通信和资源管理的离线契约没有发现实质退步，已完成专属Docker代码的归档核对。
时间戳是用户明确授权的差异，其准确性不能仅由新旧一致或速度证明；实际模型ROS测试使用控制标签，只验证链路。
没有调用真实云、麦克风、扬声器、机器人SDK或关节。
因此现场端到端语音质量、真实打断延迟与动作效果仍需用户Enter授权验收，不能用离线检查代替。

## 归档边界

Docker专用文件已全部保留在archive/docker-humble：
container.py、Dockerfile、runtime.Dockerfile、Compose、runtime_entrypoint.sh、Docker说明、verify_container.py、smoke_test.py及.dockerignore。
实际文件清单以archive/docker-humble目录为准。正式GuideBot、tools/ros2、main.py无Docker命令、容器路径或host_bridge导入。
Docker程序、镜像及GuideBot-py310-backup没有删除；不将备份环境当正式生产回退入口。

runtime当前职责为launcher、local_runtime、environment、worker/workers、transport和ipc。
启动仍为conda activate GuideBot后python main.py；真实动作加--gesture-backend unitree，先开运控、不另起运动服务，按Enter启动/结束。

## 证据索引

本轮汇总与测试日志：~/.local/state/guidebot/experiments/runtime-fp32-20261125/。
所有下列运行目录均在~/.local/state/guidebot/ros2：
- foxy-kfwnmko1/acceptance.json：当前原生离线ROS。
- foxy-6d5lsy18/aligned-acceptance.json：注入锚点。
- foxy-f7ekjt15/aligned-acceptance.json：真实FP32后台进程到ROS模拟执行。
- foxy-hdxrddyx、foxy-4gzkcgqg、foxy-j534swi_、foxy-tz3vk73c：四组生命周期。
- foxy-9u3hh4hn：正式入口待命EOF清理。
- run-jm6_dwxl/acceptance.json：原Docker历史基线，本轮没有重新启动Docker图。

音频比较输出frontend-py310-final.json、frontend-py38-final.json位于~/.local/state/guidebot/migrations/foxy-py38/。
未提交或推送，保留此前已有工作区修改。
