FROM python:3.12-alpine

# git + ssh for pushing to GitHub, ffmpeg for audio concatenation
RUN apk add --no-cache git git-lfs openssh-client ffmpeg && git lfs install

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create appuser (uid 1000) and fix ownership
RUN addgroup -g 1000 appuser && adduser -D -u 1000 -G appuser appuser \
    && mkdir -p output \
    && chown -R appuser:appuser /app \
    && chmod +x /app/entrypoint.sh

ENV HOME="/home/appuser"

USER 1000
# entrypoint.sh copies SSH key to /tmp (outside k8s volume management),
# sets chmod 400, exports GIT_SSH_COMMAND, then exec's python main.py "$@"
# Use ENTRYPOINT so k8s args (e.g. --test) are forwarded as $@
ENTRYPOINT ["/app/entrypoint.sh"]
