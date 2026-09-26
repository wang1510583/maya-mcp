"""Bake world-space leg motion onto IK controls and four orientation-offset outputs."""
import math
from maya_agent.rigs.soft_limb.animation import Transfer as ArmTransfer
from maya_agent.rigs.custom_body.animation import Transfer as BaseTransfer
from maya_agent.rigs.custom_body.targets import CHANNELS


class Transfer(ArmTransfer):
    def __init__(self,rig,samples,frames):
        super().__init__(rig,samples,frames)
        self.controls=[rig['controls'][k] for k in ('hip','knee','foot','toe')]
        self.helpers={}
        self.rest={}

    def capture(self):
        BaseTransfer.capture(self)
        try:
            for frame in self.frames:
                self.c.currentTime(frame)
                points=[self.c.xform(s['node'],q=True,ws=True,rp=True) for s in self.samples]
                if min(math.dist(points[a],points[b]) for a,b in ((0,1),(1,2),(2,3),(0,2)))<1e-5:
                    raise ValueError('帧 {} 存在重合关节或完全折叠的腿，未替换原动画。'.format(frame))
                self.pivots.append(points)
        finally:self.c.currentTime(self.time)

    def prepare_drivers(self):
        import maya.api.OpenMaya as om
        c,ns=self.c,self.ctx.namespace+':'
        for i,(joint,sample,control) in enumerate(zip(self.rig['joints'],self.samples,self.controls),1):
            driver=c.createNode('transform',name=ns+'animationOutput'+str(i),parent=joint,skipSelect=True)
            self.ctx.created.append(driver)
            matrix=list(om.MMatrix(sample['matrix']));matrix[12:15]=sample['position']
            c.xform(driver,ws=True,m=matrix)
            for attr in CHANNELS:
                custom='animationOffset'+attr[0].upper()+attr[1:]
                c.addAttr(control,ln=custom,at='doubleAngle' if attr.startswith('rotate') else 'doubleLinear',
                          niceName=('动画补偿旋转 ' if attr.startswith('rotate') else '动画补偿位移 ')+attr[-1],keyable=True)
                c.setAttr(control+'.'+custom,c.getAttr(driver+'.'+attr))
                c.connectAttr(control+'.'+custom,driver+'.'+attr)
                self._curve(control+'.'+custom,attr.startswith('rotate'))
            self.drivers.append(driver)
        # Maya's xform on a disposable twin handles pivot compensation and rotate order.
        # Original controls remain animated; the twin is removed after baking.
        for index in (2,3):
            control=self.controls[index]
            parent=c.listRelatives(control,parent=True,fullPath=True)[0]
            helper=c.createNode('transform',name=ns+'animationSolve'+str(index),parent=parent,skipSelect=True)
            self.temporary.append(helper);self.ctx.created.append(helper)
            c.setAttr(helper+'.visibility',False)
            for attr in ('translate','rotate','scale','rotateAxis','rotatePivot','scalePivot','rotatePivotTranslate','scalePivotTranslate'):
                c.setAttr(helper+'.'+attr,*c.getAttr(control+'.'+attr)[0])
            c.setAttr(helper+'.rotateOrder',c.getAttr(control+'.rotateOrder'))
            self.helpers[control]=helper
            rest=list(om.MMatrix(self.samples[index]['matrix']));rest[12:15]=self.samples[index]['position']
            self.rest[control]=om.MMatrix(c.xform(control,q=True,ws=True,m=True))*om.MMatrix(rest).inverse()
        return self.drivers

    def _control_values(self,control,desired):
        import maya.api.OpenMaya as om
        helper=self.helpers[control]
        self.c.xform(helper,ws=True,m=list(desired))
        # xform(matrix=...) may rewrite pivot-compensation attributes. Those are
        # static on the real control, so restore them and solve the translation
        # difference in parent space instead of accidentally baking setup edits.
        for attr in ('rotatePivotTranslate','scalePivotTranslate'):
            self.c.setAttr(helper+'.'+attr,*self.c.getAttr(control+'.'+attr)[0])
        actual=self.c.xform(helper,q=True,ws=True,m=True)
        delta=om.MVector(*[a-b for a,b in zip(list(desired)[12:15],actual[12:15])])
        parent=self.c.listRelatives(helper,parent=True,fullPath=True) or []
        if parent:delta*=om.MMatrix(self.c.xform(parent[0],q=True,ws=True,m=True)).inverse()
        translation=self.c.getAttr(helper+'.translate')[0]
        self.c.setAttr(helper+'.translate',*[v+d for v,d in zip(translation,delta)])
        values=[self.c.getAttr(helper+'.'+a) for a in CHANNELS]
        rotation=om.MEulerRotation(*[math.radians(v) for v in values[3:]],self.c.getAttr(control+'.rotateOrder'))
        if control in self.previous:rotation=rotation.closestSolution(self.previous[control])
        self.previous[control]=rotation
        return values[:3]+[math.degrees(v) for v in rotation]

    def bake(self,mappings):
        import maya.api.OpenMaya as om
        from maya_agent.rigs.soft_limb.selection import _geometry
        c=self.c
        settings=self.rig['controls']['settings']
        for index,control in enumerate(self.controls):
            for attr in CHANNELS if index>=2 else CHANNELS[:3]:self._curve(control+'.'+attr,attr.startswith('rotate'))
        for i in (1,2):self._curve(settings+'.lenght_joint_'+str(i))
        for frame,matrices,points in zip(self.frames,self.motion,self.pivots):
            c.currentTime(frame)
            samples=[dict(position=p,matrix=list(om.MTransformationMatrix(om.MMatrix(m)).rotation(asQuaternion=True).asMatrix()))
                     for p,m in zip(points,matrices)]
            _,pole,_=_geometry(samples[:3])
            for i in (0,1):self._key(settings+'.lenght_joint_'+str(i+1),frame,math.dist(points[i],points[i+1]))
            for control,position in zip(self.controls[:2],[points[0],pole]):
                matrix=list(om.MMatrix());matrix[12:15]=position
                for attr,value in zip(CHANNELS[:3],self._local(control,matrix)[:3]):self._key(control+'.'+attr,frame,value)
            for index in (2,3):
                control=self.controls[index]
                desired=list(samples[index]['matrix']);desired[12:15]=points[index]
                values=self._control_values(control,self.rest[control]*om.MMatrix(desired))
                for attr,value in zip(CHANNELS,values):self._key(control+'.'+attr,frame,value)
            for joint,point in zip(self.rig['joints'][:3],points[:3]):
                if math.dist(c.xform(joint,q=True,ws=True,t=True),point)>1e-4:
                    raise RuntimeError('腿部 IK 动画解算未匹配原关节：{}，帧 {}'.format(joint,frame))
            for sample,point,control,driver in zip(samples,points,self.controls,self.drivers):
                desired=list(sample['matrix']);desired[12:15]=point
                for attr,value in zip(CHANNELS,self._local(driver,desired)):
                    self._key(control+'.animationOffset'+attr[0].upper()+attr[1:],frame,value)
        if all(abs(f-self.time)>1e-8 for f in self.frames):
            for plug in self.keyed:c.cutKey(plug,time=(self.time,self.time),clear=True)
        error=self.verify(mappings)
        for node in reversed(self.temporary):
            if c.objExists(node):c.delete(node)
        self.ctx.created[:]=[n for n in self.ctx.created if n not in self.temporary]
        error=max(error,self.verify(mappings))
        return dict(start_frame=self.frames[0],end_frame=self.frames[-1],sample_count=len(self.frames),
                    max_world_matrix_error=error,source_animation_backup=self.backup,
                    original_curve_count=len(set(e['source'].split('.')[0] for e in self.edges)),
                    scale_animation='preserved_on_targets',temporary_locators_removed=True,
                    controls=self.controls,orientation_offsets='animationOffset channels on leg controls')
