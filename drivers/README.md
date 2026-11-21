# 底层驱动与模型适配

- `unitree_motion/`：G1 上肢运动服务及原生示教实现。人工操作入口在 `tools/motion/`。
- `localvqe/runtime.py`：AEC、NS、去混响适配；本机权重在 `localvqe/models/`。
- `agc2/runtime.py`：AGC2 适配；`build_agc2.sh` 与 `agc2_bridge.cpp` 构建原生桥接。
- `timestamps/runtime.py`：FunASR 时间戳模型和工作进程；本机权重在 `timestamps/models/`。

模型目录不纳入 Git，不会随克隆下载。SDK、共享库和编译产物仍使用外部安装路径。
这些模块导入时不启动机器人或音频设备。

当前目录、兼容入口和完整验证命令见 `../docs/repository-layout.md`。
