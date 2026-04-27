# Lambda Web Adapter as an extension
FROM --platform=linux/arm64 public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 AS adapter

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /var/task

# Install the adapter into Lambda's extensions dir
COPY --from=adapter /lambda-adapter /opt/extensions/lambda-adapter

# Hardening + perf
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AWS_LWA_INVOKE_MODE=response_stream \
    AWS_LWA_READINESS_CHECK_PATH=/mcp

# Install uv, then deps
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App code
COPY shared/ ./shared/
COPY prospecting_mcp/ ./prospecting_mcp/

CMD [".venv/bin/python", "-m", "prospecting_mcp.server"]
