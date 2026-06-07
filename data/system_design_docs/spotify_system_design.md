# Spotify System Design

## Overview
Spotify is a global audio streaming service spanning music, podcasts, and audiobooks. It must serve audio with near-instant playback, generate personalized playlists like Discover Weekly, support social features, and accurately attribute plays for royalty payouts.

## Functional Requirements
- Stream music and podcasts on demand with adaptive bitrate.
- Browse, search, and discover via personalized recommendations.
- Manage playlists (personal, collaborative, algorithmic like Discover Weekly).
- Offline downloads on mobile.
- Social features: follow friends, share songs, see what others are playing.
- Podcast subscriptions and episode management.
- Royalty tracking: precise per-stream attribution to artists/labels.

## Non-Functional Requirements
- Scalability: ~600M MAU, ~250M Premium, ~100M+ tracks, billions of plays/day.
- Availability: 99.95% playback; download-and-play offline tolerance for outages.
- Latency: play-tap to first audio chunk < 200ms p95.
- Durability: audio masters + play logs durable for royalty audits.
- Cost: bandwidth dominates - aggressive caching and compression matter.

## Capacity Estimation
- 600M MAU, ~30M concurrent listeners at peak.
- Average track ~3.5 MB at 160 kbps Ogg Vorbis -> ~10 PB catalog (multiple bitrates).
- Plays/day: ~5B -> ~60K/sec average, 200K/sec peak.
- Catalog: ~100M tracks + ~5M podcasts.
- Royalty events: every play of 30s+ generates an attributable event, billions/day.

## API Design
```
GET  /v1/tracks/{id}                 metadata
GET  /v1/tracks/{id}/stream          returns CDN URL + audio manifest
POST /v1/play/start                  { track_id, context_uri }
POST /v1/play/heartbeat              { position_ms, bitrate }
POST /v1/play/end                    finalizes royalty event
GET  /v1/me/discover-weekly
GET  /v1/search?q=...
POST /v1/playlists                   { name, tracks[] }
GET  /v1/podcasts/{id}/episodes
```

## Data Model
- `users(user_id, country, plan, language, created_at)`
- `tracks(track_id, title, artist_ids[], album_id, duration_ms, isrc, popularity)`
- `albums(album_id, title, artist_ids[], release_date)`
- `playlists(playlist_id, owner_id, name, track_ids[], collaborative)`
- `plays(user_id, track_id, ts, context, ms_played, completed)` (Kafka -> data lake)
- `audio_files(track_id, bitrate, codec, storage_url, drm)`
- `recommendations(user_id, type, items[], generated_at)`

## High-Level Architecture
- Mobile/desktop/web clients -> edge LB -> API gateway.
- Catalog service (Cassandra) for track/album/artist metadata.
- Streaming service: returns short-lived signed CDN URLs.
- CDN: Fastly + multi-CDN strategy; audio segments served as small HTTP objects.
- Recommendations: offline pipeline on GCP/Hadoop produces playlists like Discover Weekly weekly.
- Search: Elasticsearch with custom ranking for tracks/artists/podcasts.
- Social service: follow graph, activity feed.
- Royalty service: deduped per-user-per-track play events go into a data lake; ETL produces label payouts.
- Storage: Cassandra (metadata, playlists), PostgreSQL (subscriptions), GCS/S3 (audio masters), BigQuery (analytics), Redis (sessions, hot tracks).
- Backend services written in Java/Scala (historically), Python for ML.

## Detailed Components

### Audio Delivery
Tracks are pre-encoded at multiple bitrates (24, 96, 160, 320 kbps Ogg Vorbis on desktop; AAC on Apple platforms) and broken into chunks of a few seconds. The streaming service issues short-lived signed URLs scoped to the user/session; the client fetches chunks from the closest CDN PoP. A small prefetch (a few seconds ahead) and an even smaller pre-seek buffer make track-to-track transitions feel instant.

### Recommendation Engine (Discover Weekly)
A combination of collaborative filtering (matrix factorization on listening history), NLP on track metadata and external text, and raw audio analysis (CNNs over spectrograms) generates candidate tracks. A ranker then selects 30 tracks weekly, balancing user taste, novelty, and exploration. Pipelines run on Spark/BigQuery; outputs land in Cassandra for per-user lookup. Algorithmic playlists like Daily Mix and Release Radar use similar two-stage architectures with different freshness windows.

### Social Features
A follow graph keyed on user_id. Activity feed is fan-out-on-read for most users; expensive users may be fan-out-on-write. "Friend Activity" sidebar pulls recent plays from followees via a feed service backed by Kafka topics keyed on producer_id.

### Podcast Support
Podcasts share the streaming and metadata stack but have separate ingest (RSS feed polling for third-party shows; direct ingest for Spotify originals) and a different recommendation pipeline weighted toward show subscription and episode-level skip behavior. Exclusive Spotify-only shows use DRM.

### Royalty Tracking
Every play of >= 30s emits a royalty event with track_id, user_id, country, plan, ts, and context. Events flow through Kafka into a data lake. A daily pipeline deduplicates (a single play counts once), maps tracks to rights-holders via ISRC, applies per-country license rates, and produces payout reports. Disputes are reconcilable because raw events are retained.

### Offline Downloads
Premium users download tracks encrypted on the device with a key obtained from a license server. Downloads expire periodically (forcing re-licensing if subscription lapses). Downloads are scheduled over Wi-Fi by default to conserve cellular data.

## Trade-offs
- Cassandra (AP, fast writes) for catalog vs SQL: catalog is denormalized for read speed.
- Algorithmic playlists generated offline (cheap, can be heavy ML) vs on-demand (fresh but expensive): Spotify chose weekly batch for Discover Weekly.
- DRM on every track vs only exclusives: most music has no DRM (just signed URLs); only exclusives use DRM.
- Multi-CDN vs single: multi reduces cost via competition and improves availability.
- Loud-norm normalization vs raw audio: loudness normalization is on by default for consistent listening experience.

## Failure Modes & Mitigations
- CDN region outage: client transparently fails over to peer CDN; the manifest contains multiple candidate hosts.
- License server down: clients use a grace window (existing license valid for hours).
- Search index lag: searches return slightly stale results - acceptable.
- Recommendation pipeline failure: previous week's Discover Weekly remains until refreshed; product gracefully says "your playlist refreshes Monday."
- Hot track (new release) overload: pre-warm CDN before release; rate-limit metadata fetches; serve audio from cache.
- Royalty pipeline lag: payouts are monthly, pipeline can tolerate days of delay.

## Key Insights
- Two-stage recommendation (candidate gen + ranking) is canonical; Spotify pioneered it for music.
- Pre-encoding multiple bitrates + small chunks + signed URLs gives instant playback without DRM overhead.
- Royalty correctness is an engineering requirement, not a finance afterthought - dedupe and ISRC mapping must be right.
- Mixing collaborative filtering with audio CNN features lets Spotify recommend new tracks with no listen history.
- Multi-CDN is the standard answer for global audio/video; single-CDN is a SPOF.
