"""Reversible handoff of existing TR drivers after world-space motion capture.

Source constraints, expressions and animation-layer graphs remain in the scene.
Only exact incoming TR edges are detached; parent and scale inputs are retained.
"""
import json
from maya_agent.rigs.custom_body.targets import CHANNELS


class InputTransfer:
    def __init__(self, ctx, samples, frames):
        self.c=ctx.cmds;self.ctx=ctx;self.samples=samples;self.frames=frames
        self.backup=None;self.edges=[];self.detached=[];self.flags={}
        for sample in samples:
            node=sample['node']
            for attr in ('translate','rotate')+CHANNELS:
                plug=node+'.'+attr
                self.flags[plug]=self.c.getAttr(plug,lock=True)
                if not self.c.connectionInfo(plug,isExactDestination=True):continue
                edge=dict(source=self.c.connectionInfo(plug,sourceFromDestination=True),destination=plug)
                if edge not in self.edges:self.edges.append(edge)

    def unlock(self):
        for plug in self.flags:
            self.c.setAttr(plug,lock=False)

    def restore_locks(self):
        # Children first: a compound lock may lock all its descendants.
        for plug,locked in reversed(list(self.flags.items())):
            self.c.setAttr(plug,lock=locked)

    def detach(self):
        c=self.c
        self.backup=c.createNode('network',name=self.ctx.namespace+':sourceDriverBackup')
        self.ctx.created.append(self.backup)
        for attr,data in [('originalConnections',self.edges),('originalLocks',self.flags),
                          ('originalValues',{s['node']:s['channels'] for s in self.samples})]:
            c.addAttr(self.backup,ln=attr,dt='string');c.setAttr(self.backup+'.'+attr,json.dumps(data),type='string',lock=True)
        c.addAttr(self.backup,ln='sourceCurves',at='message',multi=True)
        for i,node in enumerate(dict.fromkeys(e['source'].split('.')[0] for e in self.edges)):
            c.connectAttr(node+'.message',self.backup+'.sourceCurves[%d]'%i)
        self.unlock()
        for edge in self.edges:
            c.disconnectAttr(edge['source'],edge['destination']);self.detached.append(edge)
        for sample in self.samples:
            for attr,value in sample['channels'].items():c.setAttr(sample['node']+'.'+attr,value)

    def release_backup(self):
        if self.backup and self.c.objExists(self.backup):
            for i,node in enumerate(dict.fromkeys(e['source'].split('.')[0] for e in self.edges)):
                src=node+'.message';dst=self.backup+'.sourceCurves[%d]'%i
                if self.c.isConnected(src,dst):self.c.disconnectAttr(src,dst)

    def rollback(self):
        self.unlock()
        for sample in self.samples:
            for attr,value in sample['channels'].items():
                plug=sample['node']+'.'+attr
                if not self.c.connectionInfo(plug,isDestination=True):self.c.setAttr(plug,value)
        for edge in self.detached:
            if not self.c.isConnected(edge['source'],edge['destination']):
                self.c.connectAttr(edge['source'],edge['destination'])
        self.restore_locks()
