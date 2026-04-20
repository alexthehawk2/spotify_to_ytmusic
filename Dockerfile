# Use the official Playwright Python image which comes with all browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only Chromium for Playwright to save space/RAM
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the application
# We use --host 0.0.0.0 for Azure
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
