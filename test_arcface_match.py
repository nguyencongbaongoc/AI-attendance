import numpy as np
import cv2
from app.vision.arcface_inference import create_arcface_inference
from app.models.registry import get_model_registry
from app.vision.enrollment import EnrollmentDatabase

registry = get_model_registry()
arcface = create_arcface_inference(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'], registry=registry)
print(f'ArcFace provider: {arcface.provider_used}')

# Load enrollment database
enrollment = EnrollmentDatabase()
enrollment.load('data/embeddings.npy', 'data/embeddings.npy.metadata.json')
print(f'Enrolled identities: {list(enrollment.metadata.keys())}')

# Test with real face image
img = cv2.imread('photo_realistic_face.jpg')
aligned = cv2.resize(img, (112, 112))

result = arcface.infer(aligned)
print(f'Test face embedding norm: {np.linalg.norm(result.normalized_embedding.flatten()):.10f}')

# Compare with enrolled identities
emb = result.normalized_embedding.flatten()
for person_id, meta in enrollment.metadata.items():
    enrolled_emb = np.array(meta['embedding'], dtype=np.float32)
    enrolled_emb = enrolled_emb / np.linalg.norm(enrolled_emb)
    sim = np.dot(emb, enrolled_emb)
    name = meta.get('name', 'Unknown')
    print(f'  {person_id} ({name}): cosine similarity = {sim:.4f}')

# Check if any match threshold
threshold = 0.6
best_match = None
best_sim = -1
for person_id, meta in enrollment.metadata.items():
    enrolled_emb = np.array(meta['embedding'], dtype=np.float32)
    enrolled_emb = enrolled_emb / np.linalg.norm(enrolled_emb)
    sim = np.dot(emb, enrolled_emb)
    if sim > best_sim:
        best_sim = sim
        best_match = person_id
        
print(f'Best match: {best_match} with similarity {best_sim:.4f}')
if best_sim >= threshold:
    print(f'MATCH: {best_match} (threshold={threshold})')
else:
    print(f'NO MATCH (threshold={threshold})')