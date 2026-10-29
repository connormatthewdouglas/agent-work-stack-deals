# Runs the published lantern-works-deals-mcp stdio server (used by Glama build/inspection checks).
# No network ports: MCP over stdin/stdout. Run: docker run -i --rm <image>
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir lantern-works-deals-mcp==0.3.21 \
 && useradd --create-home --uid 10001 mcp
USER mcp
ENTRYPOINT ["lantern-works-deals-mcp"]
