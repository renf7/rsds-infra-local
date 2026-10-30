FROM python:3.12.16-slim-trixie
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 pwuser \
    && mkdir /artifacts && chown pwuser:pwuser /artifacts
COPY --chown=pwuser:pwuser test_site.py .
USER pwuser
HEALTHCHECK NONE
CMD ["python", "test_site.py"]
