"""Sample world motion, then bake arm inputs and independent orientation offsets."""
import math
from types import SimpleNamespace
from maya_agent.rigs.custom_body.animation import Transfer as BaseTransfer
from maya_agent.rigs.custom_body.targets import CHANNELS


class Transfer(BaseTransfer):
    def __init__(self, rig, samples, frames):
        import maya.cmds as c
        super().__init__(SimpleNamespace(cmds=c, namespace=rig['namespace'], created=rig['nodes']), samples, frames)
        self.rig = rig
        self.pivots = []
        self.drivers = []
        self.previous = {}
        self.keyed = []

    def capture(self):
        super().capture()
        try:
            for frame in self.frames:
                self.c.currentTime(frame)
                points = [self.c.xform(s['node'], q=True, ws=True, rotatePivot=True) for s in self.samples]
                if min(math.dist(points[a],points[b]) for a,b in ((0,1),(1,2),(0,2))) < 1e-5:
                    raise ValueError('帧 {} 存在重合点或完全折叠的手臂，未替换原动画。'.format(frame))
                self.pivots.append(points)
        finally:
            self.c.currentTime(self.time)

    def _curve(self, plug, angular=False):
        c = self.c
        node, attr = plug.rsplit('.',1)
        curve = c.createNode('animCurveTA' if angular else 'animCurveTL',
                             name=node.split('|')[-1]+'_'+attr+'_bake', skipSelect=True)
        self.ctx.created.append(curve)
        value = c.getAttr(plug)
        c.connectAttr('time1.outTime',curve+'.input')
        c.connectAttr(curve+'.output',plug)
        self.keyed.append(plug)
        self._key(plug,self.time,value)

    def _key(self, plug, frame, value):
        self.c.setKeyframe(plug,time=frame,value=value,inTangentType='linear',outTangentType='linear')
        self.c.dgdirty(plug.split('.')[0])

    def _local(self, node, desired):
        import maya.api.OpenMaya as om
        c = self.c
        parent = c.listRelatives(node, parent=True, fullPath=True) or []
        local = om.MMatrix(desired)
        if parent: local *= om.MMatrix(c.xform(parent[0],q=True,ws=True,m=True)).inverse()
        tm = om.MTransformationMatrix(local)
        rotation = tm.rotation(asQuaternion=True).asMatrix()
        if c.nodeType(node)=='joint':
            def orient(attr):
                return om.MEulerRotation(*[math.radians(v) for v in c.getAttr(node+'.'+attr)[0]]).asMatrix()
            rotation = orient('rotateAxis').inverse()*rotation*orient('jointOrient').inverse()
        euler = om.MTransformationMatrix(rotation).rotation(asQuaternion=True).asEulerRotation()
        euler.reorderIt(c.getAttr(node+'.rotateOrder'))
        if node in self.previous: euler = euler.closestSolution(self.previous[node])
        self.previous[node] = euler
        return list(tm.translation(om.MSpace.kTransform)) + [math.degrees(v) for v in (euler.x,euler.y,euler.z)]

    def prepare_drivers(self):
        """Offset channels preserve arbitrary target rotations, independent of the bend plane."""
        import maya.api.OpenMaya as om
        c, ns = self.c, self.ctx.namespace+':'
        controls = [ns+n for n in ('shldrFK_L1','armFK_L1','handFK_L1')]
        for i,(joint,sample,control) in enumerate(zip(self.rig['joints'],self.samples,controls),1):
            driver = c.createNode('transform',name=ns+'animationOutput'+str(i),parent=joint,skipSelect=True)
            self.ctx.created.append(driver)
            matrix = list(om.MMatrix(sample['matrix']))
            matrix[12:15] = sample['position']
            c.xform(driver,ws=True,m=matrix)
            for attr in CHANNELS:
                value = c.getAttr(driver+'.'+attr)
                custom = 'animationOffset'+attr[0].upper()+attr[1:]
                c.addAttr(control,longName=custom,attributeType='doubleAngle' if attr.startswith('rotate') else 'doubleLinear',
                          niceName=('动画补偿旋转 ' if attr.startswith('rotate') else '动画补偿位移 ')+attr[-1],keyable=True)
                c.setAttr(control+'.'+custom,value)
                c.connectAttr(control+'.'+custom,driver+'.'+attr)
                self._curve(control+'.'+custom,attr.startswith('rotate'))
            self.drivers.append(driver)
        return self.drivers

    def bake(self, mappings):
        import maya.api.OpenMaya as om
        from .selection import _geometry
        c, ns = self.c, self.ctx.namespace+':'
        controls = [ns+n for n in ('shldrFK_L1','armFK_L1','handFK_L1')]
        for control in controls:
            for attr in CHANNELS:self._curve(control+'.'+attr,attr.startswith('rotate'))
        for axis in 'XYZ':self._curve(ns+'elb_L1.translate'+axis)
        for index in (1,2):self._curve(ns+'strech_ik_foot1.lenght_joint_'+str(index))
        for frame,matrices,points in zip(self.frames,self.motion,self.pivots):
            c.currentTime(frame)
            samples=[dict(position=p,matrix=list(om.MTransformationMatrix(om.MMatrix(m)).rotation(asQuaternion=True).asMatrix()))
                     for p,m in zip(points,matrices)]
            frames,pole,_ = _geometry(samples)
            for i in (0,1):self._key(ns+'strech_ik_foot1.lenght_joint_'+str(i+1),frame,math.dist(points[i],points[i+1]))
            for control,matrix in zip(controls,frames):
                for attr,value in zip(CHANNELS,self._local(control,matrix)):self._key(control+'.'+attr,frame,value)
            pole_matrix = list(om.MMatrix())
            pole_matrix[12:15] = pole
            for attr,value in zip(CHANNELS[:3],self._local(ns+'elb_L1',pole_matrix)[:3]):self._key(ns+'elb_L1.'+attr,frame,value)
            for sample,point,control,driver in zip(samples,points,controls,self.drivers):
                desired=list(sample['matrix'])
                desired[12:15]=point
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
                    controls=controls,orientation_offsets='animationOffset channels on FK controls')
