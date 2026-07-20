-- Media Automation Platform — PostgreSQL Initialization
-- This runs once when the PostgreSQL container starts for the first time.

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy text search
CREATE EXTENSION IF NOT EXISTS "unaccent";    -- accent-insensitive search

-- Create a read-only reporting user (optional, for future analytics)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'media_readonly') THEN
        CREATE ROLE media_readonly WITH LOGIN PASSWORD 'readonly_change_this';
        GRANT CONNECT ON DATABASE media_platform TO media_readonly;
        GRANT USAGE ON SCHEMA public TO media_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT ON TABLES TO media_readonly;
    END IF;
END
$$;

-- Create application schema (all tables will go here via Alembic)
CREATE SCHEMA IF NOT EXISTS app;
GRANT ALL PRIVILEGES ON SCHEMA app TO media;

-- Set default search path
ALTER DATABASE media_platform SET search_path TO public, app;

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'Media Platform database initialized successfully.';
END
$$;
