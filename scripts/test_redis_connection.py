"""
Test Redis connection and basic operations
"""
import redis
from app.core.config import settings
from app.core.state_manager import RedisConversationStateManager
from app.models.schemas import ConversationHistory


def test_redis_connection():
    """Test basic Redis connection"""
    print("=" * 60)
    print("Testing Redis Connection")
    print("=" * 60)
    
    print(f"\n📋 Configuration:")
    print(f"   Host: {settings.redis_host}")
    print(f"   Port: {settings.redis_port}")
    print(f"   Password: {'***' if settings.redis_password else 'None'}")
    print(f"   Database: {settings.redis_db}")
    print(f"   TTL: {settings.redis_ttl} seconds")
    
    try:
        # Test 1: Basic connection
        print("\n1️⃣  Testing basic connection...")
        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            decode_responses=True,
            socket_connect_timeout=10,
        )
        
        response = client.ping()
        print(f"   ✅ PING successful: {response}")
        
        # Test 2: Set and Get
        print("\n2️⃣  Testing SET and GET...")
        client.set("test_key", "Hello Redis!")
        value = client.get("test_key")
        print(f"   ✅ SET/GET successful: {value}")
        
        # Test 3: TTL
        print("\n3️⃣  Testing TTL (expiration)...")
        client.setex("test_ttl", 60, "expires in 60 seconds")
        ttl = client.ttl("test_ttl")
        print(f"   ✅ TTL set successfully: {ttl} seconds remaining")
        
        # Test 4: State Manager
        print("\n4️⃣  Testing RedisConversationStateManager...")
        state_manager = RedisConversationStateManager(redis_client=client)
        
        # Create test conversation
        test_session_id = "test-session-123"
        conversation = state_manager.get_conversation(test_session_id)
        conversation.add_message("user", "Design a URL shortener")
        conversation.add_message("assistant", "Here's a design for a URL shortener...")
        
        # Save conversation
        state_manager.save_conversation(test_session_id, conversation)
        print(f"   ✅ Saved conversation with {len(conversation.messages)} messages")
        
        # Retrieve conversation
        retrieved = state_manager.get_conversation(test_session_id)
        print(f"   ✅ Retrieved conversation with {len(retrieved.messages)} messages")
        
        # Check TTL
        ttl = state_manager.get_ttl(test_session_id)
        print(f"   ✅ Conversation TTL: {ttl} seconds")
        
        # List sessions
        sessions = state_manager.list_sessions()
        print(f"   ✅ Active sessions: {sessions}")
        
        # Cleanup
        print("\n5️⃣  Cleaning up test data...")
        client.delete("test_key", "test_ttl")
        state_manager.delete_conversation(test_session_id)
        print(f"   ✅ Cleanup complete")
        
        print("\n" + "=" * 60)
        print("✅ All Redis tests passed!")
        print("=" * 60)
        print("\n💡 Your Redis Cloud connection is working perfectly!")
        print("   You can now enable Redis in your .env file:")
        print("   REDIS_ENABLED=true")
        
        return True
        
    except redis.ConnectionError as e:
        print(f"\n❌ Connection Error: {e}")
        print("\n💡 Troubleshooting:")
        print("   1. Check your Redis Cloud credentials in .env")
        print("   2. Verify host and port are correct")
        print("   3. Ensure password is set correctly")
        print("   4. Check if your IP is whitelisted in Redis Cloud")
        return False
        
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Make sure Redis is enabled in settings
    if not settings.redis_enabled:
        print("\n⚠️  Warning: REDIS_ENABLED is set to False in your configuration")
        print("   The script will still test the connection, but the app won't use Redis")
        print("   Set REDIS_ENABLED=true in your .env to enable Redis\n")
    
    success = test_redis_connection()
    exit(0 if success else 1)
