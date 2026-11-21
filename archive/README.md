# 历史归档

这些内容用于追溯旧实现，不由正式语音入口导入，不纳入默认运动构建。
归档不代表删除功能实现，也不代表仍可独立启动。

| 路径 | 内容 | 替代入口 |
| --- | --- | --- |
| `doubao-demo/` | Mac 上验证过的原始豆包 demo | 当前统一使用 StepFun |
| `doubao/doubao.py` | 曾接入 G1 的豆包 provider | `GuideBot/conversation/stepfun.py` |
| `doubao/conversation_legacy.py` | 归档前的多 provider CLI 快照，仅作历史参考 | `GuideBot/conversation/conversation.py` |
| `doubao/tests/` | 豆包事件回归测试 | 手动运行归档测试，不进入正式测试发现 |
| `unitree-motion-legacy/play.cpp` | 旧手柄单动作播放 | 当前 motion_library_server |
| `unitree-motion-legacy/play_with_motions.cpp` | 旧拳击状态机 | 当前导览动作库 |
| `unitree-motion-legacy/tts_probe.cpp` | TTS speaker_id 扫描 | 当前流式语音链路 |
| `unitree-motion-legacy/watchdog.cpp` | 启动旧 play 的手柄守护进程 | 无默认启用替代 |
| `unitree-motion-legacy/systemd/` | 对应上游部署示例 | 不安装、不自动启动 |

基础 `teach.cpp`、带名称注册的 `teach_with_name.cpp` 及站姿腰部演示保留在 drivers。
运动归档保留原 MIT LICENSE、UPSTREAM.json；后者为导入时原始文件清单。
归档源码未单独配置构建系统，上游 service 中的账户及绝对路径未适配本机。

豆包历史测试可从仓库根目录手动运行（不连接云端或设备）：

```bash
conda activate GuideBot
python -m unittest discover -s archive/doubao/tests -p 'test_*.py'
```

`conversation_legacy.py` 仅为历史代码快照，旧相对路径和参数不得作为当前使用说明。
配置与密钥继续留在本机，不将归档 demo 内的本机配置加入 Git。
