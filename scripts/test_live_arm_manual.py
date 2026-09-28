"""Compare live gestures with Maya's native input edits after manual alignment."""
import math,uuid
import maya.cmds as c
from maya_agent.rigs import live_alignment,live_edit
from maya_agent.rigs.integrated import build
from scripts.test_integrated_rig_live import fixture,remove


def compare(root):
    import json
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    _,dest,frames,zero,restore=live_edit._plan(root)
    plugs=[dest.get(n+'.'+a,n+'.'+a) for n in dict.fromkeys([n for n,m in frames+restore]+zero) for a in live_edit.TR]
    saved=live_edit._snapshot(plugs);sel=c.ls(sl=True,long=True) or [];tool=c.currentCtx();auto=c.autoKeyframe(q=True,state=True)
    nodes=list(data['targets'].values())+list(data['controls'].values())
    def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def error(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))
    initial=pose();report=[]
    try:
        c.autoKeyframe(state=False)
        for role in ('middle_fk','end_fk','shoulder_fk'):
            proxy=data['controls'][role];source=data['inputs'][role]
            for mode in ('move','rotate'):
                if mode=='move' and role=='shoulder_fk':continue
                for axis in range(3):
                    delta=[0.,0.,0.];delta[axis]=.4 if mode=='move' else 11.
                    live_edit._restore(saved)
                    live_edit.prepare(root,wrist_only=(role=='end_fk' and mode=='rotate'))
                    # Manipulate the original input with Maya's own commands,
                    # bypassing the live runtime to obtain the reference result.
                    edges=[]
                    try:
                        for attr in live_edit.TR:
                            src=proxy+'.'+attr;dst=source+'.'+attr
                            if c.isConnected(src,dst):
                                value=c.getAttr(dst);c.disconnectAttr(src,dst);c.setAttr(dst,value);edges.append((src,dst))
                        if mode=='move':c.move(*delta,source,r=True,ws=True)
                        else:c.rotate(*delta,source,r=True,os=True)
                        expected=pose()
                    finally:
                        for src,dst in edges:c.connectAttr(src,dst,force=True)
                    live_edit._restore(saved)
                    c.select(proxy);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
                    before=pose();live_edit.before_drag('manual-regression');press=error(before,pose())
                    if mode=='move':c.move(*delta,proxy,r=True,ws=True)
                    else:c.rotate(*delta,proxy,r=True,os=True)
                    live_edit.update_drag();during=pose();live_edit.after_drag('manual-regression')
                    report.append(dict(role=role,mode=mode,axis=axis,manual_error=error(expected,pose()),press=press,release=error(during,pose())))
                    assert max(report[-1][k] for k in ('manual_error','press','release'))<1e-5,report[-1]
        return report
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        live_edit._restore(saved);c.autoKeyframe(state=auto);c.setToolTo(tool)
        c.select(sel,r=True) if sel else c.select(cl=True)
        assert error(initial,pose())<1e-5


def verify(native=False,animated=False):
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    rig=None;camera=None;panel=None;old_camera=None;frame=c.currentTime(q=True)
    try:
        c.autoKeyframe(state=False);prefix='_manualArm_'+uuid.uuid4().hex[:6]
        _,parts=fixture(prefix,animated)
        if animated:c.currentTime(3)
        rig=build({k:v for k,v in parts.items() if k.startswith('arm')},namespace=prefix)
        if native:
            import maya.api.OpenMayaUI as ui
            panel=next(p for p in c.getPanel(type='modelPanel') if int(ui.M3dView.getM3dViewFromModelPanel(p).widget())==int(ui.M3dView.active3dView().widget()))
            old_camera=c.modelPanel(panel,q=True,camera=True);camera,shape=c.camera()
            c.setAttr(shape+'.orthographic',True);c.setAttr(shape+'.orthographicWidth',12);c.lookThru(panel,camera)
        results={}
        for key,part in rig['parts'].items():
            data=live_alignment.enable(part,'arm')
            c.setAttr(data['controls']['middle_fk']+'.rotate',17,-13,-70)
            results[key]=compare(part['root'])
            if native:
                for role in ('middle_fk','end_fk'):
                    pos=c.xform(data['controls'][role],q=True,ws=True,t=True)
                    c.xform(camera,ws=True,t=(pos[0],pos[1],pos[2]+18))
                    for mode in ('move','rotate'):
                        results[key].append(native_compare(part['root'],role,mode))
                from scripts import test_live_arm_boundaries as boundaries,test_live_arm_native_boundaries as nb
                audit=boundaries.inspect(part['root'],True)
                assert audit['restore']<1e-5,audit
                assert max(max(r['press'],r['release']) for r in audit['results'])<1e-5,audit
                results[key].append(dict(boundaries=audit))
                for mode in ('move','rotate'):
                    audit=nb.inspect(part['root'],'middle_fk',mode,True)
                    assert max(audit[k] for k in ('press','native_release','commit','restore'))<1e-5,audit
                    results[key].append(dict(native_autokey=audit))
        return results
    finally:
        if panel and old_camera:c.lookThru(panel,old_camera)
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.currentTime(frame);c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(cl=True)


