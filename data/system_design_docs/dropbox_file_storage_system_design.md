# Dropbox/Cloud File Storage System Design

## Overview
A cloud file storage and synchronization service allowing users to store, sync, and share files across multiple devices with real-time updates and version control.

## Core Components

### 1. **API Gateway & Load Balancer**
- Entry point for web, mobile, and desktop clients
- Authentication and authorization
- Request routing (metadata vs file operations)
- Rate limiting per user/account tier

### 2. **Metadata Service**
- File/folder hierarchy (tree structure)
- File metadata (name, size, modified_time, permissions)
- User account information (storage quota, plan)
- Sharing permissions (public links, shared folders)
- Version history tracking
- Database: PostgreSQL/MySQL (sharded by user_id)

### 3. **Block Storage Service**
- File chunking (4 MB blocks)
- Deduplication (same block = same hash, store once)
- Content-addressed storage (hash-based)
- Block metadata mapping (file_id → block_hashes)
- Object storage: S3, GCS, or custom

### 4. **Sync Service**
- Real-time file synchronization across devices
- Conflict resolution (last-write-wins or manual merge)
- Delta sync (only changed blocks, not entire file)
- WebSocket/Long polling for real-time notifications
- Client-side sync daemon (monitors file system changes)

### 5. **Notification Service**
- Notify clients of remote file changes
- WebSocket connections for online clients
- Push notifications for offline clients
- Event queue (Kafka) for async notifications

### 6. **Version Control Service**
- Store file versions (configurable retention: 30 days, 1 year)
- Incremental versioning (only store diffs/blocks)
- Restore previous versions
- Version metadata (timestamp, file size, user)

### 7. **Sharing Service**
- Generate shareable links (public/private)
- Access control (view-only, edit, admin)
- Shared folder management
- Expiration and password protection for links

### 8. **Search Service**
- Full-text search of file names and content
- Elasticsearch or Solr
- Indexing metadata and file content (OCR for images)
- Filter by type, date, folder, shared status

## Database Architecture

### Metadata Database
- **PostgreSQL/MySQL** (sharded by user_id):
  - User accounts (email, plan, storage_used, quota)
  - File metadata (file_id, name, path, size, hash, created_at, modified_at)
  - Folder hierarchy (parent_id, path)
  - Sharing permissions (shared_with, access_level)
  - Version history (version_id, file_id, timestamp, block_hashes)

### Block Metadata
- **Cassandra/DynamoDB** (key-value):
  - Key: block_hash (SHA256)
  - Value: S3 location, size, reference_count
  - Enables deduplication (same file uploaded by different users)

### Caching Layer
- **Redis**:
  - User session data
  - Frequently accessed file metadata
  - Online/offline device status
  - Pending sync operations queue
  - TTL: 15 minutes to 1 hour

### Object Storage
- **S3/Google Cloud Storage**:
  - Encrypted file blocks
  - Geo-replication for durability (99.999999999%)
  - Lifecycle policies (archive old versions to Glacier)
  - CDN integration for fast downloads

## File Chunking & Deduplication

### Why Chunking?
- **Faster Sync**: Upload only changed blocks (delta sync)
- **Deduplication**: Same block = same hash, stored once
- **Bandwidth Optimization**: 1 GB file, 10 MB change = upload 4 MB block only
- **Parallel Upload**: Multiple blocks uploaded concurrently

### Chunking Algorithm
1. Split file into fixed-size blocks (4 MB)
2. Compute hash for each block (SHA256)
3. Check if block exists in system (metadata lookup)
4. Upload only new/changed blocks
5. Update file metadata with block hashes list

### Deduplication Savings
- Same photo uploaded by 100 users = stored once
- OS system files across users = massive savings
- Average deduplication ratio: 30-50% storage reduction

## Synchronization Strategy

### Client-Side Sync Daemon
1. **Monitor File System**: Detect changes (inotify, FSEvents)
2. **Compute Block Hashes**: Identify changed blocks
3. **Upload Changed Blocks**: Send to block storage service
4. **Update Metadata**: Notify metadata service of changes
5. **Notify Other Devices**: Trigger sync on user's other devices

