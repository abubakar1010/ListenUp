"""Provider-neutral AI adapter layer (NFR-AI-1, ADR 0009, ADR 0028).

Callers use `gateway.get_gateway()` and the types in `ports`; only grading and transcript
may import this package. Vendor libraries are imported only under `providers/`.
"""
