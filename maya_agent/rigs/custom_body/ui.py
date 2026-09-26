"""Standalone Maya commands UI; no MCP, HTTP client or AI provider dependency."""
from .definition import DISPLAY_NAME, VERSION

WINDOW = 'CustomBodyRigWindow'
_instance = None


class BodyRigWindow:
    def __init__(self,extra_options=None):
        import maya.cmds as c
        from maya_agent.rigs import ui_common as layout
        self.c = c
        self.targets = []
        self.last_result = None
        self.manual_dimensions = (4, 6.0)
        was_tracking = c.selectPref(query=True, trackSelectionOrder=True)
        c.selectPref(trackSelectionOrder=True)
        layout.begin(c,WINDOW,DISPLAY_NAME,VERSION,'按腰部 → 脊柱 → 胸部的顺序，选择 2–64 根骨骼或物体。')
        self.selection_frame,self.target_list=layout.selection(c,self.read_selection,self.reverse)
        c.frameLayout(self.selection_frame,edit=True,enable=False)
        self.targets_list=self.target_list
        c.rowLayout(numberOfColumns=3,adjustableColumn=3,columnWidth3=(110,110,240))
        c.button(label='↑ 上移',width=105,command=lambda *_:self.move(-1))
        c.button(label='↓ 下移',width=105,command=lambda *_:self.move(1))
        c.button(label='移除所选行',command=self.remove)
        c.setParent('..')
        self.target_info=c.text(label='尚未读取目标',align='left',height=22)
        self.namespace=layout.namespace(c,'customBody')
        self.count = c.intFieldGrp(label='骨骼 / 控制器数', numberOfFields=1, value1=4,
                                   columnWidth2=(110, 100))
        self.height = c.floatFieldGrp(label='总高度（厘米）', numberOfFields=1, value1=6,
                                      precision=3, columnWidth2=(110, 100))
        self.selection_mode = c.checkBox(label='在选择物体上创建并驱动', value=False,
                                         changeCommand=self.toggle_selection)
        c.text(label='勾选后，数量、位置和朝向由目标列表决定。', align='left', height=22)
        self.copy_animation = c.checkBox(label='拷贝动画至控制器', value=False, enable=False,
                                         changeCommand=self.toggle_animation)
        self.animation_fields,self.frame_bounds,self.sample_step=layout.animation_fields(c)
        if extra_options:extra_options()
        self.create_button=layout.create_button(c,'创建自定义身体绑定',self.create)
        self.status=layout.status(c,'就绪。' if was_tracking else '已开启选择顺序追踪，请从腰到胸重新逐个选择，再读取目标。')
        c.showWindow(WINDOW)

    def status_text(self, text):
        self.c.scrollField(self.status, edit=True, text=text)

    def toggle_selection(self, *_):
        enabled = self.c.checkBox(self.selection_mode, query=True, value=True)
        self.c.intFieldGrp(self.count, edit=True, enable=not enabled)
        self.c.floatFieldGrp(self.height, edit=True, enable=not enabled)
        self.c.frameLayout(self.selection_frame, edit=True, enable=enabled)
        self.c.checkBox(self.copy_animation, edit=True, enable=enabled)
        if not enabled:
            self.c.checkBox(self.copy_animation, edit=True, value=False)
        self.toggle_animation()
        if enabled:
            self.manual_dimensions = (self.c.intFieldGrp(self.count, query=True, value1=True),
                                      self.c.floatFieldGrp(self.height, query=True, value1=True))
            self.c.floatFieldGrp(self.height, edit=True, label='链长（厘米）')
            self.read_selection()
        else:
            self.c.intFieldGrp(self.count, edit=True, value1=self.manual_dimensions[0])
            self.c.floatFieldGrp(self.height, edit=True, value1=self.manual_dimensions[1], label='总高度（厘米）')
            self.status_text('标准模式：按数量和总高度创建独立绑定。')

    def toggle_animation(self, *_):
        enabled = self.c.checkBox(self.selection_mode, query=True, value=True) and self.c.checkBox(
            self.copy_animation, query=True, value=True)
        self.c.columnLayout(self.animation_fields, edit=True, enable=enabled)

    def read_selection(self, *_):
        from .targets import ordered_selection
        try:
            self.targets = ordered_selection()
            self.refresh_list()
            self.status_text('请检查目标列表顺序；可上移、下移，再点击创建。')
        except Exception as exc:
            self.status_text(str(exc))

    def refresh_list(self, selected=None):
        c = self.c
        c.textScrollList(self.target_list, edit=True, removeAll=True)
        count = len(self.targets)
        for i, target in enumerate(self.targets):
            role = '腰部' if i == 0 else '胸部' if i == count-1 else '脊柱'
            c.textScrollList(self.target_list, edit=True, append='{:02d}  {}  {}'.format(i+1, role, target))
        if selected is not None and 0 <= selected < count:
            c.textScrollList(self.target_list, edit=True, selectIndexedItem=selected+1)
        c.text(self.target_info, edit=True, label='{} 个目标 → {} 根骨骼 + {} 个控制器'.format(count, count, count))
        if c.checkBox(self.selection_mode, query=True, value=True):
            import math
            c.intFieldGrp(self.count, edit=True, value1=count)
            try:
                points = [c.xform(n, query=True, worldSpace=True, translation=True) for n in self.targets]
                length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
            except Exception:
                length = 0
            c.floatFieldGrp(self.height, edit=True, value1=length)

    def move(self, direction):
        indices = self.c.textScrollList(self.target_list, query=True, selectIndexedItem=True) or []
        if not indices:
            return
        index, other = indices[0]-1, indices[0]-1+direction
        if 0 <= other < len(self.targets):
            self.targets[index], self.targets[other] = self.targets[other], self.targets[index]
            self.refresh_list(other)

    def reverse(self,*_):
        self.targets.reverse()
        self.refresh_list()

    def remove(self, *_):
        indices = self.c.textScrollList(self.target_list, query=True, selectIndexedItem=True) or []
        if indices:
            del self.targets[indices[0]-1]
            self.refresh_list()

    def create(self, *_):
        from . import build
        c = self.c
        self.last_result = None
        c.button(self.create_button, edit=True, enable=False)
        try:
            selected = c.checkBox(self.selection_mode, query=True, value=True)
            kwargs = {'namespace': c.textFieldGrp(self.namespace, query=True, text=True).strip()}
            if selected:
                kwargs['targets'] = list(self.targets)
                kwargs.update(copy_animation=c.checkBox(self.copy_animation, query=True, value=True),
                              start_frame=c.floatFieldGrp(self.frame_bounds, query=True, value1=True),
                              end_frame=c.floatFieldGrp(self.frame_bounds, query=True, value2=True),
                              sample_step=c.floatFieldGrp(self.sample_step, query=True, value1=True))
            else:
                kwargs.update(segment_count=c.intFieldGrp(self.count, query=True, value1=True),
                              height=c.floatFieldGrp(self.height, query=True, value1=True))
            rig = build(**kwargs)
            self.last_result = rig
            self.status_text('已创建 {}：{} 根骨骼 / {} 个控制器。{}\n可按 Ctrl+Z 撤销本次创建。'.format(
                rig['namespace'], rig['segment_count'], rig['segment_count'],
                '已按列表顺序驱动目标。' if selected else '独立绑定已就绪。'))
            if rig.get('animation_transfer'):
                self.status_text('已创建 {}；动画已转移至控制器，共 {} 个采样帧。\n原曲线保留在 {}。Ctrl+Z 可整次撤销。'.format(
                    rig['namespace'], rig['animation_transfer']['sample_count'],
                    rig['animation_transfer']['source_animation_backup']))
            return rig
        except Exception as exc:
            self.status_text('创建未完成：' + str(exc))
            c.warning(str(exc))
            return None
        finally:
            c.button(self.create_button, edit=True, enable=True)


def show():
    global _instance
    _instance = BodyRigWindow()
    return _instance
