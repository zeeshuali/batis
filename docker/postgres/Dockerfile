# PostGIS 16 plus pgvector (for the AI assistant's RAG embeddings).
# Same major version and base image as postgis/postgis:16-3.4 so the existing
# data volume (batis_postgres_data) stays compatible.
FROM postgis/postgis:16-3.4
# bullseye-pgdg was moved to the apt archive after bullseye went EOL.
RUN sed -i 's|apt.postgresql.org/pub/repos/apt|apt-archive.postgresql.org/pub/repos/apt|' /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgvector \
 && rm -rf /var/lib/apt/lists/*
