"""Independent native-node motion reference; clone curves, never edit source animation."""
import maya.cmds as c

VERSION='1.0.0'
NATIVE={'orientConstraint','decomposeMatrix','multMatrix','composeMatrix','choice',
        'addDoubleLinear','multDoubleLinear','condition','timeToUnitConversion',
        'unitConversion','inverseMatrix','blendMatrix','reverse','multiplyDivide',
        'plusMinusAverage','quatNormalize','quatAdd','quatProd','eulerToQuat',
        'quatInvert','quatNegate','quatConjugate','quatSlerp','quatToEuler',
        'axisAngleToQuat','quatToAxisAngle','animBlendNodeAdditiveDL','animBlendNodeAdditiveDA',
        'animCurveTA','animCurveTL','animCurveTU','animCurveTT'}

class Reference:
    def __init__(self, namespace, created):
        self.namespace=namespace;self.created=created;self.copies={};self.wired=set();self.busy=set()
        self.group=c.createNode('transform',name=namespace+':continuous_reference',skipSelect=True)
        self.created.append(self.group);c.setAttr(self.group+'.visibility',False)

    def source(self, plug):
        node,attr=plug.split('.',1)
        if c.nodeType(node)=='time':return plug
        dag=c.nodeType(node)=='transform'
        if dag and attr.split('[',1)[0] in ('worldMatrix','worldInverseMatrix','parentMatrix','parentInverseMatrix'):
            raise ValueError('身体旋转参考包含世界空间反馈，未修改绑定：'+plug)
        if node not in self.copies:
            if dag:
                clone=c.duplicate(node,parentOnly=True,inputConnections=False,name=self.namespace+':continuous_refTransform',returnRootsOnly=True)[0]
                self.created.append(clone)
                c.parent(clone,self.group,relative=True)
            else:
                if c.nodeType(node) not in NATIVE:
                    raise ValueError('身体旋转参考不支持该驱动节点，未修改原动画：'+node+' ('+c.nodeType(node)+')')
                clone=c.duplicate(node,inputConnections=False,name=self.namespace+':continuous_refNode')[0]
                self.created.append(clone)
                if c.objectType(clone,isAType='dagNode'):c.parent(clone,self.group,relative=True)
            self.copies[node]=clone
        clone=self.copies[node]
        if dag:
            attributes=('translate','rotate','scale','shear','rotateOrder','rotateAxis','rotatePivot','rotatePivotTranslate','scalePivot','scalePivotTranslate') if attr in ('matrix','inverseMatrix') else (attr,)
            for attribute in attributes:self.attribute(node,clone,attribute)
        elif node not in self.busy:
            self.busy.add(node)
            connections=c.listConnections(node,s=True,d=False,p=True,c=True) or []
            for dest,src in zip(connections[::2],connections[1::2]):
                if c.getAttr(src,type=True)=='message':continue
                target=clone+'.'+dest.split('.',1)[1]
                if c.getAttr(target,lock=True):raise ValueError('身体参考输入锁定：'+target)
                c.connectAttr(self.source(src),target,force=True)
        return clone+'.'+attr

    def attribute(self,node,clone,attr):
        key=(node,attr)
        if key in self.wired:return
        self.wired.add(key)
        source=node+'.'+attr;target=clone+'.'+attr
        incoming=c.connectionInfo(source,sourceFromDestination=True)
        if incoming:
            c.connectAttr(self.source(incoming),target,force=True);return
        children=c.attributeQuery(attr,node=node,listChildren=True) or []
        for child in children:self.attribute(node,clone,child)
