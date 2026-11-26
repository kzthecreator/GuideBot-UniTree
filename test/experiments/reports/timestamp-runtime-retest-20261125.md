# 时间戳环境复测：INT8路径与调用历史

日期：2026-11-25。用户要求再次测试并报告。本轮仅增加离线复测工具和证据，未修改正式时间戳配置、依赖、模型或语音前端。没有启动ROS图、机器人SDK、云端、采音或播放。

## 结论

性能退步可复现，但不能把“7倍”当作所有流式场景的固定倍率。
在当前Python3.8/Torch2.4.1环境关闭动态INT8、改用FP32的实验中，耗时大幅降低，与旧环境FP32接近；两环境FP32边界在此次固定输入中一致。
这将主要嫌疑收敛到量化执行路径及底层后端差异，不能归因于Python3.8解释器本身；尚未定位到PyTorch/oneDNN具体算子或缺陷。
旧INT8还表现出明显的输入长度调用历史依赖，因此旧INT8不能直接充当正确性真值。
建议将FP32作为后续正式切换候选，先用真实文本的多段现场录音验证完整前缀实时行为；此次未直接改标准方案。

## 方法

工具：`tools/timestamps/retest_runtime.py`，支持默认INT8、`--float32`和`--six-only`。
旧环境GuideBot-py310-backup：Python3.10.22、Torch/torchaudio2.5.1、NumPy2.2.6。
新环境GuideBot：Python3.8.20、Torch/torchaudio2.4.1、NumPy1.24.4。
FunASR均1.4.26，核对auto_model.py、monotonic_aligner/model.py、cif_predictor.py和load_utils.py源码哈希相同。
同一本地模型、同一`recordings/long-reply/reply.wav`前6秒、单声道16kHz PCM16。
音频SHA256为`ae1cfa97b2fad78da6ea2a960577ebc1bc107ce0def6aa770e697259b3bee73e`。
模型参数threads=1、reuse_predictor=True、count_offset=-1，运行时torch有效线程数确为1，量化engine=onednn。
模型处于eval状态；固定每次推理随机种子1729。
21单元测试标签是长度控制输入，不是该录音的人工逐字真值，不能推导文字匹配准确性。

逐步前缀依次1s、4s、6s流式和6s final，每项3次。旧→新→新→旧交替，全部串行，避免基准互相争用。
补充新旧“从首次就提交6s”的各6次调用；FP32旧1轮、新2轮各12次。
合计9个独立模型进程、96次对齐调用。
下表热运行中位数取每项第2/3次；INT8旧/新各4个样本，新FP32取2轮共4个样本。模型加载耗时另计。
未固定CPU频率、独占CPU或清理用户进程，数字代表本机本次离线条件，不是实时截止保证。

## 逐步增长前缀结果

| 输入/模式 | 旧INT8 | 新INT8 | 旧FP32 | 新FP32 |
| --- | ---: | ---: | ---: | ---: |
| 1s流式 | 0.223s | 1.232s | 0.240s | 0.246s |
| 4s流式 | 1.266s | 2.284s | 0.529s | 0.504s |
| 6s流式 | 1.923s | 3.433s | 0.694s | 0.686s |
| 6s final | 1.874s | 3.415s | 0.657s | 0.648s |

首轮新FP32热运行分别0.250/0.505/0.681/0.643s；第二个独立进程再次验证，合并中位数已列入表格。
在此次片段中，关闭INT8大幅改善速度，但不意味着所有设备或所有模型都适合FP32。

## 为什么此前测得约7倍

直接从6s开始、相同长度重复时，旧INT8 final热运行0.514s，新3.368s，约6.55倍，复现此前现象。
先提交1s、4s再提交6s时，旧INT8变为1.874s，新3.415s，约1.82倍。
旧INT8从6s开始时预测count约25.033；先经1s/4s时变为44.119。
新INT8两种调用顺序下count均约25.045。
因此“7倍”只覆盖此前固定6s实验，不能外推全部实时前缀；调用历史异常尚未定位根因。

## 边界结果

- 新旧FP32：1/4/6s及final对应边界完全一致，count差异仅浮点微量。
- 同一新FP32独立进程复测：逐次边界与count一致。
- 直接从6s开始的新旧INT8：21个边界最大差20ms。
- 增长前缀的新旧INT8：4s分别返回21/14单元，共有索引最大边界差1.265s；6s均21单元，最大差0.5s。
- 新INT8对新FP32：4s均14单元，最大边界差0.28s；6s最大差20ms。

因此此前“最大20ms”只能描述单独6s控制输入，不能描述整个流式过程。更快或新旧一致都不等于已通过人工对齐准确性验收。

## 原始证据与复现

全部JSON、逐次阶段耗时和日志：`~/.local/state/guidebot/experiments/timestamp-retest-20261125/`。
`old-a/b`、`new-a/b`为交替INT8；`old-six/new-six`为首次6s；`old-fp32/new-fp32/new-fp32-b`为FP32。

```bash
conda activate GuideBot
python tools/timestamps/retest_runtime.py --output /tmp/guidebot-int8.json
python tools/timestamps/retest_runtime.py --float32 --output /tmp/guidebot-fp32.json
python tools/timestamps/retest_runtime.py --six-only --output /tmp/guidebot-six.json
```

原录音必须已由用户恢复，工具不会下载录音或启动真实设备。
