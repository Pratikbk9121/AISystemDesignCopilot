# Rate Limiter System Design

## Overview
A rate limiter restricts how many requests a client may make in a time window. It protects backends from overload, enforces fair use across tenants, mitigates abuse and DoS, and is deployed at multiple tiers (edge CDN, API gateway, service-internal). Designs trade off accuracy, latency overhead, distributed-consistency cost, and behavior on failure (fail-open vs fail-closed).

## Functional Requirements
- Enforce request limits per key (user, IP, API key, route).
- Multiple limit tiers (e.g., 10 req/s, 100 req/min, 1000 req/hour).
- Returns 429 with `Retry-After` and standard headers when exceeded.
- Configurable per-route, per-tenant, per-plan.
- Support burst allowances (token bucket semantics).
- Whitelist/blacklist override.
- Hot-reload of limit configuration without restart.

## Non-Functional Requirements
- Latency overhead: < 1ms p99 added to request path.
- Throughput: 1M+ checks/sec per node.
- Availability: must not become a SPOF; fail-open by default for non-abuse traffic.
- Consistency: approximate counters acceptable; absolute precision is too expensive at scale.
- Distributed correctness: total req/sec for a key across N gateway pods must be enforced.

## Capacity Estimation
- API platform with 1B requests/day -> ~12K req/sec avg, 100K peak.
- Each request consults rate limiter -> ~100K limiter ops/sec.
- Key cardinality: 10M API keys + 1M IPs daily -> ~10M hot keys.
- Counter state: ~100 bytes/key x 10M = 1GB per shard.

## API Design
```
Allowed(key, scope) -> { allowed: bool, remaining: int, reset_at: ts, retry_after_ms?: int }

Response headers when enforced:
  X-RateLimit-Limit: 1000
  X-RateLimit-Remaining: 42
  X-RateLimit-Reset: 1717800000
  Retry-After: 13          (on 429)
```
Implemented either as a sidecar/library inside the gateway or as a remote Redis-backed service.

## Data Model
- `limits(rule_id, scope, key_type, window, max_requests, burst)`
- `counters(key, window_start)` -> counter (in Redis or in-memory).
- `bucket_state(key)` -> { tokens, last_refill_ts } (for token bucket).
- `overrides(key, allow|deny, expires_at)`.

## High-Level Architecture
- At edge: CDN-tier limits per IP (Cloudflare-style).
- At API gateway: per-API-key and per-route limits using Redis-backed counters.
- Inside services: per-tenant concurrency caps, often via local semaphores.
- Configuration plane: hot-reload from a config service (etcd, Consul, file watcher).
- Storage: Redis cluster for distributed counters; local in-memory L1 cache to absorb most checks.

## Detailed Components

### Token Bucket
A bucket holds N tokens; tokens refill at rate R per second up to capacity C. Each request consumes 1 token; if none, deny. Burst-friendly: a client can spend C tokens at once after a quiet period. State: `{tokens, last_refill_ts}`. On each request, compute `tokens = min(C, tokens + (now - last_refill_ts) * R)` then decrement. Used by AWS, Stripe, many gateways.

### Leaky Bucket
A FIFO queue of capacity C drained at constant rate R. Excess requests overflow and are rejected. Smooths out bursts to a constant rate - good when downstream wants smoothness rather than averages. Less burst-friendly than token bucket; in practice often equivalent and people use the terms loosely.

### Fixed Window Counter
Increment a counter keyed by `(api_key, floor(now/window))`. Cheap (single INCR). Problem: bursts at the window boundary can deliver 2x the limit (last second of window N + first second of window N+1).

### Sliding Window Log
Store a sorted-set of request timestamps; on each request, drop entries older than the window, count remaining. Most accurate but memory-heavy (stores every request) and slow at high QPS.

### Sliding Window Counter (Hybrid)
Maintain two fixed-window counters (current + previous). Weight the previous window by the fraction of overlap with the current sliding window. Accurate enough for most uses and cheap. Industry favorite.

### Distributed Rate Limiting with Redis
Each gateway pod must enforce a global limit. Implementations:
- **Centralized counter in Redis**: every check is a Redis INCR with EXPIRE. Adds ~1ms RTT. Hot keys can hammer a single Redis shard - mitigate with key splitting or replicas.
- **Lua script in Redis**: atomically refill + decrement token bucket in a single RTT.
- **Cell-based estimation**: each gateway pod tracks local count, syncs to Redis periodically. Lower latency, may briefly over-deliver near the limit.
- **Token bucket replicated via gossip**: each pod owns a share of tokens; redistribute idle tokens. Used by Envoy's global limiting in some setups.

### Key Selection
Common scopes: per-API-key (paid customers), per-user-id (logged-in), per-IP (anonymous, with /24 grouping to defeat trivial IP rotation), per-route (different limits per endpoint), per-tenant (org-level total). Often layered: a request must pass IP-limit AND user-limit AND route-limit.

### Edge vs Origin Rate Limiting
- **Edge** (CDN/WAF): drops abusive traffic before it reaches origin; protects bandwidth. Best for IP-based and broad DoS.
- **Origin/gateway**: knows the API key and tenant; enforces business limits.
- **Service-internal**: per-tenant concurrency caps, per-dependency circuit breakers.
A layered defense is standard.

### Fail-Open vs Fail-Closed
- **Fail-open**: if rate limiter is down, allow requests. Preferred for user-facing reads where availability beats abuse prevention.
- **Fail-closed**: deny requests. Preferred for sensitive endpoints (auth, payments) where abuse is worse than downtime.
Often configurable per route.

## Trade-offs
- Accuracy vs latency: sliding window log is exact but slow; fixed window is fast but lumpy.
- Centralized Redis (precise, +RTT) vs local-with-sync (fast, sloppy near limit): pick by SLA.
- Strict denial vs degrade (queue + slow): graceful degradation is friendlier but more complex.
- Token bucket (burst-friendly) vs leaky bucket (smoothing): pick based on downstream tolerance for bursts.
- Per-IP limits with NAT'd IPs hurt legitimate users; layered limits with API-key fallback fix it.

## Failure Modes & Mitigations
- Redis cluster outage: fail-open by default; alert + circuit-break to bypass.
- Hot key on a single Redis shard: shard counters by `(key, random_suffix)` and sum locally; or use replicas.
- Clock skew across pods: derive window from server-side time; use monotonic clocks for token refill.
- Configuration push error (bad config zeros all limits): require validation + canary deploy of configs.
- Bypass attempts (header spoofing, rotating IPs): combine IP/route/key signals; ML risk scoring for sophisticated abuse.
- Legitimate spike (launch event): pre-raise limits per tenant via admin override.

## Key Insights
- Token bucket is the default - burst-friendly, cheap, and easy to explain to API users.
- Sliding window counter is the right precision/perf trade-off for distributed limiters.
- Centralize counters in Redis only when accuracy near the limit matters; otherwise local-with-sync is faster.
- Layer limits: edge IP, gateway API-key, service tenant. No single layer can defend everything.
- Fail-open vs fail-closed is a per-route decision driven by what's worse: outage or abuse.
