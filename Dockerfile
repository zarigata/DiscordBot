# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  F3V3R DR34M Team Presents:                                                  ║
# ║  Discord Bot Container - Crafted by Z4R1G4T4                                ║
# ║  [2025] - No System Is Safe!                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# Use Python 3.11 slim as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create config directory and default config files
RUN mkdir -p /app/config

# Create default config files if they don't exist
RUN echo '{\n\
    "ollama": {\n\
        "host": "localhost",\n\
        "port": 11434,\n\
        "model": "llama2:3.2"\n\
    },\n\
    "stable_diffusion": {\n\
        "host": "localhost",\n\
        "port": 7860\n\
    }\n\
}' > /app/config/config.json

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/app:${PATH}"

# Expose port for web dashboard
EXPOSE 5000

# Command to run the bot
CMD ["python", "main.py"]
