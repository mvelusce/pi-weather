FROM python:3.9-slim-bullseye

# Install rtl_433 and dependencies
RUN apt-get update && \
    apt-get install -y rtl-433 libusb-1.0-0 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
RUN pip install prometheus-client

# Copy application code
COPY exporter.py .

CMD ["python", "exporter.py"]