### Conflict Resolution
- **Last Write Wins**: Use timestamps to determine latest version
- **Conflicted Copy**: Create "conflicted copy" if simultaneous edits detected
- **Manual Merge**: User resolves conflicts manually (for critical files)

### Offline Sync
- Queue operations locally when offline
- Sync on reconnection (merge with server state)
- Conflict detection on reconnect

## API Design

### Upload File
```
POST /api/v1/files/upload
Headers: { Authorization: "Bearer <token>" }
Body (multipart):
  - file: <binary>
  - path: "/folder/file.txt"
Response: {
  "file_id": "abc123",
  "name": "file.txt",
  "size": 1048576,
  "hash": "sha256:...",
  "version": 1
}
```

### Download File
```
GET /api/v1/files/{file_id}/download
Response: Binary file stream (with Range support for resume)
```

### List Files
```
GET /api/v1/files?path=/folder
Response: {
  "files": [
    { "name": "doc.pdf", "size": 500000, "modified_at": "..." }
  ]
}
```

### Share File
```
POST /api/v1/shares
Body: { "file_id": "abc123", "access": "view", "expires_at": "2024-12-31" }
Response: { "share_link": "https://dropbox.com/s/xyz789" }
```

## Scaling Strategy

### Horizontal Scaling
- Stateless API servers (easy to scale)
- Database sharding by user_id
- Object storage auto-scales (S3)
- Multiple data centers for geo-distribution

### Caching Strategy
- Metadata in Redis (hot files)
- CDN for popular shared files
- Client-side caching (local file system)
- Prefetch prediction (ML-based)

### Storage Optimization
- Compression before storage
- Cold storage (Glacier) for old versions
- Deduplication at block level
- Lazy deletion (mark deleted, cleanup later)

### Network Optimization
- Delta sync (only changed blocks)
- Compression (gzip, brotli)
- Parallel uploads/downloads (multiple blocks)
- Adaptive transfer speed (based on bandwidth)

## Trade-offs

### Block Size (4 MB)
- **Smaller (1 MB)**: Better deduplication, more metadata overhead
- **Larger (8 MB)**: Less metadata, but worse delta sync efficiency
- **Dropbox Choice**: 4 MB balances both

### Sync Strategy
- **Eager Sync**: Instant sync, high server load
- **Lazy Sync**: Batch sync, lower load but delayed
- **Hybrid**: Real-time for small files, batched for large

### Versioning Retention
- **Unlimited**: Storage cost explosion
- **Limited (30 days)**: Balance between cost and utility
- **Tiered Plans**: Free (30 days), Paid (1 year or unlimited)

## Security Considerations

1. **Encryption at Rest**: AES-256 for stored blocks
2. **Encryption in Transit**: TLS 1.3 for all API calls
3. **Access Control**: OAuth 2.0, token-based auth
4. **Shared Link Security**: UUID-based URLs, expiration, password protection
5. **Audit Logs**: Track file access, sharing, deletions

## Performance Optimizations

1. **LAN Sync**: Directly sync between devices on same network (avoid server)
2. **Smart Sync**: Download file metadata only, fetch content on-demand
3. **Selective Sync**: Users choose folders to sync (save local storage)
4. **Bandwidth Throttling**: Limit upload/download speed to not hog network
5. **Resume Support**: Resumable uploads/downloads (HTTP Range header)

## Capacity Estimates

- **Users**: 500 million active users
- **Storage**: 500 PB total (avg 1 TB per user)
- **Requests**: 10,000 file operations/second
- **Bandwidth**: 1 Gbps per data center (multiple DCs)
- **Metadata**: 500 million users × 10,000 files avg = 5 trillion metadata records

## Key Insights

- Block-level deduplication is critical for storage efficiency
- Delta sync (only changed blocks) saves massive bandwidth
- Conflict resolution is complex (last-write-wins is simplest)
- Object storage (S3) handles durability and replication
- Client-side sync daemon is key to UX (seamless background sync)
- Metadata service is separate from block storage (different access patterns)
