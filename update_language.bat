@echo off
REM Script to update default_language from Thai to Malay in database

echo.
echo =================================================
echo Updating default_language from 'th' to 'ms'...
echo =================================================
echo.

REM Run SQL migration
docker-compose exec -T postgres psql -U supoclip -d supoclip -c "UPDATE \"user\" SET default_language = 'ms' WHERE default_language = 'th' OR default_language IS NULL;"

echo.
echo =================================================
echo Verifying update...
echo =================================================
echo.

REM Show results
docker-compose exec -T postgres psql -U supoclip -d supoclip -c "SELECT default_language, COUNT(*) FROM \"user\" GROUP BY default_language;"

echo.
echo =================================================
echo Language update complete!
echo =================================================
echo.

pause
