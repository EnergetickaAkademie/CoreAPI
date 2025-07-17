FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy configuration file
COPY users_config.toml /users_config.toml

# Copy source code
COPY src/ .

# Expose the port
EXPOSE 5000

# Run the application
CMD ["python", "main.py"]
