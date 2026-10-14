"""Small Maya window for the reusable BIP retarget module."""
from pathlib import Path

WINDOW='CustomBipRetargetWindow'


def show_ui():
    import maya.cmds as c
    if c.window(WINDOW,exists=True):c.deleteUI(WINDOW)
    c.window(WINDOW,title='Max BIP → 角色控制器 v1.7',widthHeight=(520,640),sizeable=True)
    form=c.columnLayout(adjustableColumn=True,rowSpacing=9,columnAttach=('both',12))
    c.text(label='首次导入：请先让 Maya 角色处于创建绑定时的姿态。',align='left')
    c.text(label='腰控制器对应 Bip001 总根；骨盆扭转保存在 BIP骨盆旋转 XYZ。',align='left')
    character=c.optionMenu(label='Maya 角色')
    roots=[n for n in c.ls(type='transform',long=True) or [] if c.objExists(n+'.integratedRigData')]
    for n in roots:c.menuItem(label=n,parent=character)
    mode=c.optionMenu(label='读取方式')
    c.menuItem(label='动画文件（无需 MCP）',parent=mode)
    c.menuItem(label='Max 当前动作（需要连接）',parent=mode)
    max_root=c.textFieldGrp(label='Max Biped 根',text='Bip001',enable=False)
    source=c.textFieldButtonGrp(label='BIP / JSON 文件',buttonLabel='浏览',text='')
    def browse(*_):
        files=c.fileDialog2(fileMode=1,caption='选择 BIP 或采样 JSON',fileFilter='BIP / JSON (*.bip *.json)')
        if files:c.textFieldButtonGrp(source,e=True,text=files[0])
    c.textFieldButtonGrp(source,e=True,buttonCommand=browse)
    c.text(label='BIP 自动启动后台 Max，无需手动打开 Max 或启动 MCP。\n本机需已安装并激活 Max；JSON 不需要 Max。',align='left')
    executable=c.textFieldButtonGrp(label='后台 Max 程序',buttonLabel='浏览',text='',placeholderText='留空自动查找 3dsmaxbatch.exe')
    def browse_max(*_):
        files=c.fileDialog2(fileMode=1,caption='选择 3dsmaxbatch.exe',fileFilter='Max Batch (3dsmaxbatch.exe)')
        if files:c.textFieldButtonGrp(executable,e=True,text=files[0])
    c.textFieldButtonGrp(executable,e=True,buttonCommand=browse_max)
    fps=c.intFieldGrp(numberOfFields=1,label='BIP 源帧率',value1=30)
    native=c.checkBox(label='使用 Max Biped 原生身材适配（推荐）',value=True,enable=False)
    def change_mode(*_):
        live=c.optionMenu(mode,q=True,select=True)==2
        c.textFieldGrp(max_root,e=True,enable=live)
        c.textFieldButtonGrp(source,e=True,enable=not live)
        c.textFieldButtonGrp(executable,e=True,enable=not live)
        c.intFieldGrp(fps,e=True,enable=not live)
        c.checkBox(native,e=True,enable=live)
        if not live:c.checkBox(native,e=True,value=True)
    c.optionMenu(mode,e=True,changeCommand=change_mode)
    key_mode=c.optionMenu(label='关键帧方式')
    c.menuItem(label='按部位保留源关键帧时间',parent=key_mode)
    c.menuItem(label='按间隔采样打帧',parent=key_mode)
    c.text(label='身体、头部、左右手、左右脚各用本组源时间点，不自动补帧。',align='left')
    use_range=c.checkBox(label='指定 Max 采样范围',value=False)
    frames=c.floatFieldGrp(numberOfFields=2,label='源起止帧',value1=0,value2=73)
    step=c.floatFieldGrp(numberOfFields=1,label='计算采样间隔',value1=.5)
    start=c.floatFieldGrp(numberOfFields=1,label='Maya 动画起点',value1=c.playbackOptions(q=True,min=True))
    ref=c.floatFieldGrp(numberOfFields=1,label='首次校准参考帧',value1=c.currentTime(q=True))
    overwrite=c.checkBox(label='覆盖范围内已有动画（保留曲线备份）',value=False)
    status=c.text(label='选择已保存的 BIP 文件即可导入。后台 Max 启动可能需要几十秒。',align='left',wordWrap=True)
    def run(dry=False):
        from . import bip_retarget as br
        if not roots:c.warning('请先创建集成角色绑定。');return
        live=c.optionMenu(mode,q=True,select=True)==2
        path='' if live else c.textFieldButtonGrp(source,q=True,text=True).strip()
        if not live and not path:c.warning('请先选择 BIP 或 JSON 动画文件。');return
        common=dict(root=c.optionMenu(character,q=True,value=True),reference_frame=c.floatFieldGrp(ref,q=True,value1=True),
                    overwrite=c.checkBox(overwrite,q=True,value=True),dry_run=dry,
                    key_mode='source' if c.optionMenu(key_mode,q=True,select=True)==1 else 'sampled')
        dialog=None
        try:
            c.waitCursor(state=True)
            c.columnLayout(form,e=True,enable=False)
            if path and Path(path).suffix.lower()=='.json':
                result=br.retarget_json(path,start_frame=c.floatFieldGrp(start,q=True,value1=True),**common)
            else:
                use=c.checkBox(use_range,q=True,value=True)
                if not live:
                    from PySide2 import QtCore,QtWidgets
                    from shiboken2 import wrapInstance
                    from maya.OpenMayaUI import MQtUtil
                    parent=wrapInstance(int(MQtUtil.mainWindow()),QtWidgets.QWidget)
                    dialog=QtWidgets.QProgressDialog('正在启动后台 Max…','取消',0,0,parent)
                    dialog.setWindowTitle('后台 Max 转换 BIP')
                    dialog.setWindowModality(QtCore.Qt.ApplicationModal)
                    dialog.setMinimumDuration(0)
                    dialog.show()
                def progress(elapsed):
                    from PySide2.QtWidgets import QApplication
                    dialog.setLabelText('后台 Max 转换中：{:.0f} 秒（Esc 取消）'.format(elapsed))
                    QApplication.processEvents()
                    return not dialog.wasCanceled()
                result=br.retarget_max_bip(max_root=c.textFieldGrp(max_root,q=True,text=True),bip_path=path or None,
                    native_adaptation=c.checkBox(native,q=True,value=True),
                    backend='live' if live else 'batch',max_executable=c.textFieldButtonGrp(executable,q=True,text=True).strip() or None,
                    max_fps=c.intFieldGrp(fps,q=True,value1=True),progress=None if live else progress,
                    start_frame=c.floatFieldGrp(frames,q=True,value1=True) if use else None,
                    end_frame=c.floatFieldGrp(frames,q=True,value2=True) if use else None,
                    sample_step=c.floatFieldGrp(step,q=True,value1=True),output_start=c.floatFieldGrp(start,q=True,value1=True),**common)
            if dry:
                if result.get('key_groups') is not None:
                    from .bip_sparse import GROUP_NAMES
                    message='分组检查通过：'+ '，'.join('{} {} 帧'.format(label,len(result['key_groups'][group])) for group,label in GROUP_NAMES.items() if group in result['key_groups'])
                else:message='映射检查通过：将保留 {} 个采样时间点。'.format(result['sample_count'])
            else:
                c.playbackOptions(min=result['start_frame'],max=result['end_frame'])
                if result.get('key_mode')=='source':
                    message='已按 {} 个部位独立保留源关键帧；与适配后 Biped 对比，过渡位置最大差约 {:.3f} cm，旋转 {:.3f}°。可 Ctrl+Z 撤销。'.format(len(result['key_groups']),result['max_sparse_position_error_cm'],result['max_sparse_rotation_error_degrees'])
                else:message='已导入 {} 个采样；控制器烘焙误差 {:.6g}。可 Ctrl+Z 撤销。'.format(result['sample_count'],result['max_world_error'])
            c.text(status,e=True,label=message)
        except Exception as exc:
            c.text(status,e=True,label=str(exc));c.warning(str(exc))
        finally:
            if dialog is not None:dialog.close();dialog.deleteLater()
            if c.layout(form,exists=True):c.columnLayout(form,e=True,enable=True)
            c.waitCursor(state=False)
    c.button(label='检查映射',height=30,command=lambda *_:run(True))
    c.button(label='导入动画至控制器',height=36,command=lambda *_:run(False))
    c.showWindow(WINDOW)
    return WINDOW
