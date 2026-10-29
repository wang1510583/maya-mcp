"""Explicit repair of v1 master scale skin connections in the open scene.

Writes a connection/weight backup, never saves or replaces a Maya scene.
"""
import json, re, datetime, hashlib, importlib
from pathlib import Path
import maya.cmds as c
import maya.api.OpenMaya as om


def points(shape):
    selection=om.MSelectionList();selection.add(shape)
    return [tuple(p) for p in om.MFnMesh(selection.getDagPath(0)).getPoints(om.MSpace.kWorld)]


def repair():
    from maya_agent.rigs.integrated import master_scale
    importlib.reload(master_scale)
    roots=[n for n in c.ls(type='transform',long=True) if c.attributeQuery(master_scale.ATTRIBUTE,node=n,exists=True)]
    markers={n+'.'+master_scale.ATTRIBUTE:c.getAttr(n+'.'+master_scale.ATTRIBUTE) for n in roots}
    registered={}
    for root in roots:
        data=json.loads(markers[root+'.'+master_scale.ATTRIBUTE])
        if data['version']=='1.0.0':registered[root]=list(dict.fromkeys(r['matrix'] for r in data['skin_inputs']))
    wrappers=set()
    skins=c.ls(type='skinCluster') or []
    edges={};values={};weights={};vertices={}
    for skin in skins:
        weights[skin]=dict(weights=c.getAttr(skin+'.weightList[*].weights[*]'),blend=c.getAttr(skin+'.blendWeights'))
        for i in c.getAttr(skin+'.matrix',mi=True) or []:
            dst=skin+'.matrix[%d]'%i;src=c.connectionInfo(dst,sfd=True)
            node=src.split('.')[0]
            if not re.fullmatch(r'masterSkinFrame\d+',node.rsplit(':',1)[-1]):continue
            wrappers.add(node)
            for plug in (dst,skin+'.bindPreMatrix[%d]'%i):
                edges[plug]=c.connectionInfo(plug,sfd=True);values[plug]=c.getAttr(plug)
        for shape in c.skinCluster(skin,q=True,g=True) or []:vertices[shape]=points(shape)
    if not wrappers:return dict(changed=False)
    pose={n:c.xform(n,q=True,ws=True,m=True) for n in c.ls(type='transform',long=True)+c.ls(type='joint',long=True)}
    curves={n:(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n in c.ls(type='animCurve')}
    path=Path(__file__).resolve().parents[1]/'outputs'/'skin-paint-repair'/('scene-backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(scene=c.file(q=True,sn=True),time=c.currentTime(q=True),markers=markers,edges=edges,values=values,weights=weights,vertices=vertices,pose=pose,curves=curves),ensure_ascii=False),encoding='utf-8')
    old_nodes=set(c.ls(uuid=True));selection=c.ls(sl=True,long=True) or [];auto=c.autoKeyframe(q=True,state=True)
    c.undoInfo(openChunk=True,chunkName='RepairSkinPaintCompatibility');c.autoKeyframe(state=False)
    try:
        owned=set()
        for root,nodes in registered.items():
            master_scale.repair_legacy_skin_frames(nodes,root);owned.update(nodes)
        master_scale.repair_legacy_skin_frames(sorted(wrappers-owned))
        vertex_error=max(abs(a-b) for n,ps in vertices.items() for p,q in zip(ps,points(n)) for a,b in zip(p,q))
        assert vertex_error<1e-5,('model changed',vertex_error)
        assert all(weights[s]==dict(weights=c.getAttr(s+'.weightList[*].weights[*]'),blend=c.getAttr(s+'.blendWeights')) for s in skins),'weights changed'
        assert all(keys==(c.keyframe(n,q=True,tc=True),c.keyframe(n,q=True,vc=True)) for n,keys in curves.items()),'animation changed'
        pose_error=max(abs(a-b) for n,m in pose.items() for a,b in zip(m,c.xform(n,q=True,ws=True,m=True)))
        assert pose_error<1e-8,('pose changed',pose_error)
        influence_counts={s:len(c.skinCluster(s,q=True,inf=True) or []) for s in skins}
        assert all(influence_counts.values()),'influences still missing'
        for s in skins:
            shape=c.skinCluster(s,q=True,g=True)[0]
            assert c.skinPercent(s,shape+'.vtx[0]',q=True,transform=None),'paint influence query failed'
        report=dict(changed=True,repaired_connections=len(wrappers),influence_counts=influence_counts,weights_unchanged=True,animation_unchanged=True,vertex_error=vertex_error,pose_error=pose_error,backup=str(path))
        path.with_name(path.stem+'-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    except Exception:
        for dst,src in edges.items():
            current=c.connectionInfo(dst,sfd=True)
            if current:c.disconnectAttr(current,dst)
            if src:c.connectAttr(src,dst)
            else:c.setAttr(dst,*values[dst],type='matrix')
        for marker,text in markers.items():c.setAttr(marker,lock=False);c.setAttr(marker,text,type='string',lock=True)
        for uid in set(c.ls(uuid=True))-old_nodes:
            found=c.ls(uid,long=True) or []
            if found:c.delete(found)
        raise
    finally:
        c.select(selection,r=True) if selection else c.select(clear=True)
        c.autoKeyframe(state=auto);c.undoInfo(closeChunk=True)
