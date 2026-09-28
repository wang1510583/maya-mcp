"""Disposable native multi-selection gestures, release, animation and undo QA."""
import uuid
import maya.cmds as c
from maya_agent.rigs import live_alignment,live_edit,live_arm_manual
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove

state=None


def pose():
    return {n:c.xform(n,q=True,ws=True,m=True) for n in state['nodes']}


def error(a,b):
    return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def setup():
    global state
    import maya.api.OpenMayaUI as ui
    state=dict(before=set(c.ls(long=True)),selection=c.ls(sl=True,long=True) or [],
               frame=c.currentTime(q=True),auto=c.autoKeyframe(q=True,state=True),tool=c.currentCtx())
    for context,command in (('Move',c.manipMoveContext),('Rotate',c.manipRotateContext)):
        state[context]={f:command(context,q=True,**{f:True}) for f in ('mode','activeHandle')}
    c.autoKeyframe(state=False)
    prefix='_multiArm_'+uuid.uuid4().hex[:6]
    _,parts=fixture(prefix,False)
    state['rig']=build({k:v for k,v in parts.items() if k.startswith('arm')},namespace=prefix)
    state['data']={k:live_alignment.enable(p,'arm') for k,p in state['rig']['parts'].items()}
    state['nodes']=[n for p in state['rig']['parts'].values() for n in p['joints']]
    state['plain']=c.createNode('transform',name=prefix+'_ordinaryControl')
    state['nodes'].append(state['plain'])
    for d in state['data'].values():
        for n in d['controls'].values():c.setKeyframe(n,at=list(live_edit.TR),time=0)
    c.setKeyframe(state['plain'],at=list(live_edit.TR),time=0)
    panel=next(p for p in c.getPanel(type='modelPanel') if int(ui.M3dView.getM3dViewFromModelPanel(p).widget())==int(ui.M3dView.active3dView().widget()))
    state.update(panel=panel,camera=c.modelPanel(panel,q=True,camera=True))
    camera,shape=c.camera();state['test_camera']=camera
    c.setAttr(shape+'.orthographic',True);c.setAttr(shape+'.orthographicWidth',30)
    c.lookThru(panel,camera);c.currentTime(5);c.autoKeyframe(state=True)
    return dict(ready=True)


def controls(case):
    d=state['data'];roles=('shoulder_fk','middle_fk','end_fk')
    cases={
        'elbow_wrist':[('arm_L',r) for r in roles[1:]],
        'shoulder_elbow':[('arm_L',r) for r in roles[:2]],
        'whole_left':[('arm_L',r) for r in roles],
        'whole_right':[('arm_R',r) for r in roles],
        'both_wrists':[(k,'end_fk') for k in d],
        'both_arms':[(k,r) for k in d for r in roles],
        'mixed':[('arm_L','end_fk')],
    }
    result=[d[k]['controls'][r] for k,r in cases[case]]
    if case=='mixed':result.append(state['plain'])
    return result


def drag(case='elbow_wrist',mode='rotate',noop=False):
    import maya.api.OpenMayaUI as ui
    import maya.api.OpenMaya as om
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    selected=controls(case);c.select(list(reversed(selected)))
    c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
    command=c.manipMoveContext if mode=='move' else c.manipRotateContext
    command('Move' if mode=='move' else 'Rotate',e=True,mode=2 if mode=='move' else 0,activeHandle=0 if mode=='move' else 2)
    points=[c.xform(n,q=True,ws=True,t=True) for n in selected]
    center=[sum(p[i] for p in points)/len(points) for i in range(3)]
    c.xform(state['test_camera'],ws=True,t=(center[0],center[1],center[2]+50));c.refresh(f=True)
    view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
    x,y=view.worldToView(om.MPoint(center))[:2];y=widget.height()-y
    start=QtCore.QPoint(x+70,y);end=start;down=False
    before=pose();state['before_drag']=before
    original_update=live_arm_manual.update;solve_errors=[]
    def audited_update(entry,*args,**kwargs):
        # During native input the proxy is a fixed independent world target.
        # Verify parent-first solving does not apply a parent delta twice.
        frozen=('children' not in entry and not entry['finished'] and
                not c.isConnected(entry['display_edge'],entry['proxy']+'.offsetParentMatrix'))
        desired=entry['input_basis']*om.MMatrix(c.xform(entry['proxy'],q=True,ws=True,m=True)) if frozen else None
        result=original_update(entry,*args,**kwargs)
        if desired is not None:
            actual=live_edit._frame(entry['source'])
            indices=range(12) if entry['role']=='shoulder_fk' else range(16)
            solve_errors.append(max(abs(actual[i]-desired[i]) for i in indices))
        return result
    live_arm_manual.update=audited_update
    try:
        QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start);down=True
        assert live_edit._gesture,'Native gesture did not begin'
        press=error(before,pose());assert press<1e-5,('press',case,mode,press)
        for i in (() if noop else (1,2,3)):
            end=QtCore.QPoint(x+70+i*8,y-i*5)
            QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,QtCore.QPointF(end),
                QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
            QtWidgets.QApplication.processEvents()
        during=pose()
        QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end);down=False
        QtWidgets.QApplication.processEvents()
        final=pose();state['after_drag']=final
        release=error(during,final);motion=error(before,final)
        assert not live_edit._gesture and not live_arm_manual._refresh_holds,'Unfinished gesture/refresh'
        assert release<1e-5,('release',case,mode,release)
        assert max(solve_errors or [0])<1e-5,('world targets',case,mode,solve_errors)
        assert (motion<1e-5 if noop else motion>1e-5),('motion',case,mode,motion)
        for d in state['data'].values():
            for e in d['entries']:assert c.isConnected(e['proxy'],e['source']),e
        if not noop:
            c.currentTime(0);c.currentTime(5)
            scrub=error(final,pose());assert scrub<1e-5,('scrub',case,mode,scrub)
        else:scrub=0
        if case=='mixed' and not noop:
            assert 5 in (c.keyframe(state['plain'],q=True,tc=True) or []),'Ordinary control lost AutoKey'
        return dict(case=case,mode=mode,noop=noop,press=press,release=release,motion=motion,scrub=scrub,solve=max(solve_errors or [0]))
    finally:
        if down:QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
        QtWidgets.QApplication.processEvents()
        if live_edit._gesture:live_edit.after_drag('test-cleanup')
        live_arm_manual.update=original_update


def check(which):
    drift=error(state[which],pose());assert drift<1e-5,(which,drift)
    return dict(state=which,error=drift)


def verify():
    setup();reports=[]
    try:
        for case in ('elbow_wrist','shoulder_elbow','whole_left','whole_right','both_wrists','both_arms','mixed'):
            for mode in ('move','rotate'):
                reports.append(drag(case,mode,True))
                reports.append(drag(case,mode))
        return reports
    finally:cleanup()


def cleanup():
    global state
    if live_edit._gesture:live_edit.after_drag('test-cleanup')
    c.autoKeyframe(state=False)
    if state.get('camera'):c.lookThru(state['panel'],state['camera'])
    if state.get('rig'):remove(state['rig'])
    for n in sorted(set(c.ls(long=True))-state['before'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    c.currentTime(state['frame']);c.setToolTo(state['tool'])
    for context,command in (('Move',c.manipMoveContext),('Rotate',c.manipRotateContext)):
        command(context,e=True,**state[context])
    c.autoKeyframe(state=state['auto'])
    c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    state=None
