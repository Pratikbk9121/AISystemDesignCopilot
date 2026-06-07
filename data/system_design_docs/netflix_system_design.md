# Netflix System Design

## Overview
Netflix is a global on-demand video streaming service that ingests source video, transcodes it into a ladder of bitrates and codecs, distributes it via a custom CDN (Open Connect) embedded in ISPs, and personalizes discovery for hundreds of millions of subscribers with strict streaming SLAs.

## Functional Requirements
- Browse, search, and play video on demand on TVs, mobile, and web.
- Personalized homepage rows and recommendations per profile.
- Adaptive video playback that adjusts to network and device capabilities.
- Multiple profiles per account with separate viewing history.
- Downloads for offline viewing.
- Live events (sports, comedy specials) in addition to VOD.
- Subscription billing, free trials, household sharing controls.

## Non-Functional Requirements
- Scalability: ~250M paid subscribers, ~1B+ hours of streaming per week.
- Availability: 99.99% for playback start; degraded modes (lower bitrate, smaller catalog) preferred over outage.
- Latency: time-to-first-frame (TTFF) < 2s; playback rebuffer ratio < 0.5%.
- Durability: master video assets and viewing history stored durably across regions.
- Multi-region active-active across AWS regions (us-east-1, us-west-2, eu-west-1).

## Capacity Estimation
- Peak concurrent streams: ~100M.
- Per-stream egress at 5 Mbps avg -> ~500 Tbps aggregate, mostly served by Open Connect.
- VOD library: ~17K titles, ~10s of PB after transcoding ladders.
- Viewing events: ~10B/day -> ~100K events/sec average.
- Storage: viewing history ~1KB/event in Cassandra, several PB compressed.

## API Design
```
GET  /v1/home?profile_id=...        -> personalized rows
GET  /v1/title/{id}                 -> metadata, ratings, trailer
POST /v1/playback/start             -> { manifest_url, session_token, drm_license_url }
POST /v1/playback/heartbeat         -> { position, bitrate, dropped_frames }
POST /v1/playback/stop              -> finalize viewing event
GET  /v1/search?q=...
POST /v1/account/profile
```
Manifests are DASH/HLS with per-segment URLs pointing at Open Connect Appliances (OCAs).

## Data Model
- `accounts(account_id, plan, billing_status, country, created_at)`
- `profiles(profile_id, account_id, name, maturity_rating, language)`
- `titles(title_id, type, metadata, available_regions, release_date)`
- `viewing_history(profile_id, title_id, ts, position_sec, device)` (Cassandra)
- `assets(asset_id, title_id, codec, bitrate, resolution, drm_keys, storage_url)`
- `recommendations(profile_id, row_id, title_ids[], score, generated_at)`

## High-Level Architecture
- Client SDKs (TV, mobile, web) talk to AWS-hosted control plane and pull video from Open Connect.
- Edge tier: API gateway (Zuul), authentication, request routing.
- Microservices on AWS (EC2/EKS) - thousands of services, mostly JVM (Java/Kotlin), some Node.
- Data: Cassandra (viewing history, user data), EVCache (Memcached fork) for hot data, MySQL (billing), S3 (master videos, transcoded ladder), Elasticsearch (search).
- Content pipeline: ingest -> validation -> chunked transcoding -> packaging -> DRM -> Open Connect distribution.
- Recommendation/ML: offline batch on Spark, online serving via Polynote/feature store.
- A/B testing platform (ABLaze) gates every UI and algorithm change.

## Detailed Components

### Open Connect (CDN)
Netflix runs its own CDN by deploying purpose-built appliances (OCAs) inside ISP networks and IXPs. Each OCA is a high-density storage server pre-loaded nightly with the most-watched titles for that region. When a client requests a manifest, Netflix's steering service picks the closest OCA with the asset and adequate capacity. ~95% of bytes are served from OCAs; only metadata and personalization traffic hit AWS. Cold titles fall back to fill-tier OCAs in IXPs, then to S3.

### Video Encoding Pipeline
Master mezzanine files (ProRes/IMF) land in S3. The pipeline splits each title into chunks of a few seconds, transcodes each chunk in parallel across thousands of EC2 spot instances, and produces a per-title bitrate ladder (e.g., 235 kbps to 16 Mbps) across codecs (H.264, HEVC, AV1, VP9) and resolutions. Per-shot optimization picks the lowest bitrate that meets a quality target (VMAF) for each scene, saving bandwidth on simple scenes.

### Adaptive Bitrate Streaming
Clients fetch a DASH/HLS manifest listing all rungs. The player's ABR algorithm monitors buffer level, throughput, and dropped frames and switches rungs between segments. Netflix's algorithm balances quality (VMAF) against rebuffer risk and uses content-aware encoding so the same VMAF score corresponds to different bitrates per title.

### Recommendation Engine
Multiple models feed multiple rows on the homepage: collaborative filtering for "Because you watched", contextual bandits for top-of-page ranking, deep nets for personalized artwork. Features include viewing history, time of day, device, locale. Offline training on Spark; online ranking via low-latency model servers. Ranking is re-personalized per profile, not per account.

### A/B Testing Infrastructure
Every meaningful change (algorithm, UI, encoding ladder) ships behind an experiment. The allocation service assigns profiles to cells deterministically. Metrics pipeline computes streaming-quality-of-experience (rebuffers, TTFF, bitrate) and engagement (hours watched, retention) and flags wins. Rollout follows ramp -> hold -> ship.

### Chaos Engineering
The Simian Army (Chaos Monkey kills instances, Chaos Kong evacuates regions, Latency Monkey injects delays) ensures every service tolerates failure. Hystrix-style circuit breakers and bulkheads isolate failures so a recommendation outage degrades to a generic homepage rather than blocking playback.

## Trade-offs
- Custom CDN (Open Connect) vs commercial CDNs: massive capex but lower marginal cost and tighter ISP relationships.
- Cassandra (AP) for viewing history vs strongly consistent stores: occasional stale reads acceptable, write availability sacred.
- Microservices everywhere vs monolith: organizational velocity wins, at the cost of complex tracing and dependency graphs.
- Pre-positioned content vs on-demand fetch: pre-positioning wastes some disk but eliminates origin spikes.
- Heavy A/B testing vs faster shipping: experimentation is slower but prevents regressions in QoE.

## Failure Modes & Mitigations
- OCA disk or rack failure: steering service routes to next-closest OCA; clients seamlessly switch.
- Region evacuation: traffic shifts to peer regions; capacity is pre-provisioned to absorb a full region.
- Transcode pipeline backlog: spot fleet auto-scales; priority queue ensures new releases finish first.
- Recommendation service down: fall back to editorially curated rows or popularity-based ranking.
- DRM license server overload: licenses cached on client for repeat plays; queue with backpressure.
- Login spike at launch event: pre-warmed capacity, rate-limit non-essential endpoints.

## Key Insights
- ~95% of streaming bytes never touch AWS; Open Connect is the leverage.
- Per-shot encoding cuts bandwidth without lowering perceived quality.
- A/B testing is the product-development substrate, not a side activity.
- Eventual consistency is fine for viewing history; users never notice ms-stale resume points.
- Chaos engineering is the only way to validate that "everything's redundant" is actually true.
