# Fix: Update the base image to resolve the vulnerability
FROM python:3.14.0a7-slim-bullseye AS base

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Install system dependencies if needed (e.g., for libraries with C extensions)
# (Currently none needed for this specific app)

# Create a non-root user and group for security
# Use a high UID/GID (e.g., 10001) in the recommended range
RUN addgroup --gid 10001 appgroup && \
    adduser --uid 10001 --ingroup appgroup --shell /bin/sh --no-create-home appuser

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# Copy files as root first, then change ownership later
COPY . .

# Ensure the non-root user owns the application files
# chown still correctly uses the names which map to the desired UIDs/GIDs
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
# FIX: Use the numeric UID directly to explicitly meet CKV_CHOREO_1 requirement
USER 10001

# Expose the port Gunicorn will run on (must match the CMD)
EXPOSE 5001

# Set default command to run the app with Gunicorn
# - Bind to 0.0.0.0 to accept connections from outside the container
# - Use environment variable PORT or default to 5001
# - Specify the number of workers (adjust based on your server resources)
# - Point to the Flask app instance (filename:variable name -> app:app)
# - Use environment variables for Gunicorn config where possible
ENV GUNICORN_CMD_ARGS="--workers 4 --bind 0.0.0.0:5001"
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5001", "app:app"]