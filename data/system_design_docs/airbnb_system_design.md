# Airbnb System Design

## Overview
Airbnb is a global short-term-rental marketplace connecting hosts with guests. The system must support listing search with rich geospatial and filter queries, prevent double-bookings under concurrent demand, process payments in many currencies, handle host-guest messaging, and rank listings via ML.

## Functional Requirements
- Hosts create/edit listings with photos, pricing, availability calendars.
- Guests search by location, dates, guests, price, amenities, filters.
- Booking flow: instant book or request-to-book, with payment authorization.
- Calendar management to prevent double-booking.
- Messaging between guest and host pre-and-post booking.
- Reviews from both sides after stay.
- Multi-currency, multi-language, tax handling per jurisdiction.

## Non-Functional Requirements
- Scalability: ~150M users, ~7M listings, ~2M bookings/week peak.
- Availability: 99.99% for search; 99.999% on booking-confirm payment path.
- Latency: search p95 < 500ms; booking commit < 2s.
- Strong consistency for booking calendar (no double-bookings).
- Multi-region (US, EU, APAC) with data residency for EU users.

## Capacity Estimation
- 7M listings, with 365 days x 7M = ~2.5B availability cells.
- Search QPS: ~30K/sec peak.
- Booking writes: ~50/sec average, ~500/sec peak (holidays).
- Photos: avg 20 per listing, ~140M images, ~50TB.
- Messages: ~50M/day -> ~600/sec.

## API Design
```
GET  /v1/listings/search?bbox=...&checkin=...&checkout=...&guests=...&filters=...
GET  /v1/listings/{id}
GET  /v1/listings/{id}/calendar?start=...&end=...
POST /v1/bookings                 { listing_id, checkin, checkout, guests, payment_token }
                                  -> { booking_id, status, total }
POST /v1/bookings/{id}/cancel
POST /v1/listings/{id}/reviews
POST /v1/threads/{id}/messages
```

## Data Model
- `users(user_id, email, name, language, country, is_host, created_at)`
- `listings(listing_id, host_id, title, description, geo_point, geohash, amenities[], base_price, max_guests, status)`
- `availability(listing_id, date, is_blocked, price_override)`
- `bookings(booking_id, listing_id, guest_id, checkin, checkout, total, currency, state)`
- `payments(payment_id, booking_id, processor, status, captured_at)`
- `reviews(review_id, listing_id, booking_id, author_id, rating, text)`
- `threads(thread_id, listing_id, host_id, guest_id, created_at)`

## High-Level Architecture
- Web/mobile clients -> CDN + API gateway.
- Listing service: CRUD on listings, media management.
- Search service: Elasticsearch + custom geo index; ML re-ranker.
- Calendar/Availability service: per-listing date map with strong consistency.
- Booking service: orchestrates availability check, payment auth, booking insert.
- Pricing service: dynamic per-night pricing (host base + suggested adjustments).
- Payment service: integrates with Stripe/Adyen/Braintree; handles payouts to hosts.
- Messaging service: thread-based, similar to a simplified Slack.
- Reviews service.
- Search index pipeline: Kafka events from listing/availability changes trigger ES updates.
- Storage: MySQL (sharded by listing_id and user_id), Cassandra (messages, audit), Redis (hot listings cache, rate limits), S3 (photos), Elasticsearch (search), Kafka (events).

## Detailed Components

### Geospatial + Filtered Search
Search must combine bounding-box geo, date availability, price band, and amenity filters with relevance ranking. Implementation: Elasticsearch with `geo_bounding_box` and `geo_distance` queries, term filters on amenities, and a date-availability filter denormalized into the listing document (precomputed "available date set" for the next 12 months) or a join against the availability service. ML re-ranker scores top-N results by predicted booking probability (features: listing quality, host responsiveness, price relative to area, photos, reviews, user history).

### Booking Engine & Double-Booking Prevention
The critical invariant: for any listing and date, at most one confirmed booking exists. Implementation options:
1. **DB-level constraint**: a unique key on (listing_id, date) in the availability table, with the booking creating one row per night inside a transaction. Insert fails if any night is taken.
2. **Distributed lock** on `listing_id` (Redis/ZooKeeper) around the check-and-write.
3. **Optimistic concurrency**: read calendar version, write conditionally on same version.
Airbnb-style systems generally use option 1 (per-night unique constraint) with the booking transaction wrapping payment authorization and availability insert. If payment fails or times out, the transaction rolls back, freeing the dates.

### Calendar / Availability
The availability service stores a per-listing date map with status (available, blocked-by-host, booked, hold). Holds are temporary reservations during checkout (15-minute TTL) to prevent two guests from competing for the same dates while one is in checkout. iCal sync with external calendars (VRBO, host's personal calendar) prevents external double-bookings.

### Payments
On booking submit, the booking service creates a hold on the guest's card (auth, not capture). On host acceptance (or instant-book), the system captures. Payouts to hosts happen after check-in (or per local payout schedule) via the payments service, which manages multi-currency, FX, and tax withholding. Idempotency keys prevent duplicate charges on retry.

### Messaging
Thread per listing-guest-host triple. Pre-booking inquiries route to the host for response; the response-rate metric is a search ranking factor. Once booked, the thread persists with booking context.

### Reviews
Double-blind reviews: both parties submit independently; reviews are revealed only after both submit or after a deadline. This reduces retaliation bias.

## Trade-offs
- Elasticsearch denormalized listings (fast search) vs SQL joins (fresh): pipeline absorbs the freshness lag, search wins on latency.
- Strong consistency on bookings vs higher availability: bookings must be strongly consistent - use single-region writes per listing.
- Holds (15-min TTL) vs no holds: holds reduce conversion friction but block inventory briefly.
- Dynamic pricing suggestions (ML) vs fixed host pricing: suggestions only; host always overrides.
- Pre-capture vs auth+capture-later: auth-now-capture-later allows host to accept without immediate charge.

## Failure Modes & Mitigations
- Search index lag: results may briefly include just-booked-out listings; booking layer detects and shows alternatives.
- Payment processor outage: queue authorization with backpressure; tell user "we'll confirm in a few minutes."
- Calendar race condition: per-night unique constraint guarantees no double-booking even under concurrent writes.
- iCal sync delay with external calendars: hosts warned that external syncs are best-effort; manual override available.
- Region failover during booking: cross-region replication async, but booking writes pinned to listing's home region; failover loses < 1 minute of in-flight bookings (reconcilable from payment provider).
- Photo upload failure: client retry with exponential backoff; listings can publish without all photos.

## Key Insights
- The per-night unique constraint is the cleanest double-booking prevention; distributed locks are an inferior alternative.
- Denormalized availability into the search index trades freshness for query speed - worth it at this scale.
- Holds during checkout are essential to high-conversion booking UX in competitive date ranges.
- Double-blind reviews materially improve review honesty.
- Dynamic pricing must be advisory; hosts demand control over their listings.
