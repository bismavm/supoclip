-- Migration: Update default_language from Thai to Malay
-- Description: Changes all users with default_language='th' to 'ms'
-- Date: 2026-04-17

-- Update existing users
UPDATE "user"
SET default_language = 'ms'
WHERE default_language = 'th' OR default_language IS NULL;

-- Verify results
SELECT
    COUNT(*) as total_users,
    default_language,
    COUNT(*) FILTER (WHERE default_language = 'ms') as malay_users,
    COUNT(*) FILTER (WHERE default_language = 'th') as thai_users
FROM "user"
GROUP BY default_language;
