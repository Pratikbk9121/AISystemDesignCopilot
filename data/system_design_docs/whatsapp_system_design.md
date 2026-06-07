# WhatsApp System Design

## Overview
WhatsApp is a real-time messaging platform supporting text, voice, video calls, and media sharing for billions of users with end-to-end encryption.

## Core Components

### 1. **API Gateway**
- Entry point for all client connections
- WebSocket management for persistent connections
- Protocol: Modified XMPP or custom binary protocol
- Load balancing across message servers

### 2. **Message Service**
- Real-time message delivery
- Message persistence and offline storage
- Read receipts and delivery confirmations
- Temporary storage before delivery (max 30 days)

### 3. **User Service**
- User authentication (phone number based)
- Profile management (name, status, profile picture)
- Contact discovery via phone numbers
- Privacy settings (last seen, profile photo visibility)

### 4. **Media Service**
- Image/Video compression and storage
- Thumbnail generation
- S3/Blob storage for media files
- CDN for media delivery
- Media encryption at rest

### 5. **Group Service**
- Group creation and management
- Member addition/removal
- Group metadata (name, icon, description)
- Admin permissions
- Max 256 members per group

### 6. **Call Service (Voice/Video)**
- WebRTC for peer-to-peer calls
- STUN/TURN servers for NAT traversal
- Signaling server for call setup
- Media relay servers for poor network conditions
- End-to-end encryption for calls

### 7. **Status/Stories Service**
- Ephemeral content (24-hour expiry)
- Media upload and distribution
- View tracking
- Auto-deletion after 24 hours

### 8. **Encryption Service**
- End-to-end encryption (Signal Protocol)
- Key exchange and management
- Device-specific encryption keys
- Forward secrecy (ephemeral keys)

## Database Architecture

### User Data
- **PostgreSQL/MySQL** (sharded by user ID):
  - User profiles (phone, name, status)
  - Device information (last seen, push tokens)
  - Contact lists
  - Privacy settings

### Message Storage
- **Cassandra/ScyllaDB**:
  - Temporary message storage (until delivered)
  - Messages deleted after delivery confirmation
  - Offline messages (max 30 days)
  - Sharded by user_id or conversation_id

### Media Storage
- **S3/Cloud Storage**:
  - Images, videos, audio, documents
  - Encrypted at rest
  - TTL-based cleanup for old media
  - CDN integration (CloudFront/Akamai)

### Caching Layer
- **Redis**:
  - Online/offline user status
  - Active WebSocket connections
  - Message queue for pending deliveries
  - Session data (authentication tokens)
  - Recent conversations

### Group Metadata
- **MongoDB/DynamoDB**:
  - Group information (members, admins, settings)
  - Group message history (limited retention)
  - Participant lists

## Scaling Strategy

### WebSocket Connection Management
- Long-lived persistent connections (WebSocket)
- Connection pooling across multiple servers
- Sticky sessions for connection affinity
- Heartbeat mechanism to detect disconnections
- Auto-reconnection with exponential backoff

### Horizontal Scaling
- Stateless message servers (easy to scale)
- Database sharding by user_id
- Microservices architecture (message, media, call services)
- Geographic distribution across regions

### Message Delivery Optimization
- **Online Users**: Direct push via WebSocket
- **Offline Users**: Store in queue, deliver on reconnection
- **Push Notifications**: APNs (iOS) / FCM (Android) for offline alerts
- **Acknowledgments**: Three-tier (sent, delivered, read)

### Load Balancing
- Geographic routing (closest data center)
- Health checks and failover
- Consistent hashing for user-to-server mapping

## End-to-End Encryption (Signal Protocol)

### Key Components
1. **Identity Keys**: Long-term per-device keypairs
2. **Signed Pre-Keys**: Medium-term signed keypairs
3. **One-Time Pre-Keys**: Ephemeral keys for forward secrecy
4. **Session Keys**: Derived from key exchange

### Message Flow
1. Sender encrypts message with recipient's public key
2. Server relays encrypted message (cannot decrypt)
3. Recipient decrypts with private key
4. Keys rotated frequently (forward secrecy)

## API Design

### Send Message
```
POST /api/v1/messages
Headers: { Authorization: "Bearer <token>" }
Body: { 
  "recipient_id": "1234567890",
  "encrypted_content": "<encrypted_data>",
  "type": "text|image|video"
}
Response: { "message_id": "msg_12345", "status": "sent" }
```

### Fetch Messages (Offline)
```
GET /api/v1/messages/pending
Response: { "messages": [...], "count": 10 }
```

### Update Status
```
POST /api/v1/messages/{message_id}/status
Body: { "status": "delivered|read" }
```

## Trade-offs

### Centralized vs Decentralized
- **WhatsApp Choice**: Centralized servers for reliability and ease of use
- **Trade-off**: Single point of control, but better performance and UX

### Message Storage
- **Temporary Storage**: Messages deleted after delivery (privacy first)
- **Trade-off**: No cloud backup, but enhanced security
- **Backup**: Optional encrypted local backups to iCloud/Google Drive

### Group Size Limit (256 members)
- **Reason**: Reduces fan-out overhead and ensures performance
- **Alternative**: Channels/Broadcasts for one-to-many communication

### End-to-End Encryption
- **Benefit**: Ultimate privacy (server cannot read messages)
- **Trade-off**: No server-side search, message recovery, or spam filtering

## Performance Optimizations

1. **Protocol Compression**: Custom binary protocol (smaller than JSON)
2. **Image Compression**: Aggressive compression before sending
3. **Message Batching**: Group multiple messages in single request
4. **Adaptive Quality**: Video call quality adjusts to network conditions
5. **Lazy Loading**: Load older messages on-demand

## Capacity Estimates

- 2 billion active users globally
- 100 billion messages per day
- 50 billion media files shared daily
- Peak: 1 million messages/second
- Average message size: 1 KB (text), 200 KB (image), 2 MB (video)

## Key Insights

- End-to-end encryption is non-negotiable (privacy first)
- WebSocket for persistent connections critical for real-time delivery
- Temporary message storage reduces infrastructure costs
- Simple UX (phone number only, no usernames/passwords)
- Erlang-based messaging infrastructure (originally)
- Acquired by Facebook (Meta) in 2014 for $19B
