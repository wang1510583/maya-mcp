"""Run setup/drag/undo/redo/cleanup in separate Maya requests for native undo QA."""
import math
import maya.cmds as c
from scripts.test_integrated_rig_live import fixture,remove
from maya_agent.rigs.integrated import build
from maya_agent.rigs import live_edit,live_alignment

state=None


def setup(animated=True):
    global state
    import maya.api.OpenMayaUI as ui
    state=dict(before=set(c.ls(long=True)),selection=c.ls(sl=True,long=True) or [],
               frame=c.currentTime(q=True),auto=c.autoKeyframe(q=True,state=True),tool=c.currentCtx(),
               mode=c.manipRotateContext('Rotate',q=True,mode=True),
               handle=c.manipRotateContext('Rotate',q=True,activeHandle=True))
    c.autoKeyframe(state=False)
    group,parts=fixture('_nativeLiveRegression',animated)
    c.currentTime(3 if animated else 1)
    state['rig']=build({k:v for k,v in parts.items() if k in ('arm_L','leg_L')},namespace='_nativeLiveRegression')
    for key,p in state['rig']['parts'].items():
        live_alignment.enable(p,key.split('_')[0])
        if key=='arm_L':
            c.select(p['live_controls']['end_fk']);c.setToolTo('moveSuperContext')
            live_edit.before_drag('fixture');c.move(-.8,.5,1,p['live_controls']['end_fk'],r=True,ws=True);live_edit.after_drag('fixture')
            if animated:
                for n in p['live_controls'].values():c.setKeyframe(n,at=['rx','ry','rz'])
        else:c.setAttr(p['live_controls']['heel']+'.rx',-20)
    panel=next(p for p in c.getPanel(type='modelPanel') if int(ui.M3dView.getM3dViewFromModelPanel(p).widget())==int(ui.M3dView.active3dView().widget()))
    state.update(panel=panel,camera=c.modelPanel(panel,q=True,camera=True))
    camera,shape=c.camera()
    state.update(test_camera=camera,test_shape=shape)
    c.setAttr(shape+'.orthographic',True);c.setAttr(shape+'.orthographicWidth',12)
    c.lookThru(panel,camera)
    select('arm_L')
    c.autoKeyframe(state=True)
    return {'ready':True}


def select(key,role=None):
    p=state['rig']['parts'][key];role=role or ('middle_fk' if key.startswith('arm') else 'foot')
    ctrl=p['live_controls'][role];pos=c.xform(ctrl,q=True,ws=True,t=True)
    c.xform(state['test_camera'],ws=True,t=(pos[0],pos[1],pos[2]+18))
    c.select(ctrl);c.setToolTo('RotateSuperContext')
    c.manipRotateContext('Rotate',e=True,mode=0,activeHandle=2 if key.startswith('arm') else 0)
    c.refresh(f=True);state.update(part=p,control=ctrl,key=key,role=role)


def matrices():
    return {n:c.xform(n,q=True,ws=True,m=True) for n in state['part']['joints']}


def drag():
    import maya.api.OpenMayaUI as ui
    import maya.api.OpenMaya as om
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
    point=c.xform(state['control'],q=True,ws=True,t=True)
    x,y=view.worldToView(om.MPoint(point))[:2];y=widget.height()-y
    start=QtCore.QPoint(x+100,y);end=QtCore.QPoint(x+100,y-25)
    state['before_drag']=matrices()
    handle_before=c.xform(state['control'],q=True,ws=True,t=True)
    other=state['part']['live_controls'].get('toe' if state['role']=='ball' else 'heel' if state['role']=='toe_end' else 'toe_end')
    other_before=c.xform(other,q=True,ws=True,t=True) if other else None
    QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start)
    fired=bool(live_edit._gesture)
    QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
        QtCore.QPointF(end),QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,
        QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
    QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
    QtWidgets.QApplication.processEvents()
    state['after_drag']=matrices()
    joint=state['part']['joints'][1 if state['key'].startswith('arm') else 2]
    error=(math.dist(handle_before,c.xform(state['control'],q=True,ws=True,t=True))
           if state['role'] in ('heel','toe_end','ball','toe') else
           math.dist(state['before_drag'][joint][12:15],state['after_drag'][joint][12:15]))
    motion=max(abs(a-b) for n,m in state['before_drag'].items() for a,b in zip(m,state['after_drag'][n]))
    assert fired and not live_edit._gesture
    assert error<1e-5,(state['key'],error)
    assert motion>1e-5
    follow=math.dist(other_before,c.xform(other,q=True,ws=True,t=True)) if other else 0
    if state['role'] in ('heel','toe_end','ball'):assert follow>1e-5
    return {'part':state['key'],'role':state['role'],'native_drag':True,'pivot_error':error,'motion':motion,'other_handle_motion':follow}


def check(which):
    actual=matrices();error=max(abs(a-b) for n,m in state[which].items() for a,b in zip(m,actual[n]))
    assert error<1e-5,error
    return {'state':which,'error':error}


def drag_move():
    """Check free manual-style motion throughout the native drag."""
    import maya.api.OpenMayaUI as ui
    import maya.api.OpenMaya as om
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    select('arm_L','end_fk');c.setToolTo('moveSuperContext')
    c.manipMoveContext('Move',e=True,mode=2,activeHandle=0)
    p=state['part'];ctrl=state['control']
    fixed={p['live_controls'][r]:c.getAttr(p['live_controls'][r]+'.translate')[0] for r in ('middle_fk','end_fk')}
    c.refresh(f=True)
    view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
    point=c.xform(ctrl,q=True,ws=True,t=True)
    x,y=view.worldToView(om.MPoint(point))[:2];y=widget.height()-y
    start=QtCore.QPoint(x+60,y);end=QtCore.QPoint(x+80,y-10)
    state['before_drag']=matrices()
    QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start)
    QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
        QtCore.QPointF(end),QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,
        QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
    QtWidgets.QApplication.processEvents()
    during=math.dist(point,c.xform(ctrl,q=True,ws=True,t=True))
    assert during>1e-5,('No real-time movement before mouse release',during)
    next_end=QtCore.QPoint(x+90,y-10)
    QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
        QtCore.QPointF(next_end),QtCore.QPointF(widget.mapToGlobal(next_end)),QtCore.Qt.NoButton,
        QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
    QtWidgets.QApplication.processEvents()
    during2=math.dist(point,c.xform(ctrl,q=True,ws=True,t=True))
    assert during2>during+1e-5,(during,during2)
    QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,next_end)
    QtWidgets.QApplication.processEvents();state['after_drag']=matrices()
    return dict(real_time_move=during,second_sample_move=during2,free_translation_change=max(abs(a-b) for n,values in fixed.items() for a,b in zip(values,c.getAttr(n+'.translate')[0])))


def scrub():
    time=c.currentTime(q=True)
    c.currentTime(time+1);c.currentTime(time)
    return check('after_drag')


def cleanup():
    global state
    if live_edit._gesture:live_edit.after_drag('cleanup')
    c.lookThru(state['panel'],state['camera']);remove(state['rig'])
    for n in sorted(set(c.ls(long=True))-state['before'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    assert set(c.ls(long=True))==state['before']
    c.currentTime(state['frame']);c.autoKeyframe(state=state['auto']);c.setToolTo(state['tool'])
    c.manipRotateContext('Rotate',e=True,mode=state['mode'],activeHandle=state['handle'])
    c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    state=None
    return True
