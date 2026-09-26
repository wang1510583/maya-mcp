"""Shared Maya UI layout for body, arm and leg tools; contains no rig logic."""
WIDTH=520
HEIGHT=860
BUTTON_COLOR=(.22,.42,.48)


def begin(c,window,title,version,instruction):
    if c.window(window,exists=True):c.deleteUI(window)
    # Maya otherwise restores each old window's saved dimensions over this size.
    if c.windowPref(window,exists=True):c.windowPref(window,remove=True)
    c.window(window,title=title+' v'+version,widthHeight=(WIDTH,HEIGHT),sizeable=True)
    c.scrollLayout(childResizable=True)
    c.columnLayout(adjustableColumn=True,rowSpacing=8,columnAttach=('both',12))
    c.text(label=title,align='left',font='boldLabelFont',height=26)
    c.text(label=instruction,align='left',height=26)


def selection(c,preview,reverse):
    frame=c.frameLayout(label='目标选择与顺序',collapsable=False,marginWidth=8,marginHeight=8)
    c.columnLayout(adjustableColumn=True,rowSpacing=6)
    listing=c.textScrollList(height=90,allowMultiSelection=False)
    c.rowLayout(numberOfColumns=2,adjustableColumn=2,columnWidth2=(230,230))
    c.button(label='预览当前选择顺序',width=226,command=preview)
    c.button(label='反转选择顺序',command=reverse)
    c.setParent('..');c.setParent('..');c.setParent('..')
    return frame,listing


def namespace(c,default):
    return c.textFieldGrp(label='名称前缀',text=default,columnWidth2=(110,350))


def animation_fields(c):
    layout=c.columnLayout(adjustableColumn=True,rowSpacing=5,enable=False)
    bounds=c.floatFieldGrp(label='起始 / 结束帧',numberOfFields=2,precision=3,
                          value1=c.playbackOptions(q=True,minTime=True),value2=c.playbackOptions(q=True,maxTime=True))
    step=c.floatFieldGrp(label='采样间隔（帧）',numberOfFields=1,value1=1,precision=3)
    c.setParent('..')
    c.text(label='勾选后逐帧转移平移和旋转，原曲线备份，缩放动画保留。\n只保证采样帧姿态；不支持动画层、已有约束或非均匀缩放。',
           align='left',wordWrap=True,height=40)
    return layout,bounds,step


def create_button(c,label,command):
    return c.button(label=label,height=40,backgroundColor=BUTTON_COLOR,command=command)


def status(c,text='就绪。'):
    return c.scrollField(editable=False,wordWrap=True,height=66,text=text)
