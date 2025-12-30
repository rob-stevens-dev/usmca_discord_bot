-- USMCA Bot Database Schema
-- PostgreSQL 16+

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- User profiles with behavior tracking
CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    username TEXT NOT NULL,
    discriminator TEXT,
    display_name TEXT,
    joined_at TIMESTAMPTZ NOT NULL,
    first_message_at TIMESTAMPTZ,
    total_messages INTEGER DEFAULT 0 CHECK (total_messages >= 0),
    toxicity_avg DOUBLE PRECISION DEFAULT 0.0 CHECK (toxicity_avg >= 0.0 AND toxicity_avg <= 1.0),
    warnings INTEGER DEFAULT 0 CHECK (warnings >= 0),
    timeouts INTEGER DEFAULT 0 CHECK (timeouts >= 0),
    kicks INTEGER DEFAULT 0 CHECK (kicks >= 0),
    bans INTEGER DEFAULT 0 CHECK (bans >= 0),
    last_action_at TIMESTAMPTZ,
    risk_level TEXT DEFAULT 'green' CHECK (risk_level IN ('green', 'yellow', 'orange', 'red')),
    is_whitelisted BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_risk_level ON users(risk_level) WHERE risk_level != 'green';
CREATE INDEX idx_users_joined_at ON users(joined_at DESC);
CREATE INDEX idx_users_updated_at ON users(updated_at DESC);

