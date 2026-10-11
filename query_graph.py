import json
with open('graphify-out/graph.json') as f:
    g = json.load(f)

# Find DecoderBackend nodes
for node in g['nodes']:
    label = node.get('label', '')
    if 'DecoderBackend' in label or 'PyNvVideoCodec' in label or 'PyAVNVDEC' in label:
        print('Node: {} - {}'.format(node['id'], label))

# Find edges between decoder backends
for edge in g['edges']:
    source = edge['source']
    target = edge['target']
    source_label = next((n.get('label', '') for n in g['nodes'] if n['id'] == source), source)
    target_label = next((n.get('label', '') for n in g['nodes'] if n['id'] == target), target)
    if any(kw in source_label for kw in ['DecoderBackend', 'PyNvVideoCodec', 'PyAVNVDEC']) or any(kw in target_label for kw in ['DecoderBackend', 'PyNvVideoCodec', 'PyAVNVDEC']):
        print('Edge: {} -> {}'.format(source_label, target_label))