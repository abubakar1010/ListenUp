# ADR 0012: SeaweedFS for local S3 storage

- Status: Accepted
- Date: 2026-10-03

## Context

The architecture named MinIO for local S3-compatible storage. MinIO images are no longer published on Docker Hub, so `docker compose up` could not pull them.

## Decision

Use SeaweedFS (`chrislusf/seaweedfs`) with its S3 gateway on port 9000 for local development. A one-off Compose service creates the `listenup` bucket.

## Consequences

Local development keeps a working S3 API. The application talks only to the S3 API (ADR 0005), so production can use any S3-compatible provider and tests are unaffected.
