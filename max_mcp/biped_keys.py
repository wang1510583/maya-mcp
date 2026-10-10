"""Read actual Biped track key times, including the three COM tracks."""


def collect(root,bones):
    from pymxs import runtime as rt
    def times(control):
        count=int(rt.numKeys(control))
        return sorted({float(rt.getKeyTime(control,i)) for i in range(1,max(0,count)+1)})
    tracks={str(n.name):times(n.controller) for n in bones}
    for label in ('Vertical','Horizontal','Turn'):
        tracks[str(root.name)+' COM '+label]=times(getattr(rt.biped,'get'+label+'Control')(root.controller))
    return dict(tracks=tracks,times=sorted({f for values in tracks.values() for f in values}),
                policy='union_of_mapped_bones_and_com')
