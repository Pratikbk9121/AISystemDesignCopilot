# Uber System Design

## Overview
Uber is a real-time ride-hailing platform that matches riders with nearby drivers, computes routes and ETAs, prices trips dynamically with surge, processes payments, and operates across hundreds of cities with strict latency requirements on location updates and matching.

## Functional Requirements
- Riders can request a ride from origin to destination and see live driver location.
- Drivers can go online/offline and stream GPS coordinates continuously.
- The system matches a rider with the best nearby driver within seconds.
- Compute ETA, fare estimate, and route using map and traffic data.
- Apply surge pricing in high-demand regions.
- Process payments (card, wallet, cash) and issue receipts.
- Trip lifecycle: requested -> accepted -> arrived -> in_progress -> completed -> rated.
- Support ride history, ratings, and driver/rider profiles.

## Non-Functional Requirements
- Scalability: 100M+ MAU, ~25M trips/day, location updates from millions of drivers concurrently.
- Availability: 99.99% for matching and trip endpoints; degrade gracefully (disable surge) before going down.
- Latency: location update ingestion p99 < 200ms; match decision < 2s.
- Durability: trip and payment records must survive AZ failure; eventual consistency acceptable for analytics.
- Multi-region active-active for failover; per-city sharding for matching state.

## Capacity Estimation
- 5M concurrent online drivers globally at peak.
- Each driver emits GPS every 4s -> ~1.25M location writes/sec peak.
- 25M trips/day -> ~300 trip starts/sec average, ~5K/sec peak.
- Storage: raw location pings ~50 bytes each, ~5TB/day raw (kept hot for 7d, cold for 90d).
- Trip records: ~2KB each, ~50GB/day.
- Bandwidth: location stream ~600Mbps ingress; map tile + ETA egress dominates.

## API Design
```
POST /v1/rides/request
  { rider_id, pickup: {lat,lng}, dropoff: {lat,lng}, product: "uberx" }
  -> { ride_id, eta_sec, fare_estimate, surge_multiplier }

POST /v1/drivers/location
  { driver_id, lat, lng, heading, speed, ts }
  -> 204

POST /v1/rides/{id}/accept   (driver)
POST /v1/rides/{id}/arrive
POST /v1/rides/{id}/start
POST /v1/rides/{id}/complete  -> triggers payment + receipt

GET  /v1/rides/{id}            -> trip state + driver location
```
Internal services prefer gRPC for low-latency RPC between matching, pricing, and dispatch.

## Data Model
- `users(user_id, type, name, phone, rating, payment_token, created_at)`
- `drivers(driver_id, vehicle_id, status, current_cell_id, last_ping_ts)`
- `trips(trip_id, rider_id, driver_id, origin, destination, state, fare, surge, started_at, ended_at)`
- `locations(driver_id, ts, lat, lng, h3_cell)` (time-series, Cassandra)
- `payments(payment_id, trip_id, amount, currency, status, processor_ref)`
- `surge_state(cell_id, multiplier, updated_at)` (Redis)

## High-Level Architecture
- Mobile clients (rider + driver apps) over HTTPS/WebSocket.
- Edge: API gateway + WebSocket gateway, TLS termination, auth.
- Location ingestion service -> Kafka (`driver-locations` topic, partitioned by city).
- Geospatial index service (in-memory, H3/S2/Quadtree per city).
- Matching/dispatch service (per-city sharded).
- Pricing/surge service.
- Trip service (state machine).
- ETA service backed by routing engine + traffic data.
- Payments service integrating Stripe/Braintree/Adyen.
- Fraud/risk service.
- Notification service (push, SMS).
- Storage: PostgreSQL (transactional), Cassandra (location time-series), Redis (hot state), S3 (receipts, ML features), Snowflake/Hive (analytics).

## Detailed Components

### Geospatial Indexing
The world is divided into hierarchical cells. Uber popularized H3 (hexagonal grid); alternatives are Google S2 (spherical quadrilaterals) and Quadtrees. Hexagons have uniform neighbor distance, which is useful for matching radius and supply/demand heatmaps. Each online driver is keyed by its current H3 cell. Lookups become "give me drivers in cell X and its k-ring neighbors."

### Driver Location Streaming
Driver app emits a position every 4s. The location service writes to Kafka partitioned by `city_id` so consumers preserve per-city ordering. A consumer updates an in-memory geo-index (per-region service) and persists pings to Cassandra (partition key `driver_id`, clustering by `ts`). Old pings TTL out after 7 days.

### Matching / Dispatch
On ride request, dispatch queries the geo-index for candidate drivers in the pickup cell + neighbors, filters by product type and status, scores by ETA, driver acceptance rate, and detour cost, then offers the ride to the top driver. If declined within a few seconds, it cascades to the next candidate. Dispatch is single-master per city to avoid double-offers; replicated via Raft for failover.

### Surge Pricing
A streaming job (Flink/Kafka Streams) aggregates open requests and available supply per H3 cell on a rolling window. When demand/supply ratio exceeds a threshold, the cell's multiplier increases. Multipliers are written to Redis and consulted by pricing on every fare estimate. Smoothing prevents oscillation.

### ETA Prediction
A routing engine (contraction-hierarchies graph over OSM/HERE map data) computes shortest paths. A separate ML model corrects raw routing ETA using historical travel times per road segment per hour-of-week and live traffic from driver pings.

### Payments
On trip completion, the trip service emits a `trip.completed` event. The payments service authorizes the rider's saved payment method via the processor, captures on settlement, and writes an idempotent payment record. Outbox pattern ensures the trip DB and payment intent stay consistent.

### Fraud Detection
Signals: GPS spoofing (impossible velocity), incentive farming (driver-rider collusion via repeat pairs), stolen card patterns. A feature store feeds an online model that scores rides before payment capture.

## Trade-offs
- SQL (trips, users) for ACID + reporting vs Cassandra for location time-series with massive write throughput.
- Strong consistency for trip state machine (one driver assigned) vs eventual consistency for location index.
- Per-city sharding simplifies matching but cross-city rides (airports) need careful boundary handling.
- H3 vs S2: H3 has uniform neighbors; S2 integrates better with some Google stacks.
- Push (WebSocket) for live driver location vs pull (poll) - push wins for UX, costs more sockets.

## Failure Modes & Mitigations
- Geo-index node loss: matching falls back to a replica; pings replayed from Kafka.
- Kafka partition lag: dispatch reads best-effort stale positions and marks ETA confidence lower.
- Payment processor outage: queue capture; allow rider to leave (charge later); show banner.
- Surge runaway: hard cap multiplier per city; circuit-break if pricing service unhealthy and default to 1.0x.
- Region failure: DNS + global load balancer move traffic to peer region; per-city state replicated async.
- Mobile network loss: client retries with exponential backoff; idempotency keys on ride-request.

## Key Insights
- Geospatial indexing (H3) is the heart of dispatch and surge.
- Kafka decouples high-volume location ingest from matching, enabling replay and multiple consumers.
- City-level sharding keeps the matching problem small and parallel.
- Surge must be smooth, capped, and explainable to avoid rider trust damage.
- Multi-region active-active matters: a ride request cannot wait for cross-Atlantic failover.
