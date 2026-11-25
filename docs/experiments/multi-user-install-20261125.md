# 本机多账户安装验收（2026-11-25）

本次范围为 Ubuntu 20.04 / aarch64 / ROS2 Foxy / Python 3.8.20。
发布内容包括此前未提交的四节点结构、倾听／说话调度、运动门禁调整与诊断，以及本轮部署工具。
不把部署通过等同于真机动作问题修复。

## 安装产物

- `environment.yml`：创建用户自己的命名 Conda 环境 GuideBot。
- `requirements.txt`：79 个已验证版本，不使用旧3.10快照或本机file URL。
- `requirement.txt`：引用同一份清单。
- `tools/deployment/setup.py`：公共资源导出、校验、Python安装、每账户完整安装。
- `config/conversation.env.example`：不含值的密钥模板。
- `docs/setup.md`：fork/clone、新账户、独立知识同步及离线验收步骤。

公共模型与原生音频库已准备在本机 `/var/tmp/guidebot-runtime`，14 个文件均记录 SHA256。
它是本机资源缓存，不进入 Git；`/var/tmp` 被清理后需重新导出。
AGC2 桥接库已改成 `$ORIGIN` 运行路径；依赖从同目录解析。

## 实际验证

测试使用新建的 Conda Python3.8环境和 `/var/tmp` 独立 checkout，而非只在现有环境 pip check。
独立 checkout 不带 recordings，通过单独的模型、原生构建与 ROS install 目录运行。
测试仍由当前 Linux 用户执行，没有冒称切换到另一个账户或使用对方凭证。

| 检查 | 结果 |
| --- | --- |
| `requirement.txt` 依赖完整安装 | 通过 |
| CycloneDDS 0.10.2 无缓存源码构建 | 修正 SDK 构建视图后通过 |
| `pip check` | 通过 |
| ROS 和 SDK 导入，不初始化 DDS | 通过 |
| LocalVQE v1.2、AGC2 原生初始化 | 通过，无录放音 |
| 10 项动作资产及限位 | 通过 |
| 正式／新环境主测试 | 各146项通过 |
| 运动 Python 回归 | 38项通过 |
| 原生 CTest | 4项通过 |
| 新环境真实ROS→原生offline-server | 通过，无机器人连接 |
| 四组会话生命周期 | 通过 |

首轮发现两项原环境掩盖的问题：

1. 共享 CycloneDDS prefix 缺少 `bin`，上游源码构建器拒绝识别。
   每账户安装建立 include/lib 链接和空 bin；不修改 `/opt`，也不使用其他账户缓存轮子。
2. 默认 domain42 的参与者索引已被本机其他进程占用。
   内部 localhost ROS graph 改用 `50 + UID % 40`，保留显式覆盖；SDK DDS不受影响。

新账户须填写自己的密钥，并运行显式知识同步命令。
验收使用 `--dependencies-only` 跳过这两项账户业务配置，没有复制维护者的云端 ID。

## 证据与数据边界

原始日志：`~/.local/state/guidebot/experiments/multi-user-install-20261125/`。
新环境动作链：`~/.local/state/guidebot/ros2/foxy-ynid568m/acceptance.json`。
四组生命周期：`foxy-cu4u6psg`、`foxy-56xq_l51`、`foxy-8fnl56l2`、`foxy-mj3nh89d`。

recordings 从当前 Git 树取消跟踪，本机文件不删除；已有 Git 历史不重写。
本轮未启动真机、采音、播放或云端会话。

## 保留的真机问题

现场 `foxy-lj6qso7y`：greet_open 已启动，播完后也已切倾听并请求 neutral。
左肩实测／指令差0.035737rad，超过0.03rad起步门禁，导致neutral与后续动作拒绝。
此门禁和原生拒绝后ROS等待超时的问题仍保留，后续单独处理。
