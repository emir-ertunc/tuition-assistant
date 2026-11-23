"""Downloads the openapi.json of the api and makes it ready for the APIM import.

1. In APIM the api is created with the path "api/v1", so the operations must not start with
   /api/v1 again (otherwise the public url would be /api/v1/api/v1/...). Routes outside /api/v1
   (like /health) are left out, they are not published on the gateway.
2. FastAPI writes OpenAPI 3.1, the APIM import expects 3.0. The few 3.1 things FastAPI uses
   are changed to the 3.0 way:
     "exclusiveMinimum": 0             -> "minimum": 0, "exclusiveMinimum": true
     "anyOf": [{X}, {"type": "null"}]  -> X + "nullable": true
     "examples": [a, b] (in a schema)  -> "example": a

usage: python prepare_openapi.py <api base url> <output file>
"""

import json
import sys
import urllib.request

PREFIX = "/api/v1"


def to_openapi_30(node):
    if isinstance(node, list):
        return [to_openapi_30(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = {key: to_openapi_30(value) for key, value in node.items()}

    for bound, plain in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        if isinstance(node.get(bound), (int, float)) and not isinstance(node.get(bound), bool):
            node[plain] = node[bound]
            node[bound] = True

    any_of = node.get("anyOf")
    if isinstance(any_of, list) and any(s == {"type": "null"} for s in any_of):
        rest = [s for s in any_of if s != {"type": "null"}]
        node.pop("anyOf")
        if len(rest) == 1:
            node.update(rest[0])
        else:
            node["anyOf"] = rest
        node["nullable"] = True

    # inside schemas 3.1 has a list "examples", 3.0 has one "example"
    # (parameter/media "examples" are a map, those are left as they are)
    if isinstance(node.get("examples"), list):
        examples = node.pop("examples")
        if examples:
            node["example"] = examples[0]

    return node


def main():
    base_url, out_file = sys.argv[1].rstrip("/"), sys.argv[2]
    with urllib.request.urlopen(f"{base_url}/openapi.json", timeout=60) as response:
        spec = json.load(response)

    spec["paths"] = {
        path[len(PREFIX):]: operations
        for path, operations in spec["paths"].items()
        if path.startswith(PREFIX + "/")
    }
    spec.pop("servers", None)  # APIM sets its own service url
    spec = to_openapi_30(spec)
    spec["openapi"] = "3.0.3"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    print(f"{len(spec['paths'])} paths written to {out_file} (openapi 3.0.3)")


if __name__ == "__main__":
    main()
