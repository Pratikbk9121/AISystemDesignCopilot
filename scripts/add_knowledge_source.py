"""
Helper script to easily add new system design knowledge to the RAG pipeline
"""
import sys
from pathlib import Path
from typing import Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# Sample knowledge sources you can add
KNOWLEDGE_TEMPLATES: Dict[str, str] = {
    "whatsapp": """
# WhatsApp System Design

## Overview
WhatsApp handles 100B+ messages per day with 2B+ active users.

## Core Components
1. **Chat Service**: Real-time message delivery
2. **Media Service**: Images, videos, voice messages
3. **Group Service**: Group chats (up to 256 members)
4. **Presence Service**: Online/offline status, last seen
5. **Notification Service**: Push notifications

## Technical Stack
- **Erlang**: Chat server (handles millions of connections)
- **FreeBSD**: Operating system for servers
- **XMPP**: Modified protocol for messaging
- **MySQL**: User data, message metadata
- **Cassandra**: Message history storage

## Key Features
- **End-to-end encryption**: All messages encrypted
- **Message Queue**: Offline message delivery
- **Connection pooling**: Minimize TCP connections
- **Sharding**: By phone number hash

## Scaling Strategy
- Erlang's lightweight processes (millions per server)
- Horizontal scaling of chat servers
- Geographic distribution for low latency
- Minimal metadata storage (no message content on servers after delivery)

## Trade-offs
**Centralized vs Decentralized**:
- WhatsApp: Centralized for simplicity and reliability
- Trade-off: Single point of control vs easier operations

**Storage Duration**:
- Messages deleted after delivery (privacy-first)
- Trade-off: Privacy vs message history/search
""",
    
    "airbnb": """
# Airbnb System Design

## Overview
Airbnb marketplace with 7M+ listings and 150M+ users globally.

## Core Services
1. **Search Service**: Find listings by location, dates, price
2. **Booking Service**: Handle reservations and payments
3. **Pricing Service**: Dynamic pricing recommendations
4. **Review Service**: Host and guest reviews
5. **Recommendation Service**: ML-based personalized suggestions

## Database Architecture
- **MySQL**: Transactional data (bookings, users, payments)
- **ElasticSearch**: Search and filtering
- **Redis**: Cache for search results, session data
- **S3**: Photo storage for listings

## Search Architecture
- **Geospatial indexing**: Find nearby listings
- **Availability checking**: Real-time calendar sync
- **Price filtering**: Range queries
- **Ranking algorithm**: ML-based relevance scoring

## Payment Flow
1. Guest reserves → Funds held in escrow
2. Host has 24h to accept
3. After check-in → Funds released to host
4. Refund policies enforced automatically

## Scaling Challenges
- Peak traffic during holidays (10x normal)
- Geographic distribution (different regulations)
- Multi-currency support
- Fraud detection at scale

## Key Insights
- **Search is critical**: 90% of bookings start with search
- **Trust & Safety**: Reviews, verification, insurance
- **Dynamic pricing**: ML models predict optimal prices
- **Mobile-first**: 60%+ bookings on mobile
""",
    
    "youtube": """
# YouTube System Design

## Overview
YouTube handles 1B+ hours of video watched daily, 500+ hours uploaded every minute.

## Core Components
1. **Upload Service**: Video ingestion and processing
2. **Transcoding Service**: Convert to multiple formats/qualities
3. **CDN**: Global content delivery network
4. **Recommendation Engine**: ML-based video suggestions
5. **Comment Service**: User interactions

## Video Processing Pipeline
1. **Upload**: Chunked upload for large files
2. **Transcode**: 
   - Multiple resolutions (144p → 8K)
   - Multiple codecs (H.264, VP9, AV1)
   - Adaptive bitrate streaming
3. **Store**: 
   - Original in Colossus (Google's distributed FS)
   - Transcoded versions in CDN
4. **Serve**: Edge servers near users

## Database Architecture
- **Bigtable**: Video metadata, comments, likes
- **Spanner**: User data, subscriptions (global consistency)
- **Vitess (MySQL)**: Channel data, playlists

## CDN Strategy
- **Google Global Cache**: Deployed in ISPs worldwide
- **Predictive prefetching**: Cache popular videos
- **Smart routing**: Route to nearest server
- **Traffic shaping**: Manage bandwidth costs

## Recommendation System
- **Watch history**: User behavior tracking
- **Collaborative filtering**: Users with similar tastes
- **Content-based**: Video metadata, thumbnails
- **Engagement signals**: Click-through rate, watch time

## Scaling Insights
- **80/20 rule**: 20% of videos get 80% of views
- **Cold start problem**: New videos need initial boost
- **Live streaming**: Different architecture (lower latency)
- **Copyright detection**: Content ID system scans uploads

## Key Trade-offs
**Quality vs Bandwidth**:
- Adaptive streaming adjusts quality based on connection
- Cost: More transcoding and storage

**Recommendation vs Diversity**:
- Personalization increases engagement
- Risk: Filter bubbles, lack of content diversity
"""
}


