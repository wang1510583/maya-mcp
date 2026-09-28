"""Live layer editing on disposable rigs; preserve base curves and layer stacks."""
import uuid
import maya.cmds as c
from maya_agent.rigs import live_edit,live_alignment
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove

state=None


def pose():
    return {n:c.xform(n,q=True,ws=True,m=True) for p in state['rig']['parts'].values() for n in p['joints']}


def error(a,b):
    return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))


def setup():
    global state
    import maya.api.OpenMayaUI as ui
    state=dict(nodes=set(c.ls(long=True)),frame=c.currentTime(q=True),selection=c.ls(sl=True,long=True) or [],
               tool=c.currentCtx(),auto=c.autoKeyframe(q=True,state=True),layers={},rig=None,temporary_layers=[])
    for layer in c.ls(type='animLayer') or []:
        state['layers'][layer]={a:c.animLayer(layer,q=True,**{a:True}) for a in ('selected','preferred')}
        c.animLayer(layer,e=True,selected=False,preferred=False)
    c.autoKeyframe(state=False)
    prefix='_layerLive_'+uuid.uuid4().hex[:6];_,parts=fixture(prefix,True)
    c.currentTime(3)
    state['rig']=build({k:v for k,v in parts.items() if k.startswith(('arm','leg'))},namespace=prefix)
    state['data']={k:live_alignment.enable(p,k.split('_')[0]) for k,p in state['rig']['parts'].items()}
    state['plugs']=list(dict.fromkeys(e['proxy'] for d in state['data'].values() for e in d['entries']))
    # Include native companion controls so all base animation is audited.
    for p in state['rig']['parts'].values():
        for n in p['controls'].values():
            state['plugs'].extend(n+'.'+a for a in live_edit.TR if c.objExists(n+'.'+a) and not c.connectionInfo(n+'.'+a,sfd=True))
    state['plugs']=list(dict.fromkeys(p for p in state['plugs'] if not c.getAttr(p,lock=True)))
    state['snapshot']=live_edit._snapshot(state['plugs'])
    state['base_pose']=pose()
    panel=next(p for p in c.getPanel(type='modelPanel') if int(ui.M3dView.getM3dViewFromModelPanel(p).widget())==int(ui.M3dView.active3dView().widget()))
    state.update(panel=panel,camera=c.modelPanel(panel,q=True,camera=True))
    camera,shape=c.camera();state['test_camera']=camera
    c.setAttr(shape+'.orthographic',True);c.setAttr(shape+'.orthographicWidth',16);c.lookThru(panel,camera)
    state['contexts']={name:{f:cmd(name,q=True,**{f:True}) for f in ('mode','activeHandle')}
                       for name,cmd in [('Move',c.manipMoveContext),('Rotate',c.manipRotateContext)]}
    return dict(ready=True)


def add_layer(key,role,override=False,weight=1.0,quaternion=False):
    for layer in c.ls(type='animLayer') or []:c.animLayer(layer,e=True,selected=False,preferred=False)
    layer=c.animLayer('_liveLayerTest',override=override);state['temporary_layers'].append(layer)
    ctrl=state['data'][key]['controls'][role]
    c.animLayer(layer,e=True,attribute=[ctrl+'.'+a for a in live_edit.TR if not c.getAttr(ctrl+'.'+a,lock=True)])
    c.animLayer(layer,e=True,weight=weight,selected=True,preferred=True)
    if quaternion:c.setAttr(layer+'.rotationAccumulationMode',0)
    state.update(layer=layer,key=key,role=role,control=ctrl)
    return layer


def drag(mode='rotate',noop=False,native=False):
    ctrl=state['control'];c.select(ctrl);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
    c.autoKeyframe(state=True);before=pose();state['before_drag']=before
    if native:
        import maya.api.OpenMayaUI as ui
        import maya.api.OpenMaya as om
        from PySide2 import QtCore,QtGui,QtWidgets,QtTest
        from shiboken2 import wrapInstance
        point=c.xform(ctrl,q=True,ws=True,t=True);c.xform(state['test_camera'],ws=True,t=(point[0],point[1],point[2]+40))
        command=c.manipMoveContext if mode=='move' else c.manipRotateContext
        command('Move' if mode=='move' else 'Rotate',e=True,mode=2 if mode=='move' else 0,activeHandle=0 if mode=='move' else 2)
        c.refresh(f=True);view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
        x,y=view.worldToView(om.MPoint(point))[:2];y=widget.height()-y
        start=QtCore.QPoint(x+70,y);end=start;down=False
        try:
            QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start);down=True
            assert live_edit._gesture,'Native layer gesture did not begin'
            press=error(before,pose())
            for i in (() if noop else (1,2,3)):
                end=QtCore.QPoint(x+70+i*7,y-i*4)
                QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,QtCore.QPointF(end),
                    QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
                QtWidgets.QApplication.processEvents()
            during=pose()
            QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end);down=False
            QtWidgets.QApplication.processEvents()
        finally:
            if down:QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
            QtWidgets.QApplication.processEvents()
            if live_edit._gesture:live_edit.after_drag('layer-test-cleanup')
    else:
        live_edit.before_drag('layer-regression');press=error(before,pose())
        if not noop:
            if mode=='move':c.move(.2,.3,-.15,ctrl,r=True,ws=True)
            else:c.rotate(4,-3,7,ctrl,r=True,os=True)
        live_edit.update_drag();during=pose();live_edit.after_drag('layer-regression')
    after=pose();state['after_drag']=after
    release=error(during,after);motion=error(before,after)
    assert max(press,release)<1e-5,('boundary',state['key'],state['role'],press,release)
    if noop:assert motion<1e-5,motion
    else:assert motion>1e-5,motion
    c.currentTime(4);c.currentTime(3);scrub=error(after,pose())
    assert scrub<1e-5,('scrub',state['key'],state['role'],scrub)
    base=state['snapshot'][1]
    actual=live_edit._snapshot(state['plugs'])[1]
    assert all(actual[n]==data for n,data in base.items()),'Base curves modified'
    c.animLayer(state['layer'],e=True,mute=True);muted=error(state['base_pose'],pose());c.animLayer(state['layer'],e=True,mute=False)
    assert muted<1e-5,('muted',state['key'],state['role'],muted)
    return dict(part=state['key'],role=state['role'],mode=mode,noop=noop,press=press,release=release,scrub=scrub,muted=muted)


