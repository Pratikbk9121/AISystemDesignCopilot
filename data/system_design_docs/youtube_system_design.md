# YouTube System Design

## Overview
YouTube is a user-generated video platform supporting upload, transcoding, global distribution, search, comments, monetization, live streaming, and ML-driven recommendations. The system must ingest hundreds of hours of video per minute, serve billions of views per day with low rebuffer rates, and moderate content at planetary scale.

## Functional Requirements
- Upload videos with progress, resumability, and large-file support.
- Transcode to multiple resolutions and codecs for adaptive streaming.
- Stream VOD with adaptive bitrate (DASH/HLS) on web/mobile/TV.
- Search videos, channels, playlists.
- Recommend videos on home, watch-next, and shorts feed.
- Comments, likes, subscriptions, notifications.
- Live streaming (RTMP ingest) with DVR.
- Content moderation (copyright, policy violations) and monetization (ads).

## Non-Functional Requirements
- Scalability: ~2.5B MAU, ~500h uploaded/min, ~1B hours watched/day.
- Availability: 99.99% playback start; serving from cache when origin is down.
- Latency: video start < 2s; live glass-to-glass < 5s; recommendations < 200ms.
- Durability: master upload retained on multi-region object storage indefinitely.
- Cost: bandwidth and storage dominate - encoding efficiency matters.

## Capacity Estimation
- 500h/min upload -> ~30K min/min = 30K hours/hour ingested.
- Average upload ~500MB raw -> ~500TB/day raw, ~5PB/day after transcoding ladder.
- Watch traffic: ~1B hours/day, avg 2 Mbps -> ~200 Tbps egress peak.
- Comments: ~50M/day -> ~600/sec average, ~10K/sec peak.
- Search QPS: ~50K/sec.

## API Design
```
POST /v1/uploads                     resumable session, returns upload_url
PUT  /v1/uploads/{session}/chunks    chunked upload (8 MiB)
POST /v1/videos                      { upload_id, title, description, tags, visibility }
GET  /v1/videos/{id}                 metadata + manifest URL
GET  /v1/videos/{id}/manifest.mpd    DASH manifest
GET  /v1/watch-next?video_id=...     ranked next-up
POST /v1/videos/{id}/comments
POST /v1/live/streams                returns RTMP ingest URL + stream_key
```

## Data Model
- `videos(video_id, channel_id, title, description, visibility, status, duration, created_at)`
- `channels(channel_id, owner_id, name, subscriber_count)`
- `assets(asset_id, video_id, codec, resolution, bitrate, storage_url, drm_key_id)`
- `views(video_id, ts, user_id, watch_ms, device, country)` (column store)
- `comments(comment_id, video_id, author_id, text, parent_id, ts, like_count)`
- `subscriptions(subscriber_id, channel_id, notify_on_upload, created_at)`
- `recommendations(user_id, candidate_ids[], scores[], generated_at)`

## High-Level Architecture
- Edge: global LB, QUIC/HTTP3, anti-abuse, auth.
- Upload service: chunked, resumable, virus-scan, hash-dedupe.
- Transcoding pipeline (MapReduce-style): split video, transcode chunks in parallel, package.
- Storage: master in Spanner/Colossus-like object store; transcoded variants on edge caches.
- CDN: Google's Edge Cache nodes embedded in ISPs (analogous to Open Connect).
- Metadata: Spanner (global, strongly consistent) for video metadata; Bigtable for views.
- Search: index in inverted-index service (Elasticsearch / proprietary).
- Recommendation: candidate generation (collaborative filtering) + ranking (deep nets).
- Comments service backed by sharded SQL with Bigtable for replies.
- Live: RTMP ingest -> low-latency transcode -> HLS/LL-HLS to CDN.
- Moderation: Content ID (audio/video fingerprinting) + classifier pipeline.

## Detailed Components

### Upload Pipeline
Clients negotiate a resumable upload session and PUT chunks to the upload service, which streams them into object storage. After completion, the system computes a perceptual hash (for dedupe and Content ID), validates container/codec, and enqueues a transcoding job. Uploads can be made visible immediately at a single resolution while higher rungs are still encoding.

### Transcoding
A scheduler splits source video into GOP-aligned chunks (typically 2-10s). Workers transcode chunks in parallel on a fleet of preemptible VMs and produce a ladder: 144p, 240p, 360p, 480p, 720p, 1080p, 1440p, 2160p across H.264, VP9, AV1. Per-shot/per-title optimization (similar to Netflix) selects bitrates that hit a perceptual quality target with minimum bytes. The packager produces DASH and HLS manifests.

### Adaptive Streaming
Players fetch a DASH/HLS manifest and pick a rung based on measured throughput and buffer level. Initial rung is chosen from device class and historical network. Segments are 2-6s; smaller for live (LL-HLS uses sub-second partial segments).

### Recommendation System
A two-stage funnel: (1) candidate generation reduces the corpus of billions of videos to a few hundred per user using collaborative filtering and embedding nearest-neighbor lookup; (2) ranking scores candidates with a deep neural net predicting watch-time, satisfaction, and survey-based engagement signals. Features include user history embeddings, video embeddings, freshness, language, and contextual signals (time, device).

### Comment System
Comments are sharded by video_id. Top-level comments and replies live in separate tables. A ranker reorders comments by relevance (likes, replies, recency, toxicity). Spam and harassment are filtered by a real-time classifier pipeline; flagged comments hide pending review.

### Live Streaming
Creators push RTMP/SRT to an ingest endpoint. A low-latency transcoder produces an HLS ladder with short segments (or LL-HLS chunks). Manifests are pushed to CDN with short cache TTLs. DVR is supported by retaining recent segments in object storage. Latency target: < 5s glass-to-glass for low-latency mode.

### Content Moderation
Content ID fingerprints uploaded audio/video and compares against a database of copyrighted reference assets; matches trigger claim or block. Classifier pipelines flag policy violations (violence, hate, CSAM via PhotoDNA/hash matching). Human reviewers handle edge cases and appeals.

## Trade-offs
- Storing master vs regenerating: masters are required for re-encoding to new codecs (AV1 rollout) - retain them.
- Spanner (strong, expensive) for metadata vs Bigtable (cheap, eventual) for views: pick per workload.
- Latency vs efficiency in live: low-latency mode uses more CDN cache churn.
- Push notifications on every upload vs digest: per-channel preference - default off for noisy channels.
- Recommend exploration vs exploitation: too much exploitation creates filter bubbles; bandits introduce exploration.

## Failure Modes & Mitigations
- Transcoding queue backlog: scale up preemptible fleet; prioritize new + monetized videos.
- CDN edge full: steering directs to peer edge; client multi-CDN failover.
- Search index lag: serve from stale index with a freshness banner.
- Upload corruption: per-chunk checksums + reupload missing chunks.
- Live ingest drop: client reconnects to RTMP endpoint; transcoder tolerates short gaps.
- Recommendation model regression: instant rollback via experiment flag; fall back to popular-in-country.

## Key Insights
- Chunked parallel transcoding is the only way to keep up with ingest.
- Two-stage candidate-generation + ranking is the canonical recommendation architecture.
- Edge cache embedded in ISPs is essential at YouTube's egress scale.
- Content ID is both a moderation tool and a business mechanism (revenue sharing).
- LL-HLS / LL-DASH brought live latency from 30s down to 3-5s without abandoning HTTP CDN economics.
