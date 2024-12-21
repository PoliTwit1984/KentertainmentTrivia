FROM python:3.11-slim

WORKDIR /app

# Install development dependencies
RUN pip install --no-cache-dir \
    watchdog \
    python-dotenv \
    flask[async]

# Only copy and install requirements, rest comes from volume mount
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Development port
EXPOSE 5001

# Use flask run for development (actual command comes from docker-compose.yml)
CMD ["flask", "run", "--host=0.0.0.0", "--port=5001", "--debug"]
