"""Measure press/update/release discontinuities without changing user animation."""
import json
import maya.cmds as c
from maya_agent.rigs import live_edit


def inspect(root,auto_key=False):
    data=json.loads(c.getAttr(root+'.liveAlignmentData'))
    nodes=list(data['controls'].values())+list(data['targets'].values())
    _,dest,frames,zero,restore=live_edit._plan(root)
    plugs=[dest.get(n+'.'+a,n+'.'+a) for n in dict.fromkeys([n for n,m in frames+restore]+zero) for a in live_edit.TR]
    saved=live_edit._snapshot(plugs)
    auto=c.autoKeyframe(q=True,state=True);tool=c.currentCtx();sel=c.ls(sl=True,long=True) or []
    def pose():return {n:c.xform(n,q=True,ws=True,m=True) for n in nodes}
    def diff(a,b):return max(abs(x-y) for n,m in a.items() for x,y in zip(m,b[n]))
    original=pose();report=[]
    try:
        c.autoKeyframe(state=auto_key)
        for role,node in data['controls'].items():
            for mode in ('move','rotate'):
                attrs=live_edit.TR[:3] if mode=='move' else live_edit.TR[3:]
                if any(not c.isConnected(node+'.'+a,data['inputs'][role]+'.'+a) for a in attrs):continue
                for edit in (False,True):
                    live_edit._restore(saved)
                    c.select(node);c.setToolTo('moveSuperContext' if mode=='move' else 'RotateSuperContext')
                    a=pose();live_edit.before_drag('audit');b=pose()
                    if edit:
                        if mode=='move':c.move(.02,.01,0,node,r=True,ws=True)
                        else:c.rotate(0,0,.1,node,r=True,os=True)
                        live_edit.update_drag()
                    d=pose();live_edit.after_drag('audit');e=pose()
                    report.append(dict(role=role,mode=mode,edit=edit,press=diff(a,b),release=diff(d,e),total=diff(a,e)))
    finally:
        if live_edit._gesture:live_edit.after_drag('cleanup')
        live_edit._restore(saved)
        c.autoKeyframe(state=auto);c.setToolTo(tool);c.select(sel,r=True) if sel else c.select(cl=True)
    return dict(results=report,restore=diff(original,pose()))
