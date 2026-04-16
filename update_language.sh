#!/bin/bash
# Script to update default_language from Thai to Malay in database

echo "🔄 Updating default_language from 'th' to 'ms'..."

# Run SQL migration
docker-compose exec -T postgres psql -U supoclip -d supoclip <<-EOSQL
    -- Update existing users
    UPDATE "user"
    SET default_language = 'ms'
    WHERE default_language = 'th' OR default_language IS NULL;

    -- Show results
    SELECT
        'Total users updated to Malay:' as message,
        COUNT(*) as count
    FROM "user"
    WHERE default_language = 'ms';
EOSQL

echo "✅ Language update complete!"
echo ""
echo "📊 Verify with:"
echo "  docker-compose exec postgres psql -U supoclip -d supoclip -c \"SELECT default_language, COUNT(*) FROM \\\"user\\\" GROUP BY default_language;\""
