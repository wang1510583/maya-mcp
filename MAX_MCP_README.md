# 3ds Max MCP

通过本机 MCP 连接，让 AI 查询和操作正在运行的 3ds Max。Max 端仅使用内置 Python、pymxs 和 Qt；MCP 依赖安装在外部 Python 环境，不注入 Max。

## 启动

1. 在 Max 中将本目录的 `install_max_mcp.ms` 拖入视口，或在 MAXScript Listener 执行：

   ```maxscript
   fileIn @"D:\MAYA\MayaAgent-main\MayaAgent-main\install_max_mcp.ms"
   ```

2. 出现 `Max MCP ready: 127.0.0.1:8766` 即启动成功。重复运行入口会刷新操作模块，不重复开启服务。重启 Max 后需要再次运行入口；当前版本不修改 Max 自动启动脚本。
3. 本机已将 `max-agent` 注册到 Codex 的 MCP 配置。如果当前会话没有出现新工具，重新打开客户端后检查连接。现有会话也可以通过 `max_mcp.connection.request` 使用桥接器。

其他 MCP 客户端使用 stdio 配置（按实际目录修改）：

```json
{
  "mcpServers": {
    "max-agent": {
      "command": "D:/MAYA/MayaAgent-main/MayaAgent-main/.venv-mcp/Scripts/python.exe",
      "args": ["D:/MAYA/MayaAgent-main/MayaAgent-main/scripts/run_max_mcp.py"]
    }
  }
}
```

外部 Python 要求 3.10+，依赖见 `requirements-mcp.txt`，本机已有 `.venv-mcp`。也可运行 `run_max_mcp.bat`；此进程使用标准输入输出与 MCP 客户端通信，并非聊天窗口。

## 提供的工具

| 工具 | 功能 |
| --- | --- |
| `get_max_status` | Max 版本、当前文件、连接状态 |
| `get_scene_info` | 对象及父级、选择、时间范围、帧率 |
| `execute_maxscript` | 在 Max 主线程执行 MAXScript |
| `execute_max_python` | 在 Max 主线程执行 Python，`rt` 为 pymxs.runtime；用 `result` 返回 JSON 可序列化结果 |
| `export_bip` | 将指定 Biped 根的动画导出为 BIP；默认拒绝覆盖已有文件 |
| `load_bip` | 将 BIP 载入指定 Biped，会改变该骨架当前动画 |
| `sample_biped` | 逐帧读取指定 Biped 的世界矩阵、层级、帧率和单位信息 |
| `capture_biped` | 采集动画并临时读取 Figure Mode 参考姿态，供 Maya BIP 重定向；完成后恢复 Figure Mode |

脚本工具可用于创建模型、修改材质、控制摄像机和动画等；目前不是一套封装好的 116 个专用工具。安装的第三方 Max 插件如果提供 MAXScript/Python 接口，也可以继续增加专用工具。

## BIP 采样约定

- 不传 `bones` 时，读取指定根下所有 `Biped_Object`，包括根；不会读取其他角色或附属普通模型。
- 帧范围包含起点和终点，按 `step` 递增；非整数倍终点额外采样一次。最多 10001 个样本。
- 矩阵为 Max 行向量 4×3 格式，最后一行是平移，世界向上轴为 Z。
- 返回 `system_unit` / `system_scale`；不能默认是厘米。当前测试场景是英寸。
- 采样使用时间上下文，不改变时间滑块位置。
- `capture_biped` 和原生适配返回 `source_keys`：映射骨骼及 COM 三轨的逐轨源键时间。源键不在规则采样网格上时，额外读取其准确姿态。Maya 默认按身体、头部、左右手、左右脚独立使用本组时间合集生成稀疏动画，计算采样密度与最终键密度独立。
- BIP 重定向到 Maya 集成绑定见 `BIP_RETARGET_README.md`。默认由内部桥接方法 `retarget_biped` 创建临时原生 Biped，匹配 Maya 骨长后载入动作并采样，完成后清理。指定文件不会覆盖 Max 原 Biped 动画。兼容模式仍可读取 `capture_biped` 的 Figure 参考姿态。
- 原生适配数据的 `native_retarget.profile` 使用 Maya 厘米数值配置临时 Biped，再按同一数值空间传回 Maya；不改 Max 场景系统单位。只有带该标记的数据使用此约定，普通原始采样仍须读取单位信息或显式求比例。

## 连接与关闭

只监听 `127.0.0.1:8766`。可通过两端一致的 `MAX_MCP_PORT` / `MAX_MCP_TOKEN` 环境变量配置；默认令牌只用于本机协议识别，不是隔离本机不可信程序的安全边界。多个 Max 实例需要不同端口。

网络线程只接收命令，Qt 定时器在 Max 主线程顺序执行。排队超时命令不会延后执行；已经开始执行的长脚本不能强制中断，超时后应查询场景再决定是否重试。Max 弹出模态窗口或正在忙时可能延迟响应。

在 Max 的 Python 中停止：

```python
from max_mcp import bridge
bridge.stop()
```

## 本机验证

- Max 2025 当前场景：查询、MAXScript、Python、BIP 导出和回读、74 帧 / 53 骨骼采样。
- 当前 BIP 回读前后最大矩阵元素误差约 `1.91e-6`。
- 桥接自动测试覆盖正常通信、错误令牌、排队超时不执行、不可序列化结果和禁止非回环监听。
- Max 2027 的 BIP 后台保存/读取曾单独验证；当前交互桥接完整测试在 Max 2025 完成。

主要实现：`max_mcp/bridge.py`（主线程桥接）、`max_mcp/max_adapter.py`（Max 操作）、`max_mcp/server.py`（MCP 工具）、`max_mcp/connection.py`（本机连接）。

`max_mcp/biped_retarget.py` 提供原生身材适配。已验证两节/三节脊柱动作和独立测试 BIP，自动拟合、载入、清理及原角色动画保留。默认由 Maya 导入窗口或 `retarget_max_bip_animation` 发起，无需手动管理中转骨架。
