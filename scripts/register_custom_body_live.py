"""Hot-register the new tool without clearing the scene or disrupting existing tools/UI."""
import importlib
import maya_agent.tools.registry as registry

old_tools = dict(registry._REGISTRY)
old_result_class = registry.ToolResult
importlib.reload(registry)
# Existing tool handlers retain their original imported ToolResult class.
registry.ToolResult = old_result_class
registry._REGISTRY.update(old_tools)
importlib.invalidate_caches()
import maya_agent.tools.custom_body_rig as custom_tool
importlib.reload(custom_tool)

import maya_mcp.maya_adapter as adapter
importlib.reload(adapter)

ui_updated = False
from maya_agent.ui.main_window import get_window_instance
from maya_agent.utils.maya_compat import import_qt
window = get_window_instance()
if window is not None:
    QtCore, QtGui, QtWidgets, _ = import_qt()
    for tree in window.tabs.findChildren(QtWidgets.QTreeWidget, 'settingsToolTree'):
        item = None
        category = None
        for index in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(index)
            if parent.text(0) == 'rigging':
                category = parent
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.data(0, QtCore.Qt.UserRole) == 'create_custom_body_rig':
                    item = child
        if category is None:
            category = QtWidgets.QTreeWidgetItem(['rigging'])
            tree.addTopLevelItem(category)
        if item is None:
            item = QtWidgets.QTreeWidgetItem(category)
        item.setText(0, '自定义身体绑定')
        item.setData(0, QtCore.Qt.UserRole, 'create_custom_body_rig')
        item.setToolTip(0, registry.get_tool('create_custom_body_rig').description)
        ui_updated = True

existing_query = registry.run_tool('get_scene_info', {})
assert existing_query.ok and isinstance(existing_query.data, dict)
result = {'registered': registry.get_tool('create_custom_body_rig').display_name,
          'tool_count': len(registry.all_tools()), 'ui_updated': ui_updated,
          'existing_tools_still_work': True}
