# Distributed Cache System Design

## Overview
A distributed cache (Redis/Memcached-style) is an in-memory key-value store sharded across many nodes, offering sub-millisecond reads to back hot data paths for web services. It must scale horizontally, handle node failures, balance load with consistent hashing, support eviction under memory pressure, and avoid pathological behaviors like hot keys and cache stampedes.

## Functional Requirements
- GET, SET, DEL, EXPIRE on keys.
- TTLs and explicit eviction.
- Atomic operations (INCR, CAS, hash/list/set ops).
- Pub/sub for change notification.
- Cluster mode: shard keys across nodes; auto-rebalance on membership change.
- Replication for HA (primary -> replicas).
- Persistence (optional snapshot/AOF) for warm restart.

## Non-Functional Requirements
- Latency: p99 < 1ms for in-DC GET; p99 < 5ms cross-AZ.
- Throughput: 100K+ ops/sec per node, 10M+ aggregate per cluster.
- Availability: 99.99% via replication and automated failover.
- Scale: scale horizontally to 100s of nodes, TB+ of memory.
- Consistency: tunable - usually eventually consistent between primary and replicas.

## Capacity Estimation
- Typical web service: ~10:1 read:write to backing DB, cache absorbs 95%+ of reads.
- Object size: typical 100B-10KB, hot keys may be MB.
- A 128GB-per-node cluster of 50 nodes -> ~6TB usable; with replication factor 2, ~3TB unique.
- Throughput: 100K ops/sec/node x 50 nodes = 5M ops/sec.

## API Design
```
GET key
SET key value [EX seconds] [NX|XX]
DEL key
INCR key
EXPIRE key seconds
MGET key1 key2 ...
HSET hash field value
SUBSCRIBE channel
```
Client libraries hash keys to nodes and pool persistent TCP connections.

## Data Model
- In-memory hash map per node, sharded by key.
- Per-key metadata: value, expiry, last-access, refcount.
- Optional secondary structures: lists, hashes, sorted sets, hyperloglog.
- Eviction tracker: LRU/LFU bookkeeping.

## High-Level Architecture
- Cache nodes hold key->value in memory.
- A cluster topology (gossiped via Redis Cluster bus, or coordinated via ZooKeeper/etcd).
- Clients use a smart library: hash the key, route to the owning node, follow MOVED/ASK redirects.
- Replication: each shard has a primary and N replicas; replicas catch up asynchronously.
- Failover controller (Sentinel/cluster manager) detects primary failure and promotes a replica.
- Optional persistence: RDB snapshots + AOF (append-only file).

## Detailed Components

### Consistent Hashing
Naive `key % N` reshuffles almost all keys when a node is added/removed. Consistent hashing places nodes and keys on a hash ring; each key is owned by the next node clockwise. Adding/removing a node only moves keys between adjacent positions. To balance load, each physical node owns multiple virtual nodes (tokens) on the ring. Redis Cluster uses a fixed 16384-slot scheme, which is conceptually similar - slots are reassigned during rebalancing.

### Eviction Policies
When memory hits the limit, the cache evicts:
- **LRU (Least Recently Used)**: evicts oldest-accessed. Approximated by sampling rather than tracking exact recency (cheaper).
- **LFU (Least Frequently Used)**: evicts least-accessed by frequency, with decay. Better for skewed access patterns.
- **TTL-based**: evicts items closest to expiry.
- **Random**: evicts random keys; surprisingly OK as a fallback.
- **No-eviction**: returns OOM errors; appropriate when cache is also source-of-truth-ish.

### Replication & Failover
Each shard has a primary that accepts writes and N async replicas. Replicas tail a replication log. On primary failure, a controller selects the most up-to-date replica and promotes it; clients are notified via the topology gossip. Async replication means a few writes may be lost on failover - tolerable for cache; not for a database.

### Cache-Aside vs Write-Through vs Write-Back
- **Cache-aside (lazy)**: app reads cache; on miss, reads DB and populates cache. Simple, default choice. Stale data possible until TTL or invalidate.
- **Write-through**: app writes both cache and DB synchronously. Stronger consistency, slower writes.
- **Write-back**: app writes cache only; cache flushes to DB asynchronously. Fast writes but data loss on cache crash.
- **Read-through**: cache itself loads from DB on miss. Encapsulates loader but tightly couples cache to data source.

### Hot Key Mitigation
A single key with massive QPS (e.g., a viral post) can saturate a single node. Mitigations:
- **Client-side micro-caching**: short-TTL local cache absorbs duplicate requests.
- **Replica reads**: spread reads across replicas of the hot shard.
- **Key splitting**: shard a logical key into K physical keys (key:0..K-1), client picks random suffix on read. Costs an extra write fan-out.
- **Tiered cache**: an in-process cache layer in front of the distributed cache.

### Cache Stampede / Thundering Herd
When a hot key expires, thousands of clients miss simultaneously and hammer the DB. Mitigations:
- **Request coalescing (single-flight)**: app code holds an in-process lock per key; only one fetcher hits the DB; others wait.
- **Probabilistic early expiration**: clients refresh proactively before TTL expires.
- **Stale-while-revalidate**: serve stale value while a background fetch refreshes; clients never see a miss.
- **Distributed mutex** (Redis SETNX with TTL) ensures only one app instance refreshes globally.

## Trade-offs
- Strong consistency vs availability: async replication trades freshness on failover for availability and write speed.
- LRU vs LFU: LFU wins on skewed long-tail; LRU is simpler and good enough for most workloads.
- Write-through (consistent, slow) vs cache-aside (fast, may serve stale): cache-aside is the pragmatic default.
- Persistence (RDB/AOF) vs pure memory: persistence enables warm restart but adds I/O cost; cache should not be the system of record.
- Single big cluster vs many small caches: small caches per service reduce blast radius; big cluster simplifies ops.

## Failure Modes & Mitigations
- Node crash: replica promoted; some recent writes may be lost - acceptable for cache, app rebuilds on next miss.
- Network partition: minority side stops serving writes (CP-leaning configs) or splits brain - operationally critical to detect.
- Memory exhaustion: eviction kicks in; if eviction can't keep up, requests fail or get OOM.
- Hot key DoS: detect via per-key QPS metrics; auto-split or shed.
- Cache poisoning: write-through with bad data poisons cache; mitigated by versioned keys + invalidation on schema change.
- Stampede on cold start: prewarm critical keys after deployment; use stale-while-revalidate.

## Key Insights
- Consistent hashing (or fixed slot maps) is the canonical sharding scheme - never use naive modulo.
- Cache-aside is the default pattern; reach for write-through only when consistency demands it.
- Stampede prevention (single-flight, jittered TTLs, stale-while-revalidate) is more important than people expect.
- Hot keys are inevitable; design for them with key splitting, replicas, or tiered caches.
- The cache is not a database. Treat any persistence/replication as best-effort; the source of truth lives elsewhere.
