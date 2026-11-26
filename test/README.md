# 测试与开发辅助工作区

正式业务不导入本包。所有主动诊断、工具、仿真验证、实验、历史实现归本目录。

| 目录 | 用途 |
| --- | --- |
| unit/ | Python、C++、JS 分类回归 |
| integration/ | 跨模块和本机 ROS 离线验收 |
| diagnostics/ | 音频、ROS环境和导航主动检查 |
| tools/ | 部署安装、构建、动作制作、导览准备、传感器采集 |
| simulation/ | 模拟验证使用说明 |
| experiments/ | 实验脚本与 reports/ 脱敏历史证据 |
| fixtures/ | 小型固定测试样本 |
| archive/ | 历史实现，禁止正式导入 |

```bash
conda activate GuideBot
python -m unittest discover -s test -t .
python test/tools/tour/prepare.py --dry-run
```

完整离线验收见 docs/repository-layout.md。需要真实硬件或云端的工具必须人工按其说明运行。
录音、原始点云、bag、模型和批量结果放 Git 外。历史 reports 和 archive 保留当时原始路径作为证据，不是当前运行命令。
