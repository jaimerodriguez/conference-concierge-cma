# The sandbox image: everything the agent's tools can touch lives in this container.
FROM python:3.13-slim

# /bin/bash is required by the SDK's tool helpers; curl is handy for the agents.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "anthropic>=2.10" "opentelemetry-sdk>=1.30" \
    "opentelemetry-exporter-otlp-proto-http>=1.30"

# Run as a non-root user. The worker downloads memory stores to /mnt/memory, so it must
# exist and be writable; do not create the per-store directories yourself.
RUN useradd --create-home --uid 10001 sandbox \
    && mkdir -p /workspace /mnt/memory /opt/concierge \
    && chown sandbox:sandbox /workspace /mnt/memory
USER sandbox
WORKDIR /workspace

# COPY keeps the file mode from your checkout and makes root the owner. Set a readable
# mode explicitly, or a checkout with private permissions (0600) leaves the sandbox user
# unable to open the script. /opt/concierge is created above because --chmod would also
# apply to a directory that COPY creates, and 0644 on a directory makes it unreadable.
COPY --chmod=0644 worker.py /opt/concierge/worker.py
CMD ["python", "/opt/concierge/worker.py"]
