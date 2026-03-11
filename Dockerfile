FROM python:3.12-alpine

# git + ssh for pushing to GitHub; nodejs for claude CLI
RUN apk add --no-cache git openssh-client nodejs npm

WORKDIR /app

# Install claude CLI from pre-downloaded tarball — no npm registry hit at build time
COPY anthropic-ai-claude-code-2.1.71.tgz .
RUN npm install -g ./anthropic-ai-claude-code-2.1.71.tgz \
    && rm anthropic-ai-claude-code-2.1.71.tgz \
    && npm cache clean --force

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create appuser (uid 1000) and fix ownership
RUN addgroup -g 1000 appuser && adduser -D -u 1000 -G appuser appuser \
    && mkdir -p output \
    && chown -R appuser:appuser /app \
    && chmod +x /app/entrypoint.sh

# Cap Node.js heap so claude subprocesses stay lean
ENV NODE_OPTIONS="--max-old-space-size=100"
# Alpine user 1000 has no home dir — claude CLI needs a writable HOME
ENV HOME="/home/appuser"
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"

USER 1000
# entrypoint.sh copies SSH key to /tmp (outside k8s volume management),
# sets chmod 400, exports GIT_SSH_COMMAND, then exec's python main.py "$@"
# Use ENTRYPOINT so k8s args (e.g. --test) are forwarded as $@
ENTRYPOINT ["/app/entrypoint.sh"]
