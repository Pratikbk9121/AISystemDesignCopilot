# Google Drive System Design

## Overview
Google Drive is a cloud file storage and sync service that lets users upload, share, and synchronize files across devices, with deduplication, version history, granular permissions, and a hand-off to collaborative editors (Docs/Sheets/Slides). The system must handle massive write/read throughput, sync efficiently over flaky networks, and preserve durability for the long tail.

## Functional Requirements
- Upload, download, organize files and folders.
- Chunked + resumable uploads for large files.
- Sync files across devices (desktop client, mobile, web).
- Share files with users, groups, or via link with permission levels.
- Version history (restore previous versions).
- Search across file content and metadata.
- Hand-off to collaborative editing for Docs/Sheets/Slides.
- Offline access on mobile/desktop.

## Non-Functional Requirements
- Scalability: 1B+ users, exabytes of data.
- Availability: 99.99% for read/write APIs.
- Durability: 11+ nines (multi-region replication, erasure coding).
- Latency: small-file upload < 1s; sync detect < 10s after change.
- Consistency: read-your-writes on metadata; eventual on cross-region.

## Capacity Estimation
- 1B users x 15 GB free + paid -> exabytes of logical data.
- After dedupe + erasure coding, physical storage is a fraction of logical.
- Uploads: ~1B files/day -> ~12K/sec average, 100K/sec peak.
- Sync deltas: clients poll/long-poll on average every few minutes when idle, instant when active.
- Bandwidth: ingress + egress dominated by media files.

## API Design
```
POST /v1/files                        { name, parent_id, mime }
                                      -> { file_id, upload_session_id }
PUT  /v1/uploads/{session}/chunk      Content-Range: bytes start-end/total
POST /v1/uploads/{session}/finish     -> { file_id, version_id, hash }
GET  /v1/files/{id}                   metadata
GET  /v1/files/{id}/content?version=  download (signed URL)
POST /v1/files/{id}/permissions       { principal, role: reader|writer|owner }
GET  /v1/changes?page_token=...       sync delta stream
POST /v1/files/{id}/copy
```

## Data Model
- `files(file_id, owner_id, parent_id, name, mime, size, current_version, created_at, modified_at, trashed)`
- `versions(version_id, file_id, hash, size, created_by, created_at)`
- `chunks(chunk_id, content_hash, size, storage_url, ref_count)` (dedupe table)
- `file_chunks(version_id, seq, chunk_id)` (manifest)
- `permissions(file_id, principal_id, role, inherited_from)`
- `users(user_id, email, quota_used, quota_limit)`
- `changes(user_id, ts, file_id, change_type)` (per-user sync log)

## High-Level Architecture
- Clients: desktop sync app, mobile app, web app.
- Edge: load balancer + API gateway.
- Metadata service: file/folder hierarchy, versions, permissions (Spanner-like strongly consistent store).
- Upload service: resumable session manager.
- Chunk service: content-addressed chunk storage (CAS) with dedupe.
- Object storage backend: Colossus/S3-style with erasure coding.
- Sync service: per-user change log; clients consume deltas.
- Permission service: ACL evaluation + caching.
- Search service: indexes file content (OCR for images, text extraction for docs) and metadata.
- Editor hand-off: when a user opens a Doc/Sheet, control passes to the collaborative editor stack (operational-transform / CRDT-based) - the Drive system stores the persisted blob.
- Storage: Spanner (metadata), Bigtable (change log), object storage (chunks), Bigtable/Elasticsearch (search index).

## Detailed Components

### Chunked Upload & Dedupe
Files are split client-side (or server-side) into chunks (typically 4-8 MiB). Each chunk is hashed (SHA-256 or similar). The client first asks the server which chunk hashes are already present; only missing chunks are uploaded. This dedupes shared files (popular PDFs, photos shared between accounts) and supports resumable uploads - on retry, only missing chunks reupload. The chunk store keeps a single physical copy keyed by content hash with a reference count.

### Versioning
Each save creates a new version pointing at a manifest of chunk_ids. Unchanged chunks are shared with previous versions. Old versions are retained per policy (e.g., 30 days or until storage cap reached). Restore is a metadata operation - the file's `current_version` pointer is updated.

### Sync Across Devices
Each user has a monotonic change log. Clients track a cursor (`page_token`) and pull `/v1/changes?page_token=...` for deltas. For real-time updates, clients hold a long-poll or WebSocket. On change, the client downloads only the changed chunks. A merge resolver handles conflicting edits to the same file (rename to "file (1).docx" on conflict; Docs/Sheets use CRDTs internally so binary-file conflicts are rare).

### Sharing & Permissions
ACLs are stored per file with inheritance from parent folders. Evaluating "can user X read file Y" walks up the inheritance chain. Aggressive caching of ACL decisions in a per-user permission cache makes this fast; cache invalidation is event-driven on permission changes. Link-sharing creates anonymous-principal entries with optional expiry.

### Collaborative Editing Hand-off
Drive stores the persisted file blob; the collaborative editor (Docs/Sheets) runs as a separate service. When opened, the editor service loads the document, accepts concurrent edits via CRDTs or operational transformation, and periodically snapshots back to Drive as a new version. The editor service owns conflict resolution; Drive sees only finalized writes.

### Search
A pipeline extracts text from common formats (PDF, Office, HTML), OCRs images, and indexes both content and metadata (filename, owner, modified date) into a per-user shard. Permission filtering at query time enforces ACLs.

## Trade-offs
- Spanner (strong, global, expensive) for metadata vs cheaper eventual stores: metadata correctness is too important to be eventual (renames, moves, permissions).
- Client-side chunking + dedupe vs server-side: client-side saves upload bandwidth at the cost of client complexity.
- Per-version full manifest vs delta encoding: manifests are simpler; chunk-level sharing already provides "free" deltas for unchanged regions.
- Operational transform vs CRDTs for collaborative editing: CRDTs are simpler to distribute; OT historically used by Docs.
- Polling vs push for sync: hybrid - long-poll/WebSocket when active, periodic poll when idle.

## Failure Modes & Mitigations
- Upload session loss: client checkpoints local progress; can resume against a new session if the original expires.
- Chunk store unavailability: writes queue, reads serve from replicas in other AZs.
- Metadata service partition: writes block (correctness over availability); reads serve from replicas.
- Permission cache staleness after share revocation: invalidation events propagate via Kafka; worst-case window is bounded by TTL.
- Quota exhaustion: client receives 403 with clear remediation; sync continues for deletes/downloads.
- Conflicting edits to binary file: create "(1)" copy and notify both users.

## Key Insights
- Content-addressed chunk storage gives dedupe and resumable upload "for free."
- Sync is a delta stream problem, not a full-state diff problem - per-user change logs with cursors are the canonical design.
- Strong consistency on metadata (renames, moves, permissions) is non-negotiable; users will not tolerate visible inconsistencies.
- Collaborative editing is a separate stack (OT/CRDT) that hands off to Drive only for persistence.
- ACL evaluation with inheritance is the slowest path; cache it aggressively with event-driven invalidation.