-- Message archive for pattern analysis
CREATE TABLE messages (
    message_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    channel_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    toxicity_score DOUBLE PRECISION CHECK (toxicity_score >= 0.0 AND toxicity_score <= 1.0),
    severe_toxicity_score DOUBLE PRECISION CHECK (severe_toxicity_score >= 0.0 AND severe_toxicity_score <= 1.0),
    obscene_score DOUBLE PRECISION CHECK (obscene_score >= 0.0 AND obscene_score <= 1.0),
    threat_score DOUBLE PRECISION CHECK (threat_score >= 0.0 AND threat_score <= 1.0),
    insult_score DOUBLE PRECISION CHECK (insult_score >= 0.0 AND insult_score <= 1.0),
    identity_attack_score DOUBLE PRECISION CHECK (identity_attack_score >= 0.0 AND identity_attack_score <= 1.0),
    sentiment_score DOUBLE PRECISION,
    is_edited BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_user_created ON messages(user_id, created_at DESC);
CREATE INDEX idx_messages_channel_created ON messages(channel_id, created_at DESC);
CREATE INDEX idx_messages_toxicity ON messages(toxicity_score DESC) WHERE toxicity_score > 0.3;
CREATE INDEX idx_messages_created_at ON messages(created_at DESC);

-- Moderation actions log
CREATE TABLE moderation_actions (
    id SERIAL PRIMARY KEY,
    action_uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    message_id BIGINT REFERENCES messages(message_id) ON DELETE SET NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('warning', 'timeout', 'kick', 'ban', 'unban')),
    reason TEXT NOT NULL,
    toxicity_score DOUBLE PRECISION CHECK (toxicity_score >= 0.0 AND toxicity_score <= 1.0),
    behavior_score DOUBLE PRECISION CHECK (behavior_score >= 0.0 AND behavior_score <= 1.0),
    context_score DOUBLE PRECISION CHECK (context_score >= 0.0 AND context_score <= 1.0),
    final_score DOUBLE PRECISION CHECK (final_score >= 0.0 AND final_score <= 1.0),
    is_automated BOOLEAN DEFAULT TRUE,
    moderator_id BIGINT,
    moderator_name TEXT,
    expires_at TIMESTAMPTZ,
    appealed BOOLEAN DEFAULT FALSE,
    appeal_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_moderation_user_created ON moderation_actions(user_id, created_at DESC);
CREATE INDEX idx_moderation_type ON moderation_actions(action_type);
CREATE INDEX idx_moderation_automated ON moderation_actions(is_automated, created_at DESC);
CREATE INDEX idx_moderation_expires ON moderation_actions(expires_at) WHERE expires_at IS NOT NULL;

-- Appeal tracking
CREATE TABLE appeals (
    id SERIAL PRIMARY KEY,
    action_id INTEGER NOT NULL REFERENCES moderation_actions(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    appeal_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied', 'withdrawn')),
    review_notes TEXT,
    reviewed_by BIGINT,
    reviewed_by_name TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_appeals_status ON appeals(status, created_at DESC);
CREATE INDEX idx_appeals_user ON appeals(user_id, created_at DESC);

-- Update moderation_actions to link appeals
ALTER TABLE moderation_actions 
    ADD CONSTRAINT fk_appeal 
    FOREIGN KEY (appeal_id) 
    REFERENCES appeals(id) 
    ON DELETE SET NULL;

-- Brigade detection events
CREATE TABLE brigade_events (
    id SERIAL PRIMARY KEY,
    event_uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    participant_count INTEGER NOT NULL CHECK (participant_count > 0),
    confidence_score DOUBLE PRECISION NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    detection_type TEXT NOT NULL CHECK (detection_type IN ('join_spike', 'message_similarity', 'coordinated_activity')),
    source_hint TEXT,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_brigade_detected ON brigade_events(detected_at DESC);
CREATE INDEX idx_brigade_resolved ON brigade_events(is_resolved, detected_at DESC);

-- Brigade participants (many-to-many)
CREATE TABLE brigade_participants (
    brigade_id INTEGER NOT NULL REFERENCES brigade_events(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    participation_score DOUBLE PRECISION CHECK (participation_score >= 0.0 AND participation_score <= 1.0),
    joined_during_event BOOLEAN DEFAULT FALSE,
    message_count INTEGER DEFAULT 0 CHECK (message_count >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (brigade_id, user_id)
);

CREATE INDEX idx_brigade_participants_user ON brigade_participants(user_id);

-- Configuration storage
CREATE TABLE configuration (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Metrics and statistics
CREATE TABLE daily_stats (
    date DATE PRIMARY KEY,
    total_messages INTEGER DEFAULT 0,
    flagged_messages INTEGER DEFAULT 0,
    warnings_issued INTEGER DEFAULT 0,
    timeouts_issued INTEGER DEFAULT 0,
    kicks_issued INTEGER DEFAULT 0,
    bans_issued INTEGER DEFAULT 0,
    brigades_detected INTEGER DEFAULT 0,
    avg_toxicity DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Functions and triggers

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_messages_updated_at BEFORE UPDATE ON messages
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_appeals_updated_at BEFORE UPDATE ON appeals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_configuration_updated_at BEFORE UPDATE ON configuration
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Update user toxicity average when message is added
CREATE OR REPLACE FUNCTION update_user_toxicity_avg()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE users
    SET toxicity_avg = (
        SELECT AVG(toxicity_score)
        FROM messages
        WHERE user_id = NEW.user_id
        AND toxicity_score IS NOT NULL
    ),
    total_messages = total_messages + 1,
    first_message_at = COALESCE(first_message_at, NEW.created_at)
    WHERE user_id = NEW.user_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_stats_on_message AFTER INSERT ON messages
    FOR EACH ROW EXECUTE FUNCTION update_user_toxicity_avg();

-- Update user action counts
CREATE OR REPLACE FUNCTION update_user_action_counts()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE users
    SET 
        warnings = warnings + CASE WHEN NEW.action_type = 'warning' THEN 1 ELSE 0 END,
        timeouts = timeouts + CASE WHEN NEW.action_type = 'timeout' THEN 1 ELSE 0 END,
        kicks = kicks + CASE WHEN NEW.action_type = 'kick' THEN 1 ELSE 0 END,
        bans = bans + CASE WHEN NEW.action_type = 'ban' THEN 1 ELSE 0 END,
        last_action_at = NEW.created_at
    WHERE user_id = NEW.user_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_counts_on_action AFTER INSERT ON moderation_actions
    FOR EACH ROW EXECUTE FUNCTION update_user_action_counts();

-- Grant permissions (adjust as needed)
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO usmca_bot_user;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO usmca_bot_user;

-- Insert default configuration
INSERT INTO configuration (key, value, description) VALUES
    ('thresholds', '{"warning": 0.35, "timeout": 0.55, "kick": 0.75, "ban": 0.88}'::jsonb, 'Toxicity score thresholds for actions'),
    ('timeouts', '{"first": 3600, "second": 86400, "third": 604800}'::jsonb, 'Timeout durations in seconds'),
    ('brigade', '{"joins_per_minute": 5, "similar_messages": 3, "time_window": 300}'::jsonb, 'Brigade detection parameters'),
    ('new_account_days', '7'::jsonb, 'Days to consider an account "new"'),
    ('new_account_multiplier', '1.25'::jsonb, 'Stricter threshold multiplier for new accounts'),
    ('repeat_offender_multiplier', '1.4'::jsonb, 'Stricter threshold multiplier for repeat offenders')
ON CONFLICT (key) DO NOTHING;

-- Create views for common queries

-- Active timeouts view
CREATE OR REPLACE VIEW active_timeouts AS
SELECT 
    ma.id,
    ma.user_id,
    u.username,
    ma.expires_at,
    ma.created_at,
    ma.reason
FROM moderation_actions ma
JOIN users u ON ma.user_id = u.user_id
WHERE ma.action_type = 'timeout'
AND ma.expires_at > NOW()
ORDER BY ma.expires_at;

-- High-risk users view
CREATE OR REPLACE VIEW high_risk_users AS
SELECT 
    u.user_id,
    u.username,
    u.toxicity_avg,
    u.warnings,
    u.timeouts,
    u.kicks,
    u.risk_level,
    u.last_action_at
FROM users u
WHERE u.risk_level IN ('orange', 'red')
OR u.toxicity_avg > 0.5
ORDER BY u.toxicity_avg DESC, u.last_action_at DESC;

-- Recent moderation summary
CREATE OR REPLACE VIEW recent_moderation_summary AS
SELECT 
    DATE(created_at) as date,
    action_type,
    COUNT(*) as count,
    AVG(final_score) as avg_score,
    COUNT(*) FILTER (WHERE is_automated = true) as automated_count,
    COUNT(*) FILTER (WHERE is_automated = false) as manual_count
FROM moderation_actions
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at), action_type
ORDER BY date DESC, action_type;

COMMENT ON TABLE users IS 'Discord user profiles with behavior tracking';
COMMENT ON TABLE messages IS 'Message archive for pattern analysis and audit trail';
COMMENT ON TABLE moderation_actions IS 'Log of all moderation actions taken';
COMMENT ON TABLE appeals IS 'User appeals of moderation actions';
COMMENT ON TABLE brigade_events IS 'Detected brigade/coordinated attack events';
COMMENT ON TABLE configuration IS 'Bot configuration storage';
COMMENT ON TABLE daily_stats IS 'Daily aggregated statistics';