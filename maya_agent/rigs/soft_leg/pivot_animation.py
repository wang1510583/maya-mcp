"""Preserve continuous animation across pivot edits without rebaking live curves.

Reference transforms retain the old/new setup with snapshots of the current
rotation and scale animation. Their local translation difference compensates
the live rotatePivotTranslate. References never read the live control, so later
animation edits still rotate around the new pivot instead of cancelling it.
"""
import maya.cmds as c

PIVOTS=('rotatePivot','scalePivot','rotatePivotTranslate','scalePivotTranslate')
SCALARS=tuple(a+axis for a in ('rotate','rotateAxis','scale') for axis in 'XYZ')+(
    'shearXY','shearXZ','shearYZ','rotateOrder')


def source(plug):return c.connectionInfo(plug,sourceFromDestination=True) or ''


def snapshot(node):
    values={a:c.getAttr(node+'.'+a)[0] for a in PIVOTS}
    edges={}
    for attr in PIVOTS:
        plug=node+'.'+attr
        if source(plug):edges[plug]=source(plug)
        else:
            for axis in 'XYZ':
                if source(plug+axis):edges[plug+axis]=source(plug+axis)
    return dict(node=node,values=values,edges=edges)


def _validate(state):
    node=state['node']
    for attr in SCALARS:
        src=source(node+'.'+attr)
        if not src:continue
        curve=src.split('.')[0]
        if c.nodeType(curve) not in ('animCurveTA','animCurveTL','animCurveTU'):
            raise ValueError('支点调整暂不支持此通道的外部驱动：'+node+'.'+attr)
        time_source=source(curve+'.input')
        if time_source and c.nodeType(time_source.split('.')[0])!='time':
            raise ValueError('支点调整需要普通时间动画：'+node+'.'+attr)
    for dst,src in state['edges'].items():
        owner=src.split('.')[0]
        if (dst!=node+'.rotatePivotTranslate' or not c.objExists(owner+'.legPivotCompensation')
                or not c.getAttr(owner+'.legPivotCompensation')):
            raise ValueError('支点属性已有外部驱动，未覆盖：'+dst)


class Edit:
    def __init__(self,root,nodes):
        self.root=root
        self.prefix=root.rsplit('|',1)[-1].rsplit(':',1)[0]+':'
        self.states={n:snapshot(n) for n in nodes}
        self.created=[]
        for state in self.states.values():_validate(state)

    def create(self,kind,name,**kwargs):
        node=c.createNode(kind,name=self.prefix+name,skipSelect=True,**kwargs)
        self.created.append(node)
        return node

    def reference(self,node,label):
        ref=self.create('transform',node.rsplit(':',1)[-1]+'_pivot'+label,parent=self.root)
        c.setAttr(ref+'.inheritsTransform',False)
        c.setAttr(ref+'.visibility',False)
        c.setAttr(ref+'.hiddenInOutliner',True)
        for attr in SCALARS:c.setAttr(ref+'.'+attr,c.getAttr(node+'.'+attr))
        for attr in PIVOTS:c.setAttr(ref+'.'+attr,*c.getAttr(node+'.'+attr)[0])
        return ref

    def apply(self,node,position):
        from .adjustment import set_pivot,pivot_lock
        state=self.states[node]
        old=self.reference(node,'Before')
        # Old compensation graphs contain only frozen curves and references. Reuse
        # their output on the old reference when performing a subsequent edit.
        for dst,src in state['edges'].items():
            c.connectAttr(src,old+'.'+dst.rsplit('.',1)[-1])
        pivot_lock(node,False)
        for dst,src in state['edges'].items():c.disconnectAttr(src,dst)
        for attr,value in state['values'].items():c.setAttr(node+'.'+attr,*value)
        set_pivot(node,position)
        new=self.reference(node,'After')
        for attr in SCALARS:
            src=source(node+'.'+attr)
            if not src:continue
            curve=src.split('.')[0]
            clone=c.duplicate(curve,name=self.prefix+node.rsplit(':',1)[-1]+'_'+attr+'_pivotReference',
                              inputConnections=True)[0]
            self.created.append(clone)
            for ref in (old,new):c.connectAttr(clone+'.'+src.split('.',1)[1],ref+'.'+attr)
        decomposers=[]
        for ref in (old,new):
            decomp=self.create('decomposeMatrix',node.rsplit(':',1)[-1]+'_pivotMatrix')
            c.connectAttr(ref+'.matrix',decomp+'.inputMatrix');decomposers.append(decomp)
        difference=self.create('plusMinusAverage',node.rsplit(':',1)[-1]+'_pivotDifference')
        c.setAttr(difference+'.operation',2)
        for i,decomp in enumerate(decomposers):c.connectAttr(decomp+'.outputTranslate',difference+'.input3D[{}]'.format(i))
        total=self.create('plusMinusAverage',node.rsplit(':',1)[-1]+'_pivotCompensation')
        c.addAttr(total,ln='legPivotCompensation',at='bool',defaultValue=True)
        c.setAttr(total+'.legPivotCompensation',True,lock=True)
        c.setAttr(total+'.input3D[0]',*c.getAttr(node+'.rotatePivotTranslate')[0])
        c.connectAttr(difference+'.output3D',total+'.input3D[1]')
        pivot_lock(node,False)
        try:c.connectAttr(total+'.output3D',node+'.rotatePivotTranslate')
        finally:pivot_lock(node,True)

    def rollback(self):
        from .adjustment import pivot_lock
        for node,state in self.states.items():
            pivot_lock(node,False)
            try:
                for attr in PIVOTS:
                    plug=node+'.'+attr
                    if source(plug):c.disconnectAttr(source(plug),plug)
                    else:
                        for axis in 'XYZ':
                            if source(plug+axis):c.disconnectAttr(source(plug+axis),plug+axis)
                for attr,value in state['values'].items():c.setAttr(node+'.'+attr,*value)
                for dst,src in state['edges'].items():c.connectAttr(src,dst)
            finally:pivot_lock(node,True)
        for node in reversed(self.created):
            if c.objExists(node):c.delete(node)
