# GuideBot-UniTree

宇树 G1 导览机器人语音组件：阶跃实时语音、宇树 SDK 播放、组播麦克风、
LocalVQE 回声处理、播放期间音量门限和知识库检索。

```bash
conda activate GuideBot
source /etc/profile.d/guidebot-audio.sh
python GuideBot/conversation/conversation.py
# 实验性字级时间戳
python GuideBot/conversation/conversation.py --timestamps
```

按 Enter 开始，再按 Enter 结束。运行前需要本机 SDK、模型、依赖及本地密钥配置；
以上命令不是全新机器的一键安装器。

维护后继续开发，请先阅读 [Agent 续接文档](docs/AGENT_HANDOFF.md)。
`GuideBot/agent` 仅放身份提示词和知识文本。当前知识文本是待运营方核实的材料，
不可把示例或待确认信息当成真实场所事实。
