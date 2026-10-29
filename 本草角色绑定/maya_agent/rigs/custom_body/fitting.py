"""Fit procedural rest frames without referencing live targets in the input graph.

The existing matrix chain keeps translation-only propagation and independent slides.
Endpoint rotation deltas are converted to each intermediate control's rest frame
before the original orientConstraint quaternion blend.
"""
import math


def fit_definition(data, samples):
    import maya.api.OpenMaya as om
    prefix = data['source_namespace'] + ':'
    nodes = {row['name']: row for row in data['nodes']}
    controls = list(data['controls'].values())
    rotations = [om.MMatrix(s['matrix']) for s in samples]
    lengths = [math.dist(a['position'], b['position']) for a, b in zip(samples, samples[1:])]
    total = sum(lengths)

    def value(name, attr, val):
        nodes[prefix + name]['attributes'][attr]['value'] = val
        if attr in nodes[prefix + name].get('custom_attributes', {}):
            nodes[prefix + name]['custom_attributes'][attr]['value'] = val

    def triple(name, attr, vector):
        for axis, val in zip('XYZ', vector):
            value(name, attr + axis, val)

    def edge(source, destination):
        data['connections'].append({'source': prefix+source, 'destination': prefix+destination})

    def replace_input(destination, source):
        for connection in data['connections']:
            if connection['destination'] == prefix + destination:
                connection['source'] = prefix + source
                return
        raise RuntimeError('Missing fit input: ' + destination)

    def node(kind, name, attrs):
        row = {'name': prefix + name, 'type': kind, 'parent': None, 'component': 'drivers',
               'attributes': {a: {'type': 'matrix' if isinstance(v, list) else 'double',
                                  'value': v, 'keyable': False, 'locked': False} for a, v in attrs.items()}}
        data['nodes'].append(row)
        nodes[row['name']] = row

    for index, (control, sample) in enumerate(zip(controls, samples)):
        stem = control[:-5]
        triple(stem + '_zero', 'translate', sample['position'])
        triple(stem + '_zero', 'rotate', sample['rotation'])
        if index:
            delta = om.MVector(*[b-a for a, b in zip(samples[index-1]['position'], sample['position'])])
            local = delta * rotations[index-1].inverse()
            triple('offset{}'.format(index), 'inputTranslate', [local.x, local.y, local.z])
        if 0 < index < len(samples)-1:
            fraction = sum(lengths[:index]) / total
            value(control, 'hipsWeight', 1-fraction)
            value(control, 'chestWeight', fraction)
            triple(stem + '_slide', 'input2', [fraction]*3)
            rest = stem + '_restRotation'
            node('composeMatrix', rest, {'inputRotate'+axis: val for axis,val in zip('XYZ', sample['rotation'])})
            next_matrix = 'position{}'.format(index+1)
            # offset * control delta * blended delta * rest rotation * previous base position
            for connection in data['connections']:
                if connection['destination'] == prefix + next_matrix + '.matrixIn[3]':
                    connection['destination'] = prefix + next_matrix + '.matrixIn[4]'
            edge(rest + '.outputMatrix', next_matrix + '.matrixIn[3]')

            slide = stem + '_slideFrame'
            node('vectorProduct', slide, {'operation': 3, 'normalizeOutput': False,
                                          'matrix': list(rotations[-1] * rotations[index].inverse())})
            edge('chest_ctrl.translate', slide + '.input1')
            replace_input(stem + '_slide.input1', slide + '.output')

            for target_index, endpoint_index in enumerate((0, len(samples)-1)):
                endpoint = 'hips' if target_index == 0 else 'chest'
                delta_name = stem + '_' + endpoint + 'Delta'
                node('multMatrix', delta_name, {
                    'matrixIn[0]': list(rotations[index] * rotations[endpoint_index].inverse()),
                    'matrixIn[2]': list(rotations[endpoint_index] * rotations[index].inverse())})
                node('decomposeMatrix', delta_name + 'Euler', {})
                edge(endpoint + '_localRotation.outputMatrix', delta_name + '.matrixIn[1]')
                edge(delta_name + '.matrixSum', delta_name + 'Euler.inputMatrix')
                replace_input(stem + '_orientConstraint.target[{}].targetRotate'.format(target_index),
                              delta_name + 'Euler.outputRotate')
    replace_input('position1.matrixIn[1]', 'hips_ctrl.worldMatrix[0]')
    if len(samples) > 2:
        for endpoint in ('hips', 'chest'):
            node('composeMatrix', endpoint + '_localRotation', {})
            edge(endpoint + '_ctrl.rotate', endpoint + '_localRotation.inputRotate')
            edge(endpoint + '_ctrl.rotateOrder', endpoint + '_localRotation.inputRotateOrder')
    data['fit_mode'] = 'selection'
    return data
