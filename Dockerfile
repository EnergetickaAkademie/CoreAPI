FROM python:3.13-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ .

# Copy presentations directory
COPY presentations/ ./presentations/

# Expose the port
EXPOSE 5000

# Run the application
CMD ["python", "main.py"]
