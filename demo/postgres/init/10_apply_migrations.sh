#!/bin/sh
# Builds the live demo database from the migration files, in order (the team's "deploy").
set -e
for file in /migrations/*.sql; do
  echo "applying $file"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$file"
done
