# Tinder System Design

## Overview
Tinder is a location-based dating app that surfaces nearby candidates one at a time, supports swipe-based interest signaling, creates matches on mutual interest, and provides chat between matched users. The system must serve geographically relevant candidates with low latency, ML-rank the queue, prevent spam/fraud, and enforce strong privacy controls.

## Functional Requirements
- Profile creation with photos, bio, age, gender, preferences.
- Discover nearby candidates filtered by distance, age, gender.
- Swipe right (like), left (pass), or super-like.
- Match creation on mutual right-swipe.
- 1:1 chat with matched users.
- Photo upload with moderation.
- Premium tiers (rewind, boost, passport for location override).
- Block/report; spam and fraud detection.

## Non-Functional Requirements
- Scalability: ~75M MAU, billions of swipes/day.
- Availability: 99.9% for discovery; chat may degrade independently.
- Latency: discovery queue load < 300ms; swipe registered in < 100ms.
- Privacy: precise location never exposed; only fuzzy distance shown.
- Eventual consistency on match creation acceptable - both users will see it quickly.

## Capacity Estimation
- 75M MAU, ~20M DAU, ~50 swipes/user/day -> 1B swipes/day, ~12K/sec average, 50K/sec peak.
- Match rate ~1% -> 10M matches/day.
- Photos: avg 6 per user, 5MB each -> 100s of TB total.
- Geo updates: clients refresh location every few minutes when active.

## API Design
```
GET  /v1/discovery?lat=...&lng=...   -> [profile_cards]
POST /v1/swipes                      { target_user_id, direction }
                                     -> { match: bool, match_id? }
POST /v1/matches/{id}/messages       { text }
GET  /v1/matches/{id}/messages
POST /v1/profile/photos              presigned-URL upload
POST /v1/profile/preferences         { age_range, max_distance, gender }
POST /v1/block                       { target_user_id, reason? }
```

## Data Model
- `users(user_id, name, dob, gender, bio, photos[], location_cell, last_active)`
- `preferences(user_id, age_min, age_max, distance_km, interested_in)`
- `swipes(user_id, target_id, direction, ts)` (Cassandra)
- `matches(match_id, user_a, user_b, created_at, last_message_ts)`
- `messages(match_id, ts, sender_id, text, read_at)`
- `blocks(user_id, blocked_id, ts)`

## High-Level Architecture
- Mobile clients -> edge LB -> API gateway.
- Discovery service: builds and ranks the candidate queue per user.
- Geo service: maintains user-to-cell mapping in Redis/in-memory geo index (S2/Geohash).
- Swipe service: writes swipe events, checks for reciprocal swipe to create a match.
- Match service: durable match records, notifies both users.
- Chat service: messaging stack analogous to WhatsApp/Slack but simpler.
- Photo service: presigned upload, moderation (NSFW detection, face validation).
- Recommendation/Ranking ML: scores candidates by predicted right-swipe rate from both sides.
- Storage: PostgreSQL (users, matches), Cassandra (swipes, messages), Redis (queues, presence), S3 (photos), Elasticsearch (admin search), Kafka (event backbone).

## Detailed Components

### Geolocation-Based Discovery
Each user's location is hashed into an S2 cell or geohash. The geo service maintains a per-cell list of recently active user_ids. To build user A's discovery queue, the service queries cells within A's max-distance radius, filters by preferences and mutual gender preference, removes already-swiped and blocked users, and returns top-K candidates. Exact lat/lng never leaves the geo service; only fuzzy distance is exposed.

### Swipe & Match Engine
A swipe is a (user, target, direction) tuple. On a right-swipe, the swipe service does an atomic check-and-set in a Redis hash to see if `target` previously right-swiped `user`. If yes, a match is created in PostgreSQL and a `match.created` event is published, triggering push notifications to both users. Swipes are also durably persisted to Cassandra for ML and exclusion lists. The Redis check is the hot path; Cassandra is the source of truth.

### Recommendation ML
A two-stage funnel: (1) candidate generation picks geo-relevant, preference-compatible users; (2) a ranker scores each candidate by predicted probability of mutual right-swipe (i.e., a match). Features include profile embeddings (vision model over photos + NLP over bio), historical swipe behavior, activity recency, and ELO-style desirability scores. Ranker is retrained daily on swipe + match outcomes; online inference uses a feature store.

### Chat
Once matched, a conversation is created. Chat is a thin messaging stack: WebSocket gateways for real-time delivery, Cassandra for message persistence, push notifications for offline. Message size and rate limits are tighter than Slack (no files in many tiers, length caps). Read receipts are optional.

### Photo Upload & Moderation
Photos are uploaded to S3 via presigned URLs. An async pipeline runs:
- NSFW classifier (block or shadow-flag).
- Face detection + count (no faces, multiple faces, or non-human flagged for review).
- Hash-based duplicate detection (catches stolen-photo accounts).
- Optional liveness/selfie verification for blue-check.

### Fraud & Spam Detection
Signals: rapid-fire right-swipes (bot behavior), reused photos across accounts, messaging URLs to off-platform sites, payment chargebacks, IP/device-id reuse, mass reports. A real-time scoring service flags accounts; high-risk accounts are shadowbanned (their swipes don't reach others) before hard ban to avoid tipping off operators.

## Trade-offs
- Push notifications on match vs in-app only: pushes drive engagement but risk notification fatigue - throttle.
- Strong consistency on match creation vs eventual: must avoid duplicate matches; Redis atomic check + idempotent DB insert handles both.
- Per-cell candidate lists in Redis (fast, ephemeral) vs database queries (slow, durable): Redis fronts geo lookups; DB is source of truth.
- Showing exact distance vs fuzzy: fuzzy (e.g., "5 km") protects against trilateration attacks.
- Aggressive shadowbanning vs explicit bans: shadowbanning makes abuse harder to evolve around.

## Failure Modes & Mitigations
- Redis geo cache loss: rebuild from last-known locations in DB; discovery degrades to slower DB queries.
- Match-creation race (both users swipe right within ms): atomic Redis SETNX prevents duplicate match rows.
- Photo moderation backlog: new photos default to "limited reach" until cleared.
- Push notification provider down: in-app notification still works; mark for re-send.
- Hot geographic region (concert, conference): per-cell rate limits; auto-spread to neighbors.
- Bot attack: account-creation rate limits per IP/device; CAPTCHA on suspicious flow; ML risk scoring at swipe time.

## Key Insights
- Geospatial sharding (S2/Geohash) is the discovery primitive; exact coordinates never leave the geo service.
- Atomic Redis check on right-swipe is the elegant solution to match-creation races.
- Two-stage ranking (candidate gen + mutual-swipe predictor) outperforms simple recency or distance ordering.
- Shadowbanning is more effective than outright bans for sophisticated abusers.
- Photo moderation must be async + multi-signal; relying on user reports alone is too slow.