def add_knowledge_source(name: str, create_sample_data: bool = False):
    """
    Add a new knowledge source to the vector database
    
    Args:
        name: Name of the knowledge source (e.g., 'whatsapp', 'airbnb')
        create_sample_data: If True, creates sample template data
    """
    data_dir = Path("./data/system_design_docs")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    if create_sample_data and name in KNOWLEDGE_TEMPLATES:
        file_path = data_dir / f"{name}_design.md"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(KNOWLEDGE_TEMPLATES[name])
        
        print(f"✅ Created: {file_path}")
        print(f"📄 Size: {len(KNOWLEDGE_TEMPLATES[name])} characters")
        return file_path
    else:
        print(f"❌ No template found for '{name}'")
        print(f"\nAvailable templates: {', '.join(KNOWLEDGE_TEMPLATES.keys())}")
        return None


def main():
    """
    Main function to add knowledge sources
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Add system design knowledge to RAG pipeline"
    )
    parser.add_argument(
        "--add",
        type=str,
        help=f"Add a knowledge source. Options: {', '.join(KNOWLEDGE_TEMPLATES.keys())}"
    )
    parser.add_argument(
        "--add-all",
        action="store_true",
        help="Add all available knowledge sources"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available knowledge sources"
    )
    
    args = parser.parse_args()
    
    if args.list:
        print("Available knowledge sources:")
        for name in KNOWLEDGE_TEMPLATES.keys():
            print(f"  - {name}")
        return
    
    if args.add_all:
        print("Adding all knowledge sources...")
        for name in KNOWLEDGE_TEMPLATES.keys():
            add_knowledge_source(name, create_sample_data=True)
        print("\n✅ All sources added!")
        print("\n🔄 Next step: Run initialize_vector_db.py to index the knowledge:")
        print("   python scripts/initialize_vector_db.py")
        return
    
    if args.add:
        add_knowledge_source(args.add, create_sample_data=True)
        print("\n🔄 Next step: Run initialize_vector_db.py to index the knowledge:")
        print("   python scripts/initialize_vector_db.py")
        return
    
    # Interactive mode
    print("🎯 Add System Design Knowledge to RAG Pipeline")
    print("=" * 60)
    print("\nAvailable templates:")
    for i, name in enumerate(KNOWLEDGE_TEMPLATES.keys(), 1):
        print(f"  {i}. {name.title()}")
    
    print(f"\n  {len(KNOWLEDGE_TEMPLATES) + 1}. All of the above")
    
    choice = input("\nSelect option (or 'q' to quit): ").strip()
    
    if choice.lower() == 'q':
        return
    
    try:
        choice_num = int(choice)
        if choice_num == len(KNOWLEDGE_TEMPLATES) + 1:
            for name in KNOWLEDGE_TEMPLATES.keys():
                add_knowledge_source(name, create_sample_data=True)
            print("\n✅ All sources added!")
        elif 1 <= choice_num <= len(KNOWLEDGE_TEMPLATES):
            name = list(KNOWLEDGE_TEMPLATES.keys())[choice_num - 1]
            add_knowledge_source(name, create_sample_data=True)
        else:
            print("Invalid choice")
            return
        
        print("\n🔄 Next step: Run initialize_vector_db.py to index the knowledge:")
        print("   python scripts/initialize_vector_db.py")
        
    except ValueError:
        print("Invalid input")


if __name__ == "__main__":
    main()
