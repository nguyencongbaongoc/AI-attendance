import sys
sys.path.insert(0, '.')
from app.main import app

routes = []
for route in app.routes:
    methods = getattr(route, 'methods', None)
    path = getattr(route, 'path', None)
    name = getattr(route, 'name', None)
    if path:
        routes.append((list(methods) if methods else ['WS'], path, name))

routes.sort(key=lambda x: x[1])
for m, p, n in routes:
    print(f"{','.join(m):<15} {p:<45} {n}")

