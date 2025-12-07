-- TikTokSales Supabase Schema (Clean)
-- Run this SQL in the Supabase SQL Editor to create all required tables
-- Delete existing tables first if needed, then run this script

-- ============================================
-- DROP EXISTING TABLES (uncomment to reset)
-- ============================================
-- DROP TABLE IF EXISTS chat_messages CASCADE;
-- DROP TABLE IF EXISTS orders CASCADE;
-- DROP TABLE IF EXISTS products CASCADE;
-- DROP TABLE IF EXISTS clients CASCADE;
-- DROP TABLE IF EXISTS streamers CASCADE;

-- ============================================
-- STREAMERS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS streamers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    platform TEXT DEFAULT 'tiktok',
    follower_count INTEGER DEFAULT 0,
    is_live BOOLEAN DEFAULT FALSE,
    live_started_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CLIENTS TABLE (buyers/users)
-- ============================================
CREATE TABLE IF NOT EXISTS clients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- PRODUCTS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    streamer TEXT,
    streamer_id UUID REFERENCES streamers(id) ON DELETE CASCADE,
    sku TEXT,
    name TEXT NOT NULL,
    user_description TEXT,
    description TEXT,
    tag TEXT,
    model_description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    image_url TEXT,
    image_urls TEXT,
    minio_bucket TEXT,
    stock INTEGER DEFAULT 0,
    category TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- ORDERS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
    streamer_id UUID REFERENCES streamers(id) ON DELETE SET NULL,
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    total_price DECIMAL(10, 2) NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CHAT MESSAGES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    streamer TEXT,
    client TEXT,
    message TEXT NOT NULL,
    intent TEXT,  -- "yes" or "no" (buying intent from webhook)
    cantidad INTEGER DEFAULT 0,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INDEXES FOR PERFORMANCE
-- ============================================
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_timestamp ON chat_messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_chat_messages_intent ON chat_messages(intent);
CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_id);
CREATE INDEX IF NOT EXISTS idx_orders_streamer_id ON orders(streamer_id);
CREATE INDEX IF NOT EXISTS idx_products_streamer_id ON products(streamer_id);
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_streamers_username ON streamers(username);
CREATE INDEX IF NOT EXISTS idx_clients_email ON clients(email);

-- ============================================
-- PRODUCT MATCHES TABLE (Vision Service)
-- ============================================
CREATE TABLE IF NOT EXISTS product_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    streamer TEXT NOT NULL,
    stream_timestamp TIMESTAMPTZ NOT NULL,
    product_id UUID REFERENCES products(id) ON DELETE CASCADE,
    vision_score FLOAT,
    frame_urls TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_matches_streamer ON product_matches(streamer);
CREATE INDEX IF NOT EXISTS idx_product_matches_product_id ON product_matches(product_id);

-- ============================================
-- STREAMER FRAMES TABLE (Video Captures)
-- ============================================
CREATE TABLE IF NOT EXISTS streamer_frames (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    streamer TEXT NOT NULL,
    frame_timestamp TIMESTAMPTZ NOT NULL,
    minio_url TEXT NOT NULL,
    minio_object TEXT NOT NULL,
    content_type TEXT,
    width INTEGER,
    height INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_streamer_frames_streamer ON streamer_frames(streamer);
CREATE INDEX IF NOT EXISTS idx_streamer_frames_timestamp ON streamer_frames(frame_timestamp);

-- ============================================
-- CHAT MESSAGE ORDER MAPPING TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS chat_message_order_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE,
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_order_mapping_chat ON chat_message_order_mapping(chat_message_id);
CREATE INDEX IF NOT EXISTS idx_chat_order_mapping_order ON chat_message_order_mapping(order_id);

-- ============================================
-- PAYMENT NOTIFICATIONS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS payment_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    notification_type TEXT,  -- 'whatsapp', 'sms', 'email'
    recipient_number TEXT,
    message_sid TEXT,
    status TEXT DEFAULT 'pending',  -- 'sent', 'failed', 'delivered'
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_notifications_order ON payment_notifications(order_id);
CREATE INDEX IF NOT EXISTS idx_payment_notifications_status ON payment_notifications(status);

-- ============================================
-- NLP INTENTS TABLE (Reference Data)
-- ============================================
CREATE TABLE IF NOT EXISTS nlp_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO nlp_intents (intent_name, description) VALUES
('yes', 'User expresses intent to purchase the product'),
('no', 'No buying intent detected'),
('question', 'User asks about product features, price, shipping, etc'),
('feedback', 'User provides positive or negative feedback'),
('complaint', 'User complains about product or service')
ON CONFLICT (intent_name) DO NOTHING;


