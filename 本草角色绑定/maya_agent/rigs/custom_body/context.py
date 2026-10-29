"""Build state and names shared by independently extensible components."""
from dataclasses import dataclass, field


@dataclass
class BuildContext:
    cmds: object
    definition: dict
    namespace: str
    created: list = field(default_factory=list)
    layer_connections: list = field(default_factory=list)

    def name(self, original):
        if not original:
            return original
        return original.replace(self.definition["source_namespace"] + ":", self.namespace + ":")

    def records(self, component):
        return [n for n in self.definition["nodes"] if n["component"] == component]

    def cleanup(self):
        # Delete only nodes owned by this build, never a caller's existing namespace.
        for name in reversed(self.created):
            if self.cmds.objExists(name):
                self.cmds.delete(name)
        if self.cmds.namespace(exists=self.namespace):
            self.cmds.namespace(removeNamespace=self.namespace)