def clear_layer():
    c.autoKeyframe(state=False)
    for layer in reversed(state['temporary_layers']):
        if c.objExists(layer):c.delete(layer)
    state['temporary_layers']=[]
    c.currentTime(4);c.currentTime(3);live_edit._restore(state['snapshot'])


def verify():
    setup();report=[]
    try:
        for side in ('L','R'):
            for kind,role,mode in [('arm','shoulder_fk','rotate'),('arm','middle_fk','move'),('arm','end_fk','rotate'),
                                   ('leg','foot','move'),('leg','heel','rotate'),('leg','toe_end','rotate'),('leg','ball','rotate')]:
                for override,weight,quaternion in [(False,1,False),(False,.5,True),(True,.5,False)]:
                    add_layer(kind+'_'+side,role,override,weight,quaternion)
                    report.append(drag(mode,True));report.append(drag(mode))
                    clear_layer()
        return report
    finally:cleanup()


def verify_stack():
    setup()
    try:
        add_layer('arm_R','middle_fk',weight=.6,quaternion=True)
        lower=drag('rotate')
        state['snapshot']=live_edit._snapshot(state['plugs']);state['base_pose']=pose()
        add_layer('arm_R','middle_fk',override=True,weight=.7)
        upper=drag('rotate',native=True)
        return dict(lower=lower,upper=upper,lower_curves_unchanged=True)
    finally:cleanup()


def verify_manual_key():
    setup()
    try:
        layer=add_layer('arm_R','middle_fk');ctrl=state['control'];before=pose()
        curves=live_edit._snapshot(state['plugs'])[1]
        c.autoKeyframe(state=False);c.select(ctrl);c.setToolTo('moveSuperContext')
        live_edit.before_drag('manual-key');c.move(.2,.1,-.15,ctrl,r=True,ws=True)
        live_edit.update_drag();during=pose();live_edit.after_drag('manual-key');final=pose()
        assert error(during,final)<1e-5
        after=live_edit._snapshot(state['plugs'])[1]
        assert all(after[n]==v for n,v in curves.items())
        assert not c.animLayer(layer,q=True,animCurves=True),'Auto Key off added keys'
        nodes=list({p.rsplit('.',1)[0] for p in c.animLayer(layer,q=True,attribute=True) or []})
        c.setKeyframe(nodes,at=list(live_edit.TR),animLayer=layer)
        c.currentTime(4);c.currentTime(3);scrub=error(final,pose());assert scrub<1e-5,scrub
        c.animLayer(layer,e=True,mute=True);muted=error(before,pose());assert muted<1e-5,muted
        return dict(auto_off_no_keys=True,manual_key_scrub=scrub,muted=muted)
    finally:cleanup()


def cleanup():
    global state
    if live_edit._gesture:live_edit.after_drag('cleanup')
    c.autoKeyframe(state=False)
    for layer in reversed(state['temporary_layers']):
        if c.objExists(layer):c.delete(layer)
    if state['rig']:remove(state['rig'])
    if state.get('camera'):c.lookThru(state['panel'],state['camera'])
    for n in sorted(set(c.ls(long=True))-state['nodes'],key=lambda n:n.count('|'),reverse=True):
        if c.objExists(n):c.delete(n)
    for layer,flags in state['layers'].items():c.animLayer(layer,e=True,**flags)
    for name,cmd in [('Move',c.manipMoveContext),('Rotate',c.manipRotateContext)]:
        if state.get('contexts'):cmd(name,e=True,**state['contexts'][name])
    c.currentTime(state['frame']);c.setToolTo(state['tool']);c.autoKeyframe(state=state['auto'])
    c.select(state['selection'],r=True) if state['selection'] else c.select(cl=True)
    state=None
