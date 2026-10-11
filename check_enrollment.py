import numpy as np
import json

embeddings = np.load('data/embeddings.npy')
print(f'Embeddings shape: {embeddings.shape}')
print(f'First embedding: {embeddings[0][:5]}')

with open('data/embeddings.npy.metadata.json', 'r') as f:
    metadata = json.load(f)
print(f'Metadata keys: {metadata.keys()}')
print(f'Person IDs: {metadata.get("person_ids", [])}')
print(f'Sample provenance length: {len(metadata.get("sample_provenance", []))}')