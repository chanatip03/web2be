import ast
import os

def find_fastapi_apps(project_path: str):
    apps = []

    for root, _, files in os.walk(project_path):
        for file in files:
            if not file.endswith(".py"):
                continue

            path = os.path.join(root, file)
            rel = os.path.relpath(path, project_path)

            try:
                tree = ast.parse(open(path).read())
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Call):
                        if getattr(node.value.func, "id", "") == "FastAPI":
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    module = rel.replace("/", ".").replace(".py", "")
                                    apps.append(f"{module}:{target.id}")

    return apps
