import sys
sys.path.insert(0, 'C:/Users/Nguyen Cong Thong/Desktop/AI attendance')
from app.models.registry import get_model_registry
registry = get_model_registry()
print(f'Model path: {registry.get_model_path("scrfd")}')
print(f'Model exists: {registry.get_model_path("scrfd").exists()}')