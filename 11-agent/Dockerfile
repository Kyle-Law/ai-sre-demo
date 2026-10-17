# In-cluster agent image (step 12): runs both the controller (`operator`) and the
# per-ticket diagnosis Jobs (`investigate`). Built locally and loaded into kind.
FROM python:3.12-slim

ARG KUBECTL_VERSION=v1.37.0
RUN python -c "import os, platform, urllib.request; \
arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[platform.machine()]; \
urllib.request.urlretrieve(f'https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/{arch}/kubectl', '/usr/local/bin/kubectl'); \
os.chmod('/usr/local/bin/kubectl', 0o755)"

WORKDIR /app
COPY pyproject.toml ./
COPY ai_sre_agent ./ai_sre_agent
RUN pip install --no-cache-dir .

USER 65532
ENTRYPOINT ["ai-sre-agent"]
