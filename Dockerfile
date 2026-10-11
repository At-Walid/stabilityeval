# syntax=docker/dockerfile:1
# StableAgent 1.0.0: the Streamlit GUI (replay mode by default, no API key needed) and the CLI.
#
#   docker build -t stableagent:1.0.0 .
#   docker run -p 8501:8501 -v ./results:/app/results stableagent:1.0.0            # GUI
#   docker run --rm -v ./results:/app/results stableagent:1.0.0 stableagent --help
#
# API keys are never part of the image: live mode takes them at run time
# (docker run -e ANTHROPIC_API_KEY=... -e OPENAI_API_KEY=..., or the key field of the GUI for
# Anthropic).
#
# Behind a proxy or antivirus that intercepts HTTPS, give pip a CA bundle that includes its root
# certificate; it is used for the build only and never stored in the image:
#   docker build --secret id=ca_bundle,src=ca-bundle.pem -t stableagent:1.0.0 .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Pinned runtime dependencies first, so code changes do not reinstall them.
COPY requirements.txt ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install -r requirements.txt

# The package (with the MockReplay fixtures of both ICSE pilot experiments: Claude Sonnet 4.6 and
# GPT-4o), the configs, the bundled SWE-bench Lite issues, the pilot database and the exports of
# both experiments, and the reproduction scripts.
COPY pyproject.toml README.md LICENSE ./
COPY .streamlit/config.toml .streamlit/config.toml
COPY stableagent/ stableagent/
COPY configs/ configs/
COPY data/ data/
COPY scripts/ scripts/
# Editable install: the code finds data/ next to the package.
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-deps -e . \
    && useradd --create-home --uid 1000 stableagent \
    && mkdir -p /app/results \
    && chown stableagent:stableagent /app/results

USER stableagent

# The working database lives in the results volume. On first use it starts as a copy of the
# shipped pilot database, so the pilot can be replayed and inspected right away.
ENV DATABASE_URL=sqlite:////app/results/stableagent.db \
    STABLEAGENT_SEED_DB=/app/data/pilot/stableagent_pilot.db

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "stableagent/dashboard/StableAgent.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.fileWatcherType=none"]