def study_alignment():
    """Run the installed Easy Rig on a disposable arm and report its channels."""
    import maya.mel as mel
    before=set(c.ls(long=True));sel=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    rig=None
    try:
        c.autoKeyframe(state=False);prefix='_studyManual_'+uuid.uuid4().hex[:6]
        _,parts=fixture(prefix,False)
        rig=build({'arm_L':parts['arm_L']},namespace=prefix)
        p=rig['parts']['arm_L'];ctrl=p['controls']
        def channels():return {r:{a:c.getAttr(ctrl[r]+'.'+a)[0] for a in ('translate','rotate')} for r in ('shoulder_fk','middle_fk','end_fk')}
        initial=channels()
        c.move(0,1,.7,ctrl['middle_fk'],r=True,ws=True)
        c.move(-.8,.5,1,ctrl['end_fk'],r=True,ws=True)
        moved=channels();pose={n:c.xform(n,q=True,ws=True,m=True) for n in p['joints']}
        snapshot=live_edit._snapshot([n+'.'+a for n in ctrl.values() for a in live_edit.TR if c.objExists(n+'.'+a)])
        c.select(ctrl['end_fk']);mel.eval('kurok_recalculate_system(0);')
        aligned=channels()
        error=max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        # Reset only the disposable rig; compare our alignment to the actual MEL.
        c.cutKey(list(ctrl.values()),clear=True);live_edit._restore(snapshot)
        data=live_alignment.enable(p,'arm');live_edit.prepare(p['root'])
        ours=channels()
        matching=max(abs(x-y) for r in ours for a in ours[r] for x,y in zip(ours[r][a],aligned[r][a]))
        return dict(initial=initial,moved=moved,manually_aligned=aligned,pose_error=error,our_alignment_error=matching)
    finally:
        if rig:remove(rig)
        for n in sorted(set(c.ls(long=True))-before,key=lambda n:n.count('|'),reverse=True):
            if c.objExists(n):c.delete(n)
        c.autoKeyframe(state=auto);c.select(sel,r=True) if sel else c.select(cl=True)


def native_compare(root,role='middle_fk',mode='move',axis=0):
    """Compare actual multi-sample Qt drags with native, manually aligned input."""
    import json
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaUI as ui
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    data=json.loads(c.getAttr(root+'.liveAlignmentData'));proxy=data['controls'][role];source=data['inputs'][role]
    _,dest,frames,zero,restore=live_edit._plan(root)
    saved=live_edit._snapshot([dest.get(n+'.'+a,n+'.'+a) for n in dict.fromkeys([n for n,m in frames+restore]+zero) for a in live_edit.TR])
    selected=c.ls(sl=True,long=True) or [];tool=c.currentCtx();auto=c.autoKeyframe(q=True,state=True)
    command=c.manipMoveContext if mode=='move' else c.manipRotateContext;context='Move' if mode=='move' else 'Rotate'
    options=dict(mode=command(context,q=True,mode=True),activeHandle=command(context,q=True,activeHandle=True))
    nodes=list(data['targets'].values())
    traces=[]
    def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def drag(node):
        c.select(node);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
        command(context,e=True,mode=2 if mode=='move' else 0,activeHandle=axis);c.refresh(f=True)
        view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
        x,y=view.worldToView(om.MPoint(c.xform(node,q=True,ws=True,t=True)))[:2];y=widget.height()-y
        start=QtCore.QPoint(x+60,y);end=start;down=False;poses=[pose()]
        try:
            QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start);down=True;poses.append(pose())
            for i in (1,2,3,2,1,0):
                end=QtCore.QPoint(x+60+i*5,y-i*3)
                QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,QtCore.QPointF(end),
                    QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
                QtWidgets.QApplication.processEvents();poses.append(pose())
                traces.append(dict(node=node,step=i,native=c.getAttr(node+'.translate')[0],source=c.xform(source,q=True,ws=True,t=True),visible=c.xform(proxy,q=True,ws=True,t=True)))
            QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end);down=False
            QtWidgets.QApplication.processEvents();poses.append(pose())
        finally:
            if down:QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
            QtWidgets.QApplication.processEvents()
            if live_edit._gesture:live_edit.after_drag('cleanup')
        return poses
    edges=[]
    try:
        c.autoKeyframe(state=False);live_edit.prepare(root,wrist_only=(role=='end_fk' and mode=='rotate'))
        for attr in live_edit.TR:
            src=proxy+'.'+attr;dst=source+'.'+attr
            if c.isConnected(src,dst):
                value=c.getAttr(dst);c.disconnectAttr(src,dst);c.setAttr(dst,value);edges.append((src,dst))
        expected=drag(source)
        for src,dst in edges:c.connectAttr(src,dst,force=True)
        edges=[];live_edit._restore(saved)
        actual=drag(proxy)
        errors=[max(abs(a-b) for n,m in e.items() for a,b in zip(m,v[n])) for e,v in zip(expected,actual)]
        motion=max(abs(a-b) for n,m in expected[0].items() for a,b in zip(m,expected[4][n]))
        assert motion>1e-5,('test gesture did not move',role,mode,axis)
        globals()['last_trace']=traces
        assert max(errors)<1e-5,(role,mode,axis,errors)
        return dict(role=role,mode=mode,axis=axis,manual_errors=errors,motion=motion)
    finally:
        for src,dst in edges:c.connectAttr(src,dst,force=True)
        live_edit._restore(saved);command(context,e=True,**options);c.setToolTo(tool)
        c.select(selected,r=True) if selected else c.select(cl=True);c.autoKeyframe(state=auto)
