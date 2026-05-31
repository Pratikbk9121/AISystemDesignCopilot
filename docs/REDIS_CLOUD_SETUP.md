# Redis Cloud Free Tier Setup Guide

Complete guide to setting up Redis Cloud for AI System Design Copilot.

---

## 🎯 Quick Overview

**What you get for FREE:**
- ✅ 30 MB storage (enough for 500-1000 sessions)
- ✅ 30 concurrent connections
- ✅ 100 ops/sec throughput
- ✅ Hosted on AWS/GCP/Azure
- ✅ No credit card required

---

## 📝 Step-by-Step Setup

### Step 1: Create Redis Cloud Account

1. **Go to:** https://redis.io/try-free

2. **Sign up** using one of these options:
   - Email + Password
   - Google Account
   - GitHub Account

3. **Verify your email** (if using email signup)

---

### Step 2: Create Free Database

1. After login, click **"Create database"** or **"New database"**

2. **Select plan:**
   - Type: **Free**
   - Memory: **30 MB**

3. **Choose location:**
   - Cloud vendor: **AWS** / **Google Cloud** / **Azure**
   - Region: Pick closest to you (e.g., `us-east-1`)

4. **Database settings:**
   - Name: `system-design-copilot` (or any name you prefer)
   - Redis version: **Latest** (7.x or 8.x)
   - Leave other settings as default

5. **Click "Create database"**

⏱️ Wait 1-2 minutes for provisioning...

---

### Step 3: Get Connection Details

After database is created:

1. **Click on your database** in the dashboard

2. **Find these values:**
   ```
   Public endpoint: redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com:12345
   Default user password: Abc123XyzSecurePassword!
   ```

3. **Note down:**
   - **Host:** `redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com`
   - **Port:** `12345` (will be different for you)
   - **Password:** `Abc123XyzSecurePassword!` (will be different for you)

---

### Step 4: Configure Your Application

1. **Copy the example environment file:**
   ```bash
   cp .env.redis-cloud.example .env
   ```

2. **Edit `.env` file** with your Redis Cloud credentials:
   ```env
   # Enable Redis
   REDIS_ENABLED=true
   
   # Your Redis Cloud credentials (replace with actual values)
   REDIS_HOST=redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com
   REDIS_PORT=12345
   REDIS_PASSWORD=Abc123XyzSecurePassword!
   REDIS_DB=0
   REDIS_TTL=3600
   ```

3. **Save the file**

---

### Step 5: Test Connection

Run the test script to verify everything works:

```bash
python scripts/test_redis_connection.py
```

**Expected output:**
```
============================================================
Testing Redis Connection
============================================================

📋 Configuration:
   Host: redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com
   Port: 12345
   Password: ***
   Database: 0
   TTL: 3600 seconds

1️⃣  Testing basic connection...
   ✅ PING successful: True

2️⃣  Testing SET and GET...
   ✅ SET/GET successful: Hello Redis!

3️⃣  Testing TTL (expiration)...
   ✅ TTL set successfully: 60 seconds remaining

4️⃣  Testing RedisConversationStateManager...
   ✅ Connected to Redis at redis-12345...
   ✅ Saved conversation with 2 messages
   ✅ Retrieved conversation with 2 messages
   ✅ Conversation TTL: 3600 seconds
   ✅ Active sessions: ['test-session-123']

5️⃣  Cleaning up test data...
   ✅ Cleanup complete

============================================================
✅ All Redis tests passed!
============================================================
```

---

### Step 6: Start Your Application

```bash
# Start the FastAPI server
uvicorn app.main:app --reload
```

**Look for this log message:**
```
🔧 Using Redis-backed state manager
✅ Connected to Redis at redis-12345.c123.us-east-1-1.ec2.cloud.redislabs.com:12345
```

---

## 🧪 Testing the Integration

### Test 1: Create a conversation

```bash
curl -X POST "http://localhost:8000/api/v1/system-design/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Design a URL shortener",
    "session_id": "test-123"
  }'
```

### Test 2: Verify data in Redis Cloud

1. Go to Redis Cloud dashboard
2. Click on your database
3. Click **"Browser"** tab
4. You should see keys like: `conversation:test-123`

### Test 3: Retrieve conversation

```bash
curl "http://localhost:8000/api/v1/system-design/conversation/test-123"
```

---

## 🔧 Troubleshooting

### Error: "Connection refused"

**Check:**
- Is `REDIS_ENABLED=true` in your `.env`?
- Are host/port/password correct?
- Is your Redis Cloud database running?

### Error: "Authentication failed"

**Fix:**
- Double-check `REDIS_PASSWORD` in `.env`
- Copy password exactly from Redis Cloud dashboard
- Remove any trailing spaces

### Error: "Timeout"

**Fix:**
- Check your internet connection
- Redis Cloud may have IP restrictions (check Security settings)
- Try increasing timeout in `app/core/state_manager.py`

---

## 💡 Tips & Best Practices

1. **Session TTL:** Default is 1 hour (3600 seconds)
   - Adjust `REDIS_TTL` in `.env` if needed
   - Inactive sessions auto-expire to save space

2. **Monitor Usage:**
   - Check Redis Cloud dashboard for memory usage
   - 30 MB = ~500-1000 active sessions
   - Old sessions auto-delete after TTL

3. **Security:**
   - Never commit `.env` file to Git
   - Keep `REDIS_PASSWORD` secret
   - Use `.gitignore` to exclude `.env`

---

## 📊 What Gets Stored in Redis?

**Key format:** `conversation:{session_id}`

**Value (JSON):**
```json
{
  "session_id": "abc-123",
  "messages": [
    {
      "role": "user",
      "content": "Design a URL shortener",
      "timestamp": "2026-04-28T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Here's a design...",
      "timestamp": "2026-04-28T10:30:15Z"
    }
  ],
  "metadata": {
    "last_architecture": {...}
  },
  "created_at": "2026-04-28T10:30:00Z",
  "updated_at": "2026-04-28T10:30:15Z"
}
```

**TTL:** Auto-expires after `REDIS_TTL` seconds of inactivity

---

## ✅ Success Checklist

- [ ] Created Redis Cloud account
- [ ] Created free database (30 MB)
- [ ] Got connection credentials (host, port, password)
- [ ] Updated `.env` file with credentials
- [ ] Ran test script successfully
- [ ] Started app and saw Redis connection message
- [ ] Tested creating and retrieving conversations

---

## 🚀 Next Steps

Once Redis is working:

1. **Scale up:** Upgrade to paid tier if you need more than 30 MB
2. **Monitor:** Check Redis Cloud dashboard regularly
3. **Optimize:** Adjust TTL based on usage patterns
4. **Production:** Consider Redis Cloud Pro for 99.99% uptime

---

**Need help?** Check the Redis Cloud docs: https://redis.io/docs/latest/operate/rc/
