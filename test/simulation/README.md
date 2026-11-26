# 模拟验证

当前模拟资源通过集成测试显式注入，见 test/integration/runtime 和 test/integration/ros2。
正式运行的 simulated 执行模式由 runtime 装配，不从 test 导入后端。
将来新增独立场景回放和假机器人工具时放本目录，不复制正式业务算法。
