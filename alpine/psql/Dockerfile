# Use the official Alpine image as a base
FROM alpine:3.22

# Install the PostgreSQL client # comment to rebuild.
RUN apk --no-cache add postgresql-client

# Set the working directory
WORKDIR /app

# Copy your script or SQL files into the container
# COPY your_script.sh /app/your_script.sh
# COPY your_sql_file.sql /app/your_sql_file.sql

# Ensure the script is executable (if you have a script)
# RUN chmod +x /app/your_script.sh

# Set the entrypoint to the psql client or your script
# ENTRYPOINT ["/app/your_script.sh"]
# Or if you want to use psql directly
ENTRYPOINT ["psql"]

# Optionally, you can set default command arguments
# CMD ["-h", "your_host", "-U", "your_user", "-d", "your_db"]
