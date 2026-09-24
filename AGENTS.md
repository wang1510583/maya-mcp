# Project custom Maya tools

- 用户说「创建自定义身体绑定」「新增自定义身体绑定」时，调用 MCP `create_custom_body_rig`。
  如果当前客户端尚未刷新直接工具，使用 `call_maya_tool(name="create_custom_body_rig", arguments={})`。
- 对应独立 Python 模块：`maya_agent.rigs.custom_body`，公开入口 `build()`，中文名称「自定义身体绑定」。
- 这是用户已确认的自定义脊柱绑定；默认四节，v1.1.0 支持新建时传入 `segment_count`（2–64，骨骼/控制器同数量）和 `height`（总高度，默认 6 厘米）。不要替换为默认 biped、auto_rig_character 或 AdvancedSkeleton。
- 先查询当前 Maya 场景；保留现有动画、蒙皮及绑定。重复创建使用独立命名空间，不删除旧绑定。
- 新增功能先读 `maya_agent/rigs/custom_body/README.md`。修改相应组件和版本化模板，并验证已有行为。
- 模块数据在包内，不能重新依赖 `outputs/scene-study` 或临时脚本。不要覆盖已有 Maya 文件。
