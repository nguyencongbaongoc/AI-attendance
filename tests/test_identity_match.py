import numpy as np
from app.vision.matching import load_matching_database, match_identity
from app.vision.enrollment import load_enrollment_database

# Load database
embeddings, metadata = load_enrollment_database('data/enrollment_db')
print(f'Embeddings shape: {embeddings.shape}')
print(f'Person IDs: {metadata.person_ids}')
print(f'Embedding count: {metadata.embedding_count}')

# Check similarities between all embeddings
print('\nPairwise similarities:')
for i in range(embeddings.shape[0]):
    for j in range(i+1, embeddings.shape[0]):
        sim = np.dot(embeddings[i], embeddings[j])
        prov_i = metadata.sample_provenance[i]
        prov_j = metadata.sample_provenance[j]
        print(f'  {prov_i["sample_id"]} ({prov_i["person_id"]}) vs {prov_j["sample_id"]} ({prov_j["person_id"]}): {sim:.10f}')

# Now test matching with the first embedding (should match HS001)
context = load_matching_database('data/enrollment_db')
query = embeddings[0]  # First embedding of HS001
result = match_identity(query, context)
print(f'\nMatch result:')
print(f'  status: {result.status}')
print(f'  person_id: {result.person_id}')
print(f'  similarity: {result.similarity}')
print(f'  threshold: {result.threshold}')
print(f'  ambiguity_margin: {result.ambiguity_margin}')
print(f'  candidate_count: {result.candidate_count}')
print(f'  provenance decision: {result.provenance.get("decision")}')
print(f'  best_person_id: {result.provenance.get("best_person_id")}')
print(f'  best_person_similarity: {result.provenance.get("best_person_similarity")}')
if 'all_person_matches' in result.provenance:
    for p in result.provenance['all_person_matches']:
        print(f'    {p["person_id"]}: {p["best_similarity"]:.10f}')