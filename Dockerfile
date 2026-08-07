# Stdlib-only app: there is no requirements.txt and no package install step, so there is
# nothing to break on a rebuild in a year's time. Alpine + the interpreter is the whole
# image (~60 MB), which also means a fast cold start on the zone.
FROM python:3.12-alpine

WORKDIR /app
COPY app.py systems.json ./
COPY static/ ./static/

# 8080 matches runtime.container.port in openhost.toml. Overridable so the same image
# runs under docker-compose on the Mac without editing anything.
ENV PYTHONUNBUFFERED=1 \
    YOS_PORT=8080

EXPOSE 8080

# Fails the container rather than serving a half-dead app: if the HTTP thread has wedged,
# the orchestrator finds out instead of the request just hanging forever.
HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status==200 else 1)"

CMD ["python", "-u", "app.py"]
