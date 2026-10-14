"""Undo fences for a native gesture that also recalibrates companion controls.

Commands only; no custom DG nodes or scene file dependency on this plugin.
"""
import maya.api.OpenMaya as om


def maya_useNewAPI():
    pass


class StateCommand(om.MPxCommand):
    def doIt(self,args):
        from maya_agent.rigs import live_edit
        self.phase,self.snapshots=live_edit._undo_payloads.pop(args.asString(0))

    def isUndoable(self):
        return True

    def undoIt(self):
        if self.phase=='before':self.restore()

    def redoIt(self):
        if self.phase=='after':self.restore()

    def restore(self):
        from maya_agent.rigs import live_edit
        for snapshot in self.snapshots:live_edit._restore(snapshot)


def initializePlugin(obj):
    om.MFnPlugin(obj,'Maya MCP','1.1.0').registerCommand('mayaLiveEditState',StateCommand)


def uninitializePlugin(obj):
    om.MFnPlugin(obj).deregisterCommand('mayaLiveEditState')
