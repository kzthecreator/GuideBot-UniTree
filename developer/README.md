# 上层开发者入口：任务 A / 任务 B

日常编辑集中在本目录。文本文件使用 UTF-8，修改 prompt 后重启程序。

| 文件 | 用途 | 生效方式 |
| --- | --- | --- |
| `conversation/prompt.md` | 对话模型的身份、表达方式和事实边界 | 启动时读取 |
| `conversation/knowledge/` | 对话模型可检索的场所资料 | 编辑后显式同步 |
| `actions/prompt.md` | 动作选择模型的语义选择与文本对齐要求 | 创建动作模型客户端时读取 |
| `tour/prompt.md` | 导览插话问答要求 | 导览会话启动时读取 |
| `tour/context_template.md` | 当前点位与讲解进度的可见模板 | 点位/问答状态变化时更新 |
| `tour/points.json` | 离线注册的讲解点与讲解词 | 准备音频后导览播放 |
| `tour/speech.json` | 离线TTS模型、音色与语速 | 修改后重新准备音频 |

动作选择 prompt 无需维护动作清单。后台自动从注册动作读取 ID、说明、适用和不适用场景，追加到 `actions/prompt.md` 文末后发送模型。角色、选择规则、JSON 输出协议及示例全部写在该文件中，DeepSeek 和本地 Qwen 使用同一份文件，后台不再追加其他提示指令。动作注册、轨迹和执行限制由程序维护，不在本用户目录展示。

## 知识库同步

在 GuideBot Conda 环境中，从仓库根目录执行：

```bash
conda activate GuideBot
python -m GuideBot.conversation.knowledge --dry-run
python -m GuideBot.conversation.knowledge
```

不带 `--dry-run` 的同步命令会调用云端服务。运行程序不会自动上传，除非显式使用 `--sync-knowledge`。旧目录的同步记录自动兼容，凭据和同步状态仍在 Git 外。

## 导览文件结构

`schema_version` 为格式版本。`points` 按编排顺序保存讲解点，每项包含：

- `id`：稳定且唯一的讲解点标识。
- `name`：讲解点名称。
- `script`：该点的讲解词。

讲解词由用户维护，不自动上传到自由对话知识库。准备过程会将文本发送StepFun TTS，生成本地音频。运行时按列表顺序讲解，插话回答后续讲；当前仅人工确认到达，没有真实导航。

```bash
python test/tools/tour/prepare.py --dry-run
python test/tools/tour/prepare.py
python main.py --service tour
```

修改prompt后重启；修改讲解词或speech.json后重新准备。完整说明见 [导览服务](../docs/tour-service.md)。

## 任务与配置边界

conversation/ 对应任务 A：大厅接待与咨询。tour/ 对应任务 B：固定流程讲解、插话问答与续讲。
actions/ 是手势规则入口，当前导览语音版不启用手势。
config/ 集中正式 ROS 参数、导航显示、G1 关节限制和密钥占位模板。
两项任务各自保持完整 Prompt，不叠加人设，不自动共用云端知识库。
points.json 保留当前点位和讲解词格式，暂不增加尚未实现的导航字段。
完整结构见 [目录规范](../docs/repository-layout.md)。
