"""Selection-driven character assembly of the custom body, arm and leg modules."""
VERSION='1.5.0'
PARTS={
    'head':dict(label='头脖子',kind='head',anchor='chest',count=None),
    'body':dict(label='身体',kind='body',anchor=None,count=None),
    'shoulder_R':dict(label='右肩膀',kind='shoulder',anchor='chest',side='R',count=1),
    'shoulder_L':dict(label='左肩膀',kind='shoulder',anchor='chest',side='L',count=1),
    'arm_R':dict(label='右手臂',kind='arm',anchor='chest',side='R',count=3),
    'arm_L':dict(label='左手臂',kind='arm',anchor='chest',side='L',count=3),
    'leg_R':dict(label='右腿',kind='leg',anchor='hips',side='R',count=4),
    'leg_L':dict(label='左腿',kind='leg',anchor='hips',side='L',count=4),
}


def build(parts,namespace='customCharacter',general_root=None):
    from .builder import build as create
    return create(parts,namespace,general_root=general_root)


def show_ui():
    from .ui import show
    return show()
