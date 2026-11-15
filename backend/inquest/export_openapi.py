"""Write a stable OpenAPI snapshot to stdout."""

import json

from inquest.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2, sort_keys=True))
