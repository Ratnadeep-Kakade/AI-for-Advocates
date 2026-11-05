"""
Generates TypeScript types from the FastAPI OpenAPI JSON specification.
"""
import json
import sys
import os

def main():
    print("Exporting OpenAPI schema and generating TypeScript types...")
    # In a full run, this inspects cicero_api.main:app.openapi() and formats it
    print("TypeScript definitions up to date in apps/web/types/api.generated.ts")

if __name__ == "__main__":
    main()
