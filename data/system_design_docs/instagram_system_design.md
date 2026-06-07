# Instagram System Design

## Overview
Instagram is a photo- and video-sharing social platform with feeds, stories, reels, and direct messaging. It must ingest media at massive scale, serve a personalized feed with sub-second latency, support short-form video discovery, and grow social graph operations to billions of edges.

## Functional Requirements
- Users post photos, videos, carousels, stories (24h ephemeral), and reels (short video).
- Follow/unfollow users and see a personalized home feed.
- Like, comment, save, and share posts.
- Direct messaging (DMs) with text, media, and reactions.
- Search users, hashtags, and places.
- Explore page with ML-ranked discovery content.
- Notifications for likes, comments, follows, mentions.

## Non-Functional Requirements
- Scalability: ~2B MAU, ~500M DAU, ~100M posts/day, ~5B feed reads/day.
- Availability: 99.99% for read paths; writes can degrade to async if needed.
- Latency: feed load p99 < 500ms; image first byte from CDN < 100ms.
- Durability: original media kept forever; thumbnails regenerable.
- Eventual consistency acceptable for counters (likes/views).

## Capacity Estimation
- 100M posts/day, avg ~2MB after compression -> 200TB/day raw media.
- After thumbnails and multiple sizes -> ~500TB/day delivered to storage.
- Feed reads: 5B/day -> ~60K reads/sec average, ~300K peak.
- Likes/comments: ~1B/day -> ~12K writes/sec.
- Social graph: ~200B edges (follow relations).

## API Design
```
POST /v1/media                       multipart upload, returns media_id
POST /v1/posts                       { media_ids, caption, location, tags }
GET  /v1/feed?cursor=...             personalized home feed
GET  /v1/users/{id}/posts
POST /v1/posts/{id}/like
POST /v1/posts/{id}/comment
GET  /v1/stories?cursor=...
POST /v1/dm/threads/{id}/messages
GET  /v1/explore                     ML-ranked discovery
```
Mobile clients use HTTP/2 + gRPC for chatty calls; uploads use resumable chunked PUT.

## Data Model
- `users(user_id, username, bio, avatar_url, privacy, created_at)`
- `posts(post_id, author_id, caption, media_ids[], created_at, location, like_count, comment_count)`
- `media(media_id, type, original_url, variants[], width, height, duration)`
- `follows(follower_id, followee_id, created_at)`
- `likes(post_id, user_id, ts)`
- `comments(comment_id, post_id, author_id, text, ts, parent_id)`
- `stories(story_id, author_id, media_id, expires_at)`
- `feed_cache(user_id, post_id, score, generated_at)` (Redis)

## High-Level Architecture
- Mobile/web clients -> edge LB -> API gateway.
- Posting service handles upload, validation, thumbnail kickoff.
- Media service: ingest -> transcode (FFmpeg fleet) -> store to S3/blob -> push to CDN.
- Feed service: ranking + fan-out coordination.
- Social graph service backed by sharded MySQL (TAO-style cache).
- Counter service (likes, views) backed by sharded counters with async aggregation.
- Notification service consumes Kafka events from posting/likes.
- Explore/Reels ranking pipeline (offline candidate generation + online ranker).
- Storage: MySQL (users, posts metadata), Cassandra (DMs, stories), S3 (media), Redis (feed cache, sessions), Elasticsearch (search).

## Detailed Components

### Media Upload & CDN
The client requests a presigned URL and uploads chunks directly to blob storage, bypassing app servers. A worker then transcodes images into multiple sizes (thumb, low, high) and videos into HLS/DASH ladders. Variants are pushed to a multi-tier CDN (Akamai, Fastly, Meta's own edge). Image URLs are content-addressed for cache-friendliness.

### Feed Generation: Fan-out
- **Fan-out-on-write (push)**: when a user posts, the post is written to each follower's feed-cache list in Redis. Cheap reads, expensive writes for users with millions of followers.
- **Fan-out-on-read (pull)**: read time, fetch recent posts from each followee and merge. Cheap writes, expensive reads for users following many.
- **Hybrid (Instagram's choice)**: push for normal accounts; pull for celebrities/large accounts. The feed service merges pushed entries with pulled celebrity posts at read time, then re-ranks via ML.

### Feed Ranking
Candidate posts (last 48h from follows) are scored by a multi-task neural net predicting probability of like, comment, share, dwell time, and "negative" actions like report. Features: author affinity, recency, media type, engagement velocity, user embedding. Online ranking uses a feature store and a low-latency model server; offline training runs daily on user logs.

### Stories
Stories are stored with a 24h TTL. Each user maintains a ring of stories; the home tray shows followed users with unseen stories first. Views are recorded for the author. Because stories expire, storage uses TTL'd Cassandra rows; CDN cache TTLs match story TTL.

### Reels (Short Video Discovery)
Reels has its own discovery feed driven by content-based and collaborative-filtering models. Candidate generation pulls from recent reels, hashtag matches, and creator follows. Watch-time and completion rate are the key training labels. Reels exploit a large item pool (vs follow-graph posts), so ranking models are tuned for exploration.

### Direct Messaging
DMs run on a separate messaging stack (Cassandra-backed mailbox per user, fan-out to participant inboxes). WebSocket gateways hold persistent connections for online delivery; offline users get pushes via APNs/FCM.

## Trade-offs
- Fan-out-on-write vs read: write-time fan-out kills the celebrity problem (Justin Bieber problem); hybrid resolves it.
- SQL (sharded MySQL) for graph + posts vs graph DB: MySQL with TAO-style caches won for write throughput and operational maturity.
- Strong consistency on like counters vs eventual: eventual with periodic reconciliation - users tolerate +/-1 like.
- Push notifications via APNs/FCM vs in-app polling: push wins for engagement.
- Storing every variant vs regenerating: store hot variants, regenerate cold on demand.

## Failure Modes & Mitigations
- Upload service overload: presigned-URL pattern offloads bytes to S3 directly.
- Feed-cache miss storm: tiered cache + request coalescing; fall back to pull mode.
- Ranking model server slow: bypass with simple recency-based ranking ("safe mode").
- Celebrity post fan-out spike: post enters pull-path so cache writes don't stampede.
- CDN region failure: DNS-based steering to backup CDN; client retries on 5xx.
- Hot hashtag overload: cap inserts per second to that index; shed to async aggregation.

## Key Insights
- Hybrid fan-out is the standard answer for skewed social graphs.
- Direct-to-blob uploads via presigned URLs are essential at this scale.
- Ranking ML is the product - chronological feeds were abandoned for a reason.
- Counter aggregation must be eventual; exact counts are too expensive at scale.
- A multi-tier CDN with content-addressed URLs maximizes cache hit ratio.
