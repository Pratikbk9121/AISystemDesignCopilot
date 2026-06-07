# Slack System Design

## Overview
Slack is a real-time team messaging platform with channels, direct messages, threads, file sharing, search, and an extensive integration ecosystem. It must deliver messages with sub-second latency, scale per-workspace, support persistent message history, and handle bursty fan-out (e.g., @channel in a 50K-member workspace).

## Functional Requirements
- Send/receive messages in channels, group DMs, and 1:1 DMs in real time.
- Threads for replies under a parent message.
- File uploads (images, videos, docs).
- Full-text search across messages and files.
- Presence indicators (active/away/offline).
- Notifications (in-app, push, email).
- Workspace administration: users, channels, roles.
- Integrations: webhooks, slash commands, bots.

## Non-Functional Requirements
- Scalability: ~20M+ DAU, ~200K paid workspaces, largest workspaces have 500K+ users.
- Availability: 99.99% for message send + receive.
- Latency: end-to-end message delivery p99 < 500ms.
- Durability: messages retained per workspace retention policy.
- Consistency: messages must arrive in causal order within a channel.

## Capacity Estimation
- 20M DAU sending ~50 messages/day -> 1B messages/day, ~12K/sec average, ~100K/sec peak.
- Concurrent WebSocket connections: ~10M.
- Storage: avg message ~1KB -> 1TB/day raw; plus files at ~10TB/day.
- Search index: full-text on all retained messages, multi-PB.

## API Design
```
WebSocket  wss://wss-mcp.slack.com    persistent connection
  events: message, presence_change, channel_marked, typing

POST /api/chat.postMessage           { channel, text, thread_ts }
POST /api/files.upload               multipart
GET  /api/conversations.history      paginated message history
GET  /api/search.messages?query=...
POST /api/conversations.create
POST /api/users.setPresence
```

## Data Model
- `workspaces(workspace_id, plan, domain, retention_days)`
- `users(user_id, workspace_id, email, name, status, tz)`
- `channels(channel_id, workspace_id, name, type, created_by, is_private)`
- `memberships(user_id, channel_id, last_read_ts, notification_pref)`
- `messages(workspace_id, channel_id, ts, user_id, text, attachments, thread_ts)`
- `files(file_id, workspace_id, uploader_id, size, mime, storage_url)`
- `mentions(user_id, channel_id, message_ts, kind)`

## High-Level Architecture
- Mobile/desktop/web clients use WebSocket for real-time + HTTP for control plane.
- WebSocket Message Gateways (wsmcp/flannel) hold persistent connections.
- Message service: validates, persists, fans out.
- Channel service: membership and ACLs.
- Search: Elasticsearch with per-workspace shards.
- File service: presigned-URL uploads to S3-compatible storage; thumbnails via async pipeline.
- Notification service: APNs/FCM/email orchestration.
- Presence service: in-memory store of user-connection mapping (Redis).
- Storage: MySQL/Vitess (messages metadata + memberships), Solr/Elasticsearch (search), S3 (files), Redis (presence, hot caches), Kafka (fan-out backbone).

## Detailed Components

### WebSocket Fan-out
On login, the client opens a WebSocket to a gateway. The gateway registers the user's active channel set in a presence cache. When a message is sent, the message service writes to MySQL/Vitess (sharded by workspace), then publishes a `channel.message` event to Kafka. Gateways subscribe to events for channels their connected users care about (channel-affinity routing) and push the event over the WebSocket. For very large channels, fan-out happens via a tree of relays to avoid hot-spotting a single Kafka partition.

### Message Storage
Messages are partitioned by workspace, then sharded by channel. Each message uses a millisecond timestamp + counter as its `ts` (effectively the message ID and ordering key). Older messages are tiered to colder storage; recent N days stay hot. Retention is enforced per workspace policy via a background sweeper.

### Threads
A reply has `thread_ts = parent.ts`. Threads are queryable as a sub-conversation. Unread state per thread is tracked per user. Channel reads do not auto-mark thread replies as read - users follow threads explicitly.

### Search
Each workspace has dedicated Elasticsearch shards (multi-tenancy by shard). Indexing happens asynchronously after message persist. ACL filtering is applied at query time (the searcher must be a member of the channel). File content is OCR/extract-indexed for searchability.

### Presence
A user is "active" if at least one WebSocket is connected and the client reports activity in the last few minutes. Presence is a Redis hash keyed by user_id; gateways maintain TTLs via heartbeats. Presence changes are broadcast only to interested users (DM partners, shared channel members) to avoid global gossip storms.

### File Uploads
Client requests a presigned URL and PUTs directly to object storage. After upload, the file service generates thumbnails (images), previews (PDFs), and OCR text (for search). Files inherit the channel's ACL.

### Notifications
A consumer subscribes to message + mention events. For each recipient who is not active, push notification builders fire APNs/FCM messages; deeply offline users receive email digests. User preferences (DND hours, channel-level overrides) gate every send.

## Trade-offs
- Vitess (sharded MySQL) vs single SQL: workspace cardinality forces sharding; per-workspace isolation is also a security feature.
- Per-workspace Elasticsearch shards vs shared index: dedicated shards isolate noisy neighbors and simplify retention/deletion.
- WebSocket gateway with channel-affinity vs random routing: affinity reduces cross-gateway chatter at the cost of more complex placement.
- Send-time fan-out vs read-time fetch: send-time wins for real-time feel; expensive @channel uses controlled fan-out trees.
- Strong consistency on channel membership (you must be a member to see a message) vs cached membership: ACL checks at fan-out time use a freshly-validated cache.

## Failure Modes & Mitigations
- Gateway loss: client reconnects to a new gateway; resumes via `last_seen_ts` for missed messages (catch-up via HTTP).
- Kafka lag: fan-out backpressures; UI shows "syncing" but does not lose data (messages remain in DB).
- Search index outage: search returns degraded (recent-only) results; full reindex from message store available.
- File storage outage: uploads queued client-side; downloads degrade to "unavailable, retrying."
- Workspace shard hotspot: rebalance via Vitess resharding; rate-limit pathological bots.
- Notification storm (incident @channel in huge workspace): rate-limit @channel/@here; require admin approval for very large channels.

## Key Insights
- WebSocket gateways with channel-affinity routing are essential for cost-efficient fan-out.
- Multi-tenant Elasticsearch with dedicated per-workspace shards isolates blast radius.
- Threads are a small data-model addition but a major UX shift - design history reads to support thread-aware unread state.
- Presigned-URL uploads scale better than proxied uploads for files.
- @channel in a 50K-user workspace is a real DoS vector and needs admin gating + rate limits.
