import json
from pathlib import Path

# Check enrollment databases
for db_name in ['enrollment_db', 'enrollment_db_1', 'enrollment_db_2']:
    meta_path = Path(f'data/{db_name}/embeddings.npy.metadata.json')
    if meta_path.exists():
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        print(f'{db_name}:')
        print(f'  sample_count: {meta.get("sample_count")}')
        print(f'  unique_persons: {meta.get("unique_persons")}')
        print(f'  model: {meta.get("model")}')
        print(f'  created_at: {meta.get("created_at")}')
        if 'sample_provenance' in meta:
            persons = set()
            for prov in meta['sample_provenance']:
                persons.add(prov.get('person_id'))
            print(f'  person_ids: {sorted(persons)}')
        print()