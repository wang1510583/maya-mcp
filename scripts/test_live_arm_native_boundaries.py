"""Audit actual Qt/native manipulator press and release, preserving current pose."""
import json,math
import maya.cmds as c
from maya_agent.rigs import live_edit


def inspect(root,role='end_fk',mode='move',auto_key=False):
    import maya.api.OpenMayaUI as ui
    import maya.api.OpenMaya as om
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    data=json.loads(c.getAttr(root+'.liveAlignmentData'));ctrl=data['controls'][role]
    nodes=list(data['controls'].values())+list(data['targets'].values())
    _,dest,frames,zero,restore=live_edit._plan(root)
    snapshot=live_edit._snapshot([dest.get(n+'.'+a,n+'.'+a) for n in dict.fromkeys([n for n,m in frames+restore]+zero) for a in live_edit.TR])
    tool=c.currentCtx();sel=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    context='Move' if mode=='move' else 'Rotate';command=c.manipMoveContext if mode=='move' else c.manipRotateContext
    options=dict(mode=command(context,q=True,mode=True),activeHandle=command(context,q=True,activeHandle=True))
    poses={};clicked=False;calls={'press':0,'release':0}
    old_begin=live_edit.before_drag;old_finish=live_edit.after_drag
    def begin(*args):
        calls['press']+=1;return old_begin(*args)
    def finish(*args):
        calls['release']+=1;return old_finish(*args)
    live_edit.before_drag=begin;live_edit.after_drag=finish
    def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def delta(a,b):return max(abs(x-y) for n,m in poses[a].items() for x,y in zip(m,poses[b][n]))
    initial=pose()
    try:
        c.autoKeyframe(state=auto_key);c.select(ctrl);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
        command(context,e=True,mode=2 if mode=='move' else 0,activeHandle=0 if mode=='move' else 2)
        c.refresh(f=True)
        view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
        x,y=view.worldToView(om.MPoint(c.xform(ctrl,q=True,ws=True,t=True)))[:2];y=widget.height()-y
        start=QtCore.QPoint(x+40,y);end=QtCore.QPoint(x+48,y-4)
        poses['before']=pose()
        QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start);clicked=True
        poses['press']=pose()
        QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
            QtCore.QPointF(end),QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,
            QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
        poses['native_move']=pose()
        QtWidgets.QApplication.processEvents();poses['solve']=pose()
        QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end);clicked=False
        poses['native_release']=pose()
        QtWidgets.QApplication.processEvents();poses['release']=pose()
        report=dict(role=role,mode=mode,press=delta('before','press'),native_move=delta('press','native_move'),
                    solve=delta('native_move','solve'),native_release=delta('solve','native_release'),
                    commit=delta('native_release','release'),total=delta('before','release'),
                    positions={k:v[ctrl][12:15] for k,v in poses.items()},calls=dict(calls))
    finally:
        if clicked:QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
        QtWidgets.QApplication.processEvents()
        if live_edit._gesture:live_edit.after_drag('cleanup')
        c.autoKeyframe(state=False);live_edit._restore(snapshot)
        command(context,e=True,**options);c.setToolTo(tool)
        c.select(sel,r=True) if sel else c.select(cl=True);c.autoKeyframe(state=auto)
        live_edit.before_drag=old_begin;live_edit.after_drag=old_finish
    report['restore']=max(abs(a-b) for n,m in initial.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
    return report
