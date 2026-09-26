"""Apply reviewed native node commands without opening/importing a scene file."""
import hashlib
import re


def commands(text):
    """Split Maya ASCII commands, preserving strings, escapes and wrapped lines."""
    text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('//'))
    quoted=False
    escaped=False
    start=0
    for index,char in enumerate(text):
        if escaped:
            escaped=False
            continue
        if quoted and char=='\\':
            escaped=True
        elif char=='"':
            quoted=not quoted
        elif char==';' and not quoted:
            command=text[start:index+1].strip()
            start=index+1
            if command: yield command
    if quoted or text[start:].strip():
        raise ValueError('Incomplete native rig command')


def create(path, spec, namespace):
    import maya.mel as mel
    import maya.cmds as c
    text=path.read_text(encoding='utf-8')
    if hashlib.sha256(text.encode('utf-8')).hexdigest()!=spec['template_sha256']:
        raise ValueError('Rig template checksum mismatch')
    items=list(commands(text))
    allowed={'requires','createNode','addAttr','setAttr','connectAttr'}
    if any(command.split()[0] not in allowed for command in items):
        raise ValueError('Unexpected command in rig template')
    names=re.compile(r'(?<=")('+ '|'.join(re.escape(n) for n in sorted(spec['nodes'],key=len,reverse=True))+r')(?=[."])')
    # quatNodes is loaded by the builder. No file command, scriptNode or scene callbacks.
    expression_block = False
    expression_locks = []
    for command in items:
        if command.startswith('createNode '):
            expression_block = command.startswith('createNode expression ')
        if command.startswith('connectAttr '):
            expression_block = False
            if '"expression1.' in command:
                plugs = re.findall(r'"([^"]+)"', command)
                if plugs[0].startswith('expression1.') and re.search(r'-l\s+on\b',command):
                    expression_locks.append(namespace+':'+plugs[1])
                continue
            plugs = re.findall(r'"([^"]+)"', command)
            source_plug, destination_plug = [namespace+':'+p for p in plugs]
            was_locked = c.getAttr(destination_plug, lock=True)
            # Import-style connectAttr -l can stop Maya's redo on locked destinations.
            # Record unlock, connection and relock as separate undoable operations.
            c.setAttr(destination_plug, lock=False)
            options = {'nextAvailable':True} if '-na' in command else {}
            c.connectAttr(source_plug, destination_plug, **options)
            c.setAttr(destination_plug, lock=was_locked or bool(re.search(r'-l\s+on\b',command)))
            continue
        # File-reader expression internals cannot safely be replayed on redo.
        # Create/compile the readable expression once, after its dependencies exist.
        if not expression_block and not command.startswith('requires '):
            mel.eval(names.sub(lambda m: ':'+namespace+':'+m.group(0), command))
    # .ixp is a file-reader representation, not an executable expression outside import.
    # Compile the reviewed human-readable solver after all its inputs/outputs exist.
    identifiers=re.compile(r'\b('+ '|'.join(re.escape(n) for n in sorted(spec['nodes'],key=len,reverse=True))+r')(?=\.)')
    source=identifiers.sub(lambda m: namespace+':'+m.group(0),spec['expression'])
    outputs=[namespace+':'+p for p in spec.get('expression_outputs',
             ('soft_knee_gr.translateX','pivot_feet.translateX',
              'soft_knee_gr.translateY','multiplyDivide3.input1X'))]
    locks=[c.getAttr(p,lock=True) for p in outputs]
    try:
        for p in outputs: c.setAttr(p,lock=False)
        # expression(name=...) loses the namespace on Maya 2024 redo. Explicit
        # createNode followed by editing an empty expression preserves its identity.
        expression_node = c.createNode('expression', name=namespace+':expression1', skipSelect=True)
        c.expression(expression_node,edit=True,string=source,alwaysEvaluate=True,unitConversion='none')
    finally:
        for p,locked in zip(outputs,locks): c.setAttr(p,lock=locked)
        for p in expression_locks: c.setAttr(p,lock=True)
