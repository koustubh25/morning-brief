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

# Cap Node.js heap so claude subprocesses stay lean
ENV NODE_OPTIONS="--max-old-space-size=100"
# Alpine user 1000 has no home dir — claude CLI needs a writable HOME
ENV HOME="/tmp"
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"

USER 1000
CMD ["python", "main.py"]
