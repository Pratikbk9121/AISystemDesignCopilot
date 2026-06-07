# URL Shortener System Design (like bit.ly, TinyURL)

## Overview
A URL shortener converts long URLs into short, memorable links and redirects users to the original URL. Used for tracking, analytics, and social media sharing.

## Core Components

### 1. **API Gateway**
- RESTful API for URL creation and redirection
- Rate limiting (prevent abuse)
- Authentication (optional for custom URLs)

### 2. **URL Shortening Service**
- Generate unique short codes (6-8 characters)
- Validate and sanitize input URLs
- Store mapping: short_code → original_url
- Handle collisions (extremely rare with good algorithm)

### 3. **Redirect Service**
- Look up short code in database/cache
- HTTP 301 (permanent) or 302 (temporary) redirect
- Track click analytics
- Handle expired or deleted links (404 response)

### 4. **Analytics Service**
- Click tracking (timestamp, IP, user agent, referrer)
- Geographic location (IP geolocation)
- Aggregated metrics (clicks per day, top referrers)
- Real-time dashboards

### 5. **Custom URL Service (Optional)**
- Allow users to choose custom short codes (e.g., bit.ly/mybrand)
- Check availability and reserve
- Premium feature for businesses

## Database Architecture

### URL Mappings
- **Primary Database** (PostgreSQL/MySQL):
  - `id` (auto-increment)
  - `short_code` (unique, indexed)
  - `original_url` (text, max 2048 chars)
  - `user_id` (optional, for user-created links)
  - `created_at` (timestamp)
  - `expires_at` (optional, for temporary links)
  - `is_active` (boolean)

### Caching Layer
- **Redis**:
  - Cache hot URLs (Pareto principle: 20% URLs = 80% traffic)
  - Key: short_code, Value: original_url
  - TTL: 1-24 hours
  - Cache-aside pattern (read-through)
  - Eviction: LRU (Least Recently Used)

### Analytics Data
- **Time-Series Database** (InfluxDB, Cassandra, ClickHouse):
  - `short_code`
  - `timestamp`
  - `ip_address`
  - `country_code`
  - `referrer`
  - `user_agent`
  - `device_type` (mobile, desktop, tablet)

### NoSQL Option
- **MongoDB/DynamoDB**:
  - Good for horizontal scaling
  - Schema flexibility for analytics
  - TTL indexes for auto-expiry

## Short Code Generation Algorithms

### Approach 1: Base62 Encoding (Recommended)
- Convert auto-increment ID to Base62 (0-9, a-z, A-Z)
- 6 characters = 62^6 = 56 billion combinations
- Example: ID 125,000 → Base62: "W7e"
- Pros: No collisions, predictable, fast
- Cons: Sequential (slightly predictable)

### Approach 2: MD5/SHA Hash + Truncate
- Hash the original URL (MD5/SHA256)
- Take first 6-8 characters
- Check for collision, retry with salt if needed
- Pros: Distributed generation
- Cons: Collision possible (rare), need collision handling

### Approach 3: Random String + Collision Check
- Generate random 6-char string from charset
- Check database for uniqueness
- Retry if collision
- Pros: Truly random
- Cons: Database lookup per generation (slower)

### Approach 4: Counter-Based with Zookeeper
- Distributed counter service (Zookeeper)
- Each server gets range (e.g., 1-1000, 1001-2000)
- Convert to Base62
- Pros: Guaranteed unique, fast
- Cons: Added complexity (Zookeeper)

## Scaling Strategy

### Read-Heavy Optimization
- **Caching**: Redis cluster for hot URLs
- **CDN**: Cache 301 redirects at edge (CloudFlare, Akamai)
- **Read Replicas**: Multiple MySQL read replicas
- **Database Indexing**: Index on short_code (primary lookup)

### Write Optimization
- **Batch Analytics**: Buffer click events, batch insert to analytics DB
- **Async Processing**: Use message queue (Kafka) for analytics
- **Database Sharding**: Partition by short_code first character (a-z, 0-9)

### High Availability
- Multi-region deployment
- Database replication (master-slave)
- Health checks and auto-failover
- Circuit breakers for external dependencies

## API Design

### Create Short URL
```
POST /api/v1/shorten
Body: { 
  "url": "https://example.com/very/long/url",
  "custom_code": "optional-custom",
  "expires_at": "2024-12-31"
}
Response: {
  "short_url": "https://short.ly/a1B2c3",
  "short_code": "a1B2c3",
  "original_url": "https://example.com/very/long/url",
  "created_at": "2024-01-01T10:00:00Z"
}
```

### Redirect
```
GET /{short_code}
Response: HTTP 301 Redirect to original_url
```

### Get Analytics
```
GET /api/v1/analytics/{short_code}
Response: {
  "total_clicks": 1250,
  "clicks_by_country": {...},
  "clicks_by_date": {...}
}
```

## Trade-offs

### HTTP 301 vs 302
- **301 (Permanent)**: Browsers cache, faster subsequent loads, but analytics lost
- **302 (Temporary)**: Always hits server, accurate analytics, slightly slower
- **Recommendation**: 302 for analytics-focused services

### SQL vs NoSQL
- **SQL**: ACID compliance, complex queries, analytics
- **NoSQL**: Horizontal scaling, high write throughput
- **Hybrid**: SQL for mappings, NoSQL for analytics

### Short Code Length
- 6 chars = 56B combinations (sufficient for most cases)
- 7 chars = 3.5T combinations (enterprise scale)
- 8 chars = 218T combinations (overkill for most)

## Security Considerations

1. **Rate Limiting**: Prevent spam and abuse (e.g., 100 URLs/hour per IP)
2. **URL Validation**: Check for malicious URLs, phishing sites
3. **Blacklist**: Block known spam domains
4. **CAPTCHA**: For anonymous URL creation
5. **DDoS Protection**: Cloudflare/WAF
6. **Link Expiration**: Auto-delete old/unused links (TTL)

## Performance Optimizations

1. **Pre-generate Short Codes**: Background job to create pool of unused codes
2. **Connection Pooling**: Reuse database connections
3. **Async Analytics**: Don't block redirect on analytics writes
4. **Bloom Filter**: Quick check if short code exists before DB lookup
5. **Geographic Routing**: Route users to nearest data center

## Capacity Estimates

- **Write**: 1,000 new URLs/second (86M per day)
- **Read**: 10,000 redirects/second (864M per day)
- **Read:Write Ratio**: 10:1 (read-heavy)
- **Storage**: 100 bytes per URL × 1B URLs = 100 GB (compact)
- **Cache Size**: 20% of URLs × 100 bytes = 20 GB (easily fits in Redis)

## Key Insights

- Extremely read-heavy (10:1 or higher ratio)
- Caching is critical (Redis + CDN)
- Base62 encoding of auto-increment ID is simplest and most reliable
- Analytics can be decoupled (message queue for async processing)
- Security and abuse prevention are essential
- Most URLs follow Pareto principle (80/20 rule for cache efficiency)
