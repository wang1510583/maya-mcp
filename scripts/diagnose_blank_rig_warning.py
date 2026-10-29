"""Reproduce current panel inputs on a disposable skeleton copy only."""
import json
import traceback
import uuid
from pathlib import Path
import maya.cmds as c


def run():
    from maya_agent.rigs.integrated import ui, build
    before = set(c.ls(uuid=True))
    selection = c.ls(sl=True,long=True) or []
    frame = c.currentTime(q=True); modified = c.file(q=True,modified=True)
    auto = c.autoKeyframe(q=True,state=True)
    config = {k:dict(row,targets=ui.targets(k)) for k,row in ui._state.items() if row['uuids']}
    roots = {n.split('|')[1] for row in config.values() for n in row['targets']}
    if len(roots) != 1:
        raise ValueError('Diagnostic expects one skeleton root')
    original_root = '|'+next(iter(roots))
    originals = c.listRelatives(original_root,allDescendents=True,fullPath=True) or []
    matrices = {n:c.xform(n,q=True,ws=True,m=True) for n in originals if c.nodeType(n) in ('joint','transform')}
    prefix = '_blankWarning_'+uuid.uuid4().hex[:8]
    Path(__file__).resolve().parents[1].joinpath('outputs','blank-rig-baseline.json').write_text(json.dumps(dict(nodes=sorted(before),matrices=matrices)),encoding='utf-8')
    report = {'parts':{k:len(v['targets']) for k,v in config.items()},'prefix':prefix}
    c.autoKeyframe(state=False)
    try:
        c.namespace(addNamespace=prefix)
        mapping = {}
        paths = {original_root}
        for row in config.values():
            for n in row['targets']:
                tokens=n.split('|')[1:]
                paths.update('|'+ '|'.join(tokens[:i]) for i in range(1,len(tokens)+1))
        for n in sorted(paths,key=lambda p:p.count('|')):
            parent=n.rsplit('|',1)[0]
            kwargs=dict(parent=mapping[parent]) if parent in mapping else {}
            new=c.createNode(c.nodeType(n),name=prefix+':sample_'+n.rsplit('|',1)[-1],**kwargs)
            mapping[n]=c.ls(new,long=True)[0]
            for attr in ('rotateOrder','inheritsTransform','segmentScaleCompensate','jointOrient','rotateAxis','rotatePivot','rotatePivotTranslate','scalePivot','scalePivotTranslate','translate','rotate','scale','offsetParentMatrix'):
                if not c.objExists(n+'.'+attr):continue
                value=c.getAttr(n+'.'+attr)
                if attr=='offsetParentMatrix':c.setAttr(new+'.'+attr,*value,type='matrix')
                elif isinstance(value,list):c.setAttr(new+'.'+attr,*value[0])
                else:c.setAttr(new+'.'+attr,value)
            if c.objExists(n+'.inverseScale'):
                edge=c.connectionInfo(n+'.inverseScale',sfd=True)
                if edge and parent in mapping and edge.rsplit('.',1)[-1]=='scale':c.connectAttr(mapping[parent]+'.scale',new+'.inverseScale',f=True)
        for key,row in config.items():
            row['targets'] = [mapping[n] for n in row['targets']]
            row['copy_animation'] = ui._global_options['copy_animation']
        result = build(config, namespace=prefix, zero_controls=True,pose_tolerance=ui._instance.pose_tolerance.value())
        report.update(passed=True,error=result['max_world_error'])
    except Exception as exc:
        report.update(passed=False,exception=repr(exc),traceback=traceback.format_exc())
    finally:
        Path(__file__).resolve().parents[1].joinpath('outputs','blank-rig-warning.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        owned = set(c.ls(uuid=True))-before
        for uid in owned:
            found = c.ls(uid,long=True) or []
            if found and prefix+':' in found[0] and c.objectType(found[0],isAType='constraint'):
                c.delete(found[0])
        names = [n for uid in owned for n in (c.ls(uid,long=True) or [])]
        for n in sorted(names,key=lambda x:x.count('|'),reverse=True):
            if c.objExists(n) and prefix in n:c.delete(n)
        for ns in sorted(c.namespaceInfo(listOnlyNamespaces=True,recurse=True) or [],key=len,reverse=True):
            if ns.startswith(prefix) and not c.namespaceInfo(ns,listOnlyDependencyNodes=True):
                c.namespace(removeNamespace=ns)
        c.currentTime(frame);c.autoKeyframe(state=auto)
        c.select(selection,r=True) if selection else c.select(clear=True)
        report['same_nodes'] = set(c.ls(uuid=True))==before
        report['original_pose_error'] = max([abs(a-b) for n,m in matrices.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True))]+[0])
        c.file(modified=modified)
    Path(__file__).resolve().parents[1].joinpath('outputs','blank-rig-warning.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
