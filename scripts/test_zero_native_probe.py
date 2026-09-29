"""Native viewport probes; caller restores or undoes its disposable fixture."""
import math
import maya.cmds as c
from maya_agent.rigs import live_edit


def probe(control, rotate=False, click=False):
    import maya.api.OpenMayaUI as ui
    import maya.api.OpenMaya as om
    from PySide2 import QtCore,QtGui,QtWidgets,QtTest
    from shiboken2 import wrapInstance
    c.select(control,r=True)
    c.setToolTo('RotateSuperContext' if rotate else 'moveSuperContext')
    if rotate:c.manipRotateContext('Rotate',e=True,mode=0,activeHandle=2)
    else:c.manipMoveContext('Move',e=True,mode=2,activeHandle=0)
    c.refresh(f=True)
    view=ui.M3dView.active3dView();widget=wrapInstance(int(view.widget()),QtWidgets.QWidget)
    def pose():
        shapes=c.listRelatives(control,s=True,f=True) or []
        curve=next((s for s in shapes if c.nodeType(s)=='nurbsCurve'),None)
        return dict(pivot=c.xform(control,q=True,ws=True,t=True),
                    cv=c.pointPosition(curve+'.cv[0]',world=True) if curve else [],
                    channels=[c.getAttr(control+'.'+a) for a in live_edit.TR])
    phases={'before':pose()}
    x,y=view.worldToView(om.MPoint(phases['before']['pivot']))[:2];y=widget.height()-y
    start=QtCore.QPoint(x+60,y);end=start
    QtTest.QTest.mousePress(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,start)
    phases['press']=pose();phases['fired']=bool(live_edit._gesture)
    if not click:
        for i in (1,2):
            end=QtCore.QPoint(x+60+10*i,y-5*i)
            QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                QtCore.QPointF(end),QtCore.QPointF(widget.mapToGlobal(end)),QtCore.Qt.NoButton,
                QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier))
            QtWidgets.QApplication.processEvents();phases['move'+str(i)]=pose()
    QtTest.QTest.mouseRelease(widget,QtCore.Qt.MiddleButton,QtCore.Qt.NoModifier,end)
    phases['release_event']=pose()
    QtWidgets.QApplication.processEvents();phases['released']=pose()
    return phases


def verify_sequence(control):
    """Repeated press/move/release is essential: the stale cache starts on drag 2."""
    errors=[]
    for rotate,click in ((False,False),(False,False),(False,True),(True,False),(False,False),(True,True)):
        p=probe(control,rotate=rotate,click=click)
        assert p['fired'],control
        for name in ('pivot','cv'):
            press=math.dist(p['before'][name],p['press'][name])
            release=math.dist(p['release_event'][name],p['released'][name])
            assert max(press,release)<1e-5,(control,name,press,release)
            if click:assert math.dist(p['before'][name],p['released'][name])<1e-5
            errors.extend((press,release))
    return dict(control=control,max_jump=max(errors))
