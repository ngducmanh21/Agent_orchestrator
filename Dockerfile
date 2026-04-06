FROM python:3.12-slim

WORKDIR /app

# Install git for repository cloning
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for repos and indexes
RUN mkdir -p /app/data/repos /app/data/indexes

EXPOSE 8888

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
