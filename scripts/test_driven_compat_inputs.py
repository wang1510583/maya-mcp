"""Exercise arbitrary TR source types, compound connections, locks and rollback."""
import json,importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import maya.cmds as c

def run(out):
    out=Path(out)
    assert Path(c.internalVar(userAppDir=True)).resolve().is_relative_to(out.parent)
    from maya_agent.rigs import integrated,head_neck
    from maya_agent.rigs.integrated import builder,input_transfer
    from maya_agent.rigs.custom_body import targets
    for m in (integrated,head_neck,targets,input_transfer,builder):importlib.reload(m)
    results=[]
    (out/'inputs-progress.json').write_text('[]','utf8')
    for kind in ('constraint','expression','animationLayer','drivenKey','compound','locked','mesh','camera','joint','parentScale','opm'):
        c.file(new=True,force=True)
        driver=c.createNode('transform',name='originalDriver')
        parent=c.createNode('transform',name='originalParent')
        if kind=='mesh':node=c.polyCube(name='target')[0]
        elif kind=='camera':node=c.camera(name='target')[0]
        else:node=c.createNode('joint' if kind=='joint' else 'transform',name='target')
        node=c.parent(node,parent,relative=True)[0];node=c.ls(node,long=True)[0]
        c.setAttr(node+'.ty',4)
        if kind=='constraint':c.parentConstraint(driver,node,maintainOffset=True)
        elif kind=='expression':c.expression(s='target.translateX = frame * 0.1; target.rotateZ = frame * 2;',name='originalExpression')
        elif kind=='animationLayer':
            c.select(node);layer=c.animLayer('originalLayer',addSelectedObjects=True)
            for t,v in [(1,0),(3,8),(5,-2)]:c.setKeyframe(node,at='rotateZ',time=t,value=v,animLayer=layer)
        elif kind=='drivenKey':
            for v in (0,10):
                c.setAttr(driver+'.ty',v);c.setAttr(node+'.rx',v*2);c.setDrivenKeyframe(node+'.rx',currentDriver=driver+'.ty')
        elif kind=='compound':c.connectAttr(driver+'.translate',node+'.translate')
        elif kind=='parentScale':
            for a in 'XYZ':c.connectAttr(driver+'.scale'+a,parent+'.scale'+a)
            for t,v in [(1,1),(3,1.2),(5,.9)]:
                for a in 'XYZ':c.setKeyframe(driver,at='scale'+a,time=t,value=v,itt='linear',ott='linear')
        elif kind=='opm':c.connectAttr(driver+'.matrix',node+'.offsetParentMatrix')
        if kind=='joint':c.setAttr(node+'.jointOrient',11,-17,8)
        if kind=='locked':
            for a in targets.CHANNELS:c.setAttr(node+'.'+a,lock=True)
        for t,v in [(1,0),(3,1),(5,-.5)]:
            for a in ('translateX','rotateY'):c.setKeyframe(driver,at=a,time=t,value=v,itt='linear',ott='linear')
        c.currentTime(1);expected={}
        for t in range(1,6):
            c.currentTime(t);expected[t]=c.xform(node,q=True,ws=True,m=True)
        c.currentTime(1)
        before_nodes=set(c.ls());before_edges={a:c.connectionInfo(node+'.'+a,sfd=True) for a in ('translate','rotate')+targets.CHANNELS}
        flags={a:c.getAttr(node+'.'+a,lock=True) for a in ('translate','rotate')+targets.CHANNELS}
        config={'head':dict(targets=[node],compatible_inputs=True,start_frame=1,end_frame=5,space_head=True)}
        # Raise after the handoff, when the first final source constraint is made.
        original=c.parentConstraint
        def fail(*a,**kw):
            if kw.get('name','').startswith('rollbackTest:head_target'):raise RuntimeError('injected build failure')
            return original(*a,**kw)
        try:
            with patch.object(c,'parentConstraint',fail):builder.build(config,namespace='rollbackTest',create_master=False)
        except RuntimeError as exc:assert str(exc)=='injected build failure',exc
        else:raise AssertionError('Expected injected failure')
        assert set(c.ls())==before_nodes,'rollback changed nodes: '+kind
        assert all(c.connectionInfo(node+'.'+a,sfd=True)==src for a,src in before_edges.items()),'rollback changed connections'
        assert all(c.getAttr(node+'.'+a,lock=True)==value for a,value in flags.items()),'rollback changed locks'
        for t in range(1,6):
            c.currentTime(t);assert max(abs(a-b) for a,b in zip(c.xform(node,q=True,ws=True,m=True),expected[t]))<1e-7
        c.currentTime(1)
        rig=builder.build(config,namespace='successTest',zero_controls=True)
        assert all(c.getAttr(node+'.'+a,lock=True)==value for a,value in flags.items()),'build changed locks'
        assert all(c.objExists(n) for n in before_nodes),'source node lost'
        def diagnostic():
            return {n:{a:dict(value=c.getAttr(n+'.'+a),input=c.connectionInfo(n+'.'+a,sfd=True)) for a in targets.CHANNELS+('offsetParentMatrix',)} for n in c.ls('successTest*:*',type='transform') or []}
        before_redo=diagnostic()
        c.undo()
        assert all(c.connectionInfo(node+'.'+a,sfd=True)==src for a,src in before_edges.items()),'undo changed connections'
        assert all(c.getAttr(node+'.'+a,lock=True)==value for a,value in flags.items()),'undo changed locks'
        assert max(abs(a-b) for a,b in zip(c.xform(node,q=True,ws=True,m=True),expected[1]))<1e-7
        c.redo()
        c.dgdirty(allPlugs=True);c.refresh(force=True)
        assert c.objExists(rig['root'])
        assert all(c.getAttr(node+'.'+a,lock=True)==value for a,value in flags.items()),'redo changed locks'
        redo_matrix=c.xform(node,q=True,ws=True,m=True)
        if max(abs(a-b) for a,b in zip(redo_matrix,expected[1]))>=1e-4:
            after_redo=diagnostic()
            diffs={n:{a:[v,after_redo.get(n,{}).get(a)] for a,v in attrs.items() if v!=after_redo.get(n,{}).get(a)} for n,attrs in before_redo.items()}
            (out/'redo-diff.json').write_text(json.dumps(dict(kind=kind,time=c.currentTime(q=True),diff={n:v for n,v in diffs.items() if v}),indent=2),'utf8')
        assert max(abs(a-b) for a,b in zip(redo_matrix,expected[1]))<1e-4,(kind,'redo',redo_matrix,expected[1])
        results.append(dict(kind=kind,error=rig['max_world_error'],rollback=True))
        (out/'inputs-progress.json').write_text(json.dumps(results,indent=2),'utf8')
    report=dict(passed=True,cases=results)
    (out/'inputs-report.json').write_text(json.dumps(report,indent=2),'utf8');return report
