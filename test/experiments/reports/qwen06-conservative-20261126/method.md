# Qwen3-0.6B保守推测解码实验

只更换官方Q8_0权重，使用原生llama.cpp CUDA，无Transformers/PyTorch规划推理；其余参数固定。

- 参考：Qwen3-1.7B Q8_0 + ngram-simple，size-n8、size-m16。
- 候选：Qwen3-0.6B Q8_0 + 相同ngram-simple参数。
- 控制：0.6B关闭推测解码，用于区分模型缩小与推测解码的收益。
- 模型来源：Qwen/Qwen3-0.6B-GGUF，Modelscope固定revision 32d6327dd2a5b42f7ce0fe5e6b6f25346b0ee8f9。
- SHA256：9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031。
- 不修改生产模型默认值或个人配置，不开启音频/机器人。

96条固定文本：12假动作/full固定prompt、48正例+48负例，原协议带双引用及各自次数；温度0/seed42/max384/schema/no-thinking/cache。预热不计时，HTTP封套解析后停止计时，评分在计时外。3次独立固定128token探针不加schema，仅用于吞吐。

生产32条：实际SemanticPlanner与真实动作表/现行10例prompt；首次请求保留，取total_seconds。捕获原有stream transport片段，在analyze返回后解析usage/timings，因此生产token/s也直接来自服务端。吞吐排除提示处理/HTTP/本地校验，不等于completion_tokens除以请求耗时。

速度成对比较双方都返回动作、以及双方都机械正确的同文本；不把漏选后的空输出当提速。机械通过仅动作集合+现有bind，不保证语义锚点自然，另外检查失败与引用。标签非独立盲审，不是现场成功率。

权重下载时先重跑1.7B参考；结束后补重复正例烟测检查时间漂移。原始证据：~/.local/state/guidebot/qwen06-20261126。
