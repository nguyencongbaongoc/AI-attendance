from app.models.registry import get_model_registry
registry = get_model_registry()
model = registry.get('scrfd')
print(f'Model path: {registry.get_model_path("scrfd")}')
print(f'Model exists: {registry.get_model_path("scrfd").exists()}')