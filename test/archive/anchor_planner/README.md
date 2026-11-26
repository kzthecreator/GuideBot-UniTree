# 旧锚点规划器归档

仅供历史实验与回归测试；正式业务不得导入本目录。

- planner.py：旧锚点 JSON/SSE 规划请求、输出校验与回调。
- prompts.py：旧协议 Prompt 和 few-shot 的消息组装。
- prompt.md：从 developer/actions/anchor_prompt.md 原样归档。
- conversation-few-shots.json：从 assets/motions 原样归档的旧示例。

正式手势规划只读 developer/actions/prompt.md。正式流式解析与客户端配置在 GuideBot/gesture/streaming.py，语义规划器不继承旧规划方法。

开发侧查看历史协议：

```bash
python -m test.tools.gesture prompt --text '欢迎参观'
```

该命令不请求云端、不使用音频或运动。evaluate 子命令会调用云端，仅供显式人工实验。
