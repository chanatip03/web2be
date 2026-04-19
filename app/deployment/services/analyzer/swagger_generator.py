from typing import Any, Dict, List
from app.deployment.services.analyzer.code_parser import APIEndpoint

def generate_openapi_spec(endpoints: List[APIEndpoint], project_name: str = "Project API") -> Dict[str, Any]:
    """Generate a basic OpenAPI 3.0.0 specification from a list of APIEndpoints."""
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": project_name,
            "version": "1.0.0",
            "description": "Auto-generated API documentation from source code analysis."
        },
        "paths": {}
    }

    if not endpoints:
        # Avoid empty Swagger UI by adding a default root path if no endpoints detected
        spec["paths"]["/"] = {
            "get": {
                "summary": "Root Endpoint",
                "description": "Default entry point (auto-generated as no specific routes were detected).",
                "responses": {"200": {"description": "OK"}}
            }
        }
        return spec

    for ep in endpoints:
        # Support both APIEndpoint objects and Pydantic-dict representation
        if isinstance(ep, dict):
            path = ep.get("path", "/")
            method = ep.get("method", "GET").lower()
            func_name = ep.get("function_name", "endpoint")
            path_params = ep.get("path_params", [])
            query_fields = ep.get("query_fields", [])
            body_fields = ep.get("body_fields", [])
        else:
            path = ep.path
            method = ep.method.lower()
            func_name = ep.function_name
            path_params = ep.path_params
            query_fields = ep.query_fields
            body_fields = ep.body_fields

        if not path.startswith("/"):
            path = "/" + path
        
        # Normalize path params from different frameworks to OpenAPI format {param}
        # e.g. /albums/:id -> /albums/{id}
        import re
        path = re.sub(r':([a-zA-Z0-9_]+)', r'{\1}', path)

        if path not in spec["paths"]:
            spec["paths"][path] = {}

        operation = {
            "summary": func_name,
            "responses": {
                "200": {
                    "description": "Successful response"
                }
            }
        }

        # Add parameters
        params = []
        for p in path_params:
            params.append({
                "name": p,
                "in": "path",
                "required": True,
                "schema": {"type": "string"}
            })
        for p in query_fields:
            params.append({
                "name": p,
                "in": "query",
                "required": False,
                "schema": {"type": "string"}
            })
        
        if params:
            operation["parameters"] = params

        # Add request body if applicable
        if method in ["post", "put", "patch"] and body_fields:
            operation["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                field: {"type": "string"} for field in body_fields
                            }
                        }
                    }
                }
            }

        spec["paths"][path][method] = operation

    return spec
