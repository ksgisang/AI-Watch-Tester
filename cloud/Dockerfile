FROM python:3.12-slim

# System dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (cloud backend)
COPY cloud/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium only (saves ~400MB vs all browsers)
RUN pip install --no-cache-dir playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# Install AAT core from project root
COPY pyproject.toml ./pyproject.toml
COPY README.md ./README.md
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Copy cloud application
COPY cloud/app/ ./app/
COPY cloud/scripts/ ./scripts/

# Create directories for runtime data
RUN mkdir -p screenshots uploads

# Non-root user for security
RUN useradd -m -r appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
