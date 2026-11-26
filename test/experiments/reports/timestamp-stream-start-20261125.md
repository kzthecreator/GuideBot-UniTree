# 流式时间戳首次调用延迟修复

## 结论

现场 foxy-nlo3u897 确实使用 CUDA，没有回退到 CPU。最初0.5906875秒音频的2.272秒计算主要来自首次预测器执行，非流式音频排队：现场最新音频排队仅0.000614秒。权重加载完成不等于预测器CUDA算子已执行；此前worker直接报告alignment.ready，把首次调用开销留给了真实音频。

以前长音频GPU报告明确每个窗口预热一次后统计，因此不能把热态45.48秒音频约1.0715秒和冷态首段2.272秒直接比较。流式此外还有token数估计阶段；final=True直接使用原文单元数量，不执行该估计分支。流式完整前缀会重复推理，累计计算量也不等于整段仅运行一次。本轮修复的是首次调用尖峰，不是改动既定完整前缀对齐策略。

## 离线复现和定位

命令均使用GuideBot Python3.8，不打开音频设备/云API/机器人：

```bash
python tools/timestamps/benchmark_stream_start.py \
  --session /path/to/recorded/session --output /tmp/cold.json --assert-first-under .5
# 同一输入在新进程预热后对照：
python tools/timestamps/benchmark_stream_start.py \
  --session /path/to/recorded/session --warmup --output /tmp/warm.json --assert-first-under .5
# 真实spawn worker：
python tools/timestamps/benchmark_stream_start.py \
  --session /path/to/recorded/session --worker --output /tmp/worker.json --assert-first-under .5
```

session需要events.jsonl及speaker-16k.wav。探针取第一条最终转写与最初9451采样（0.5906875秒）；该输入对应此次现场首段，不是通用分段器。

冷态断言确实失败：首轮1.7274秒，紧接两轮0.0957/0.0908秒。独立新进程以 --profile-predictor 对预测器各子模块前后CUDA同步，首次cif_conv1d 1.2292秒，对照后续0.00127/0.00136秒；BLSTM首次0.1341秒，后续0.0056/0.0057秒。说明主要冷启动位置在GPU预测器卷积与循环层。尚未进一步区分驱动/cuDNN库加载与各算法初始化，不能把整个count计时当成纯数词运算；原阶段计时含CUDA异步工作的同步等待。

## 修改

MonotonicBackend.warmup仅针对CUDA，用0.64秒本地合成正弦PCM依次经过流式估计和final对齐，并等待CUDA完成；fork_rng恢复前端抖动所用随机状态。无ResponseAlignment状态、无音频设备、无伪时间戳发布。模型显式eval。

_worker在预热成功后才发布alignment.ready，并附device/seconds/calls；异常只发alignment.error，不谎报就绪。初始化约增加1.4秒，发生于会话启动准备阶段。CPU路径不增加额外预热，不改变GPU/CPU依赖。

## 验证

| 测量 | 结果 |
| --- | --- |
| 独立进程合成预热 | 1.479秒 |
| 预热后第一条真实0.591秒输入 | 0.0945秒 |
| 固定seed原始时间戳、估计值 | 与冷态原始输入结果完全相同 |
| 真实spawn worker预热 | 1.380秒 |
| spawn worker首段真实推理 | 0.0976秒 |
| 首段从入队到收到update | 0.1001秒 |
| 主Python测试 | 177通过；含预热成功后才就绪、预热失败不就绪 |

原GPU音频基准复测1/4/8/16/45.48秒分别0.1038/0.2060/0.3935/0.6028/1.1123秒（每种热态本轮仅1次，非稳定分布），5/14/34/73/197单元时间边界与此前GPU报告全部一致。没有证据表明流式稳态小窗口计算比整段更慢。

原始证据位于 ~/.local/state/guidebot/timestamp-stream-start-20261125/{cold,layers,warm,worker,long-audio}.json。worker日志 /tmp/guidebot-stream-worker-worker/alignment-worker.log。录音和原始运行产物未纳入Git。

## 边界

本轮未录音、播放、调用云或启动真机。0.1秒是本机此样本离线结果，不是所有负载的时延保证。后续目标词音频仍须先收到才能对齐，短动作窗口最低预算和DeepSeek响应9秒是独立问题，本修复不能保证现场一定产生动作。下次人工验收需重启进程，仍按Enter启动。
