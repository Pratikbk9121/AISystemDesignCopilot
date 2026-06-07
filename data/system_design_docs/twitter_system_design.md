# Twitter System Design

## Overview
Twitter is a social media platform for sharing short messages (tweets), following users, and real-time content distribution to millions of concurrent users.

## Core Components

### 1. **API Gateway & Load Balancer**
- Entry point for all client requests (web, mobile, third-party)
- Rate limiting per user/API key
- SSL termination and request routing
- Nginx or AWS ALB for load distribution

### 2. **Tweet Service**
- **Post Tweet**: Write tweets to database with user ID, timestamp, content
- **Timeline Generation**: Fan-out on write for followers
- **Media Upload**: Handle images/videos via separate media service
- Rate limiting: 2,400 tweets/day per user

### 3. **Timeline Service**
- **Home Timeline**: Aggregated feed from followed users
- **User Timeline**: Individual user's tweets
- **Fan-out Strategy**: 
  - Fan-out on write for most users (pre-compute timelines)
  - Fan-out on read for celebrities (too many followers)
  - Hybrid approach for optimal performance

### 4. **Social Graph Service**
- Manages follow/unfollow relationships
- Bi-directional graph: followers and following
- Optimized for fast lookups (who follows whom)
- Graph database or adjacency lists in cache

### 5. **Search Service**
- Elasticsearch or Solr for full-text search
- Real-time indexing of tweets
- Search by keywords, hashtags, users, date ranges
- Inverted index for fast lookups

### 6. **Notification Service**
- Push notifications for mentions, likes, retweets, follows
- WebSocket connections for real-time updates
- Message queue (Kafka) for async notification delivery

### 7. **Trending Topics Service**
- Real-time aggregation of popular hashtags
- Stream processing (Apache Kafka + Flink/Storm)
- Time-windowed counts (last 1 hour, 24 hours)
- Geographic trending (country/region specific)

## Database Architecture

### Primary Datastore
- **MySQL/PostgreSQL** (sharded by user ID):
  - User profiles (username, bio, location)
  - Tweets metadata (tweet_id, user_id, timestamp, text)
  - Social graph relationships

### Caching Layer
- **Redis/Memcached**:
  - Home timelines (hot data, recent 800 tweets)
  - User profiles (frequently accessed)
  - Tweet counts (likes, retweets)
  - Session data
  - TTL: 15-30 minutes for timelines

### Time-Series Data
- **Cassandra** or **HBase**:
  - Tweet archive (historical tweets)
  - Analytics data (impressions, engagement metrics)
  - High write throughput for real-time tweets

### Media Storage
- **S3/CDN**:
  - Images, videos, GIFs
  - Distributed via CloudFront/Akamai for low latency

### Search Index
- **Elasticsearch**:
  - Real-time tweet indexing
  - Sharded by date for efficient queries

## Scaling Strategy

### Horizontal Scaling
- **Stateless Services**: All application servers are stateless, enabling easy scaling
- **Database Sharding**: Partition by user_id (consistent hashing)
- **Read Replicas**: Multiple read replicas for MySQL to handle read-heavy load
- **CDN**: Serve static assets and media from edge locations

### Caching Strategy
- **L1 Cache**: In-memory cache on application servers
- **L2 Cache**: Distributed Redis cluster
- **Cache Invalidation**: Write-through for posts, lazy loading for timelines

### Message Queue
- **Apache Kafka**:
  - Decouple tweet ingestion from timeline fan-out
  - Buffer for spiky write traffic (breaking news, viral tweets)
  - Enables async processing (search indexing, analytics, notifications)

### Geographically Distributed
- Multiple data centers across continents
- Geo-routing based on user location
- Cross-region replication for disaster recovery

## API Design

### Post Tweet
```
POST /api/v1/tweets
Body: { "text": "Hello Twitter!", "media_ids": [...] }
Response: { "tweet_id": "12345", "created_at": "2024-01-01T10:00:00Z" }
```

### Get Timeline
```
GET /api/v1/timelines/home?count=20&max_id=999
Response: { "tweets": [...], "next_cursor": "888" }
```

### Follow User
```
POST /api/v1/friendships/create
Body: { "user_id": "67890" }
Response: { "relationship": "following" }
```

## Trade-offs

### Fan-out on Write vs Fan-out on Read
- **Fan-out on Write**: Pre-compute timelines, fast reads, high write amplification for celebrities
- **Fan-out on Read**: Compute timelines on-demand, slower reads, lower storage
- **Twitter's Approach**: Hybrid - write for regular users, read for celebrities (>1M followers)

### Consistency vs Availability
- **Tweets**: Eventual consistency acceptable (not critical if delayed by 1-2 seconds)
- **Follower Counts**: Eventually consistent
- **Authentication**: Strong consistency required

### SQL vs NoSQL
- **SQL**: User profiles, relationships (ACID compliance, complex queries)
- **NoSQL**: Tweet storage, analytics (horizontal scalability, high write throughput)

## Performance Optimizations

1. **Timeline Materialization**: Pre-compute top 800 tweets per user in Redis
2. **Lazy Loading**: Load older tweets on-demand from database
3. **Pagination**: Cursor-based pagination for infinite scroll
4. **Rate Limiting**: Prevent spam and abuse (API limits, posting limits)
5. **Content Delivery**: CDN for media, edge caching for hot content

## Key Insights

- Handle 500M tweets/day, 6,000 tweets/second average, 12,000 peak
- 350M active users, 1.5B timeline requests/day
- Fan-out optimization crucial for scalability
- Real-time processing with Kafka/Storm for trends and search
- Geographic distribution for global low-latency access
