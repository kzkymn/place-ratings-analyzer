---
name: setup-environment
description: "Set up the environment to run this MCP server: WSL, Docker, image build, and Claude Desktop registration. Activate when the user is setting up from scratch, asks how to install prerequisites, or needs to register the server in an MCP client."
---

The product runs as a Docker image — Docker is the only supported setup path.
(Local non-Docker execution exists only for development; see `mcp-server` and `run-tests`.)

## 1. WSL (Windows only)

The toolchain requires a Linux environment. On Windows, install WSL first:

1. Open PowerShell **as Administrator** and run `wsl --install`
2. Restart Windows when prompted
3. On the first launch of Ubuntu, create a Linux username and password
4. Do everything below inside the WSL (Ubuntu) terminal

macOS/Linux: skip this section.

## 2. Docker

Either of the following works. Docker Engine inside WSL avoids Docker Desktop's
commercial-license requirement (Docker Desktop is paid for larger companies):

**Option A — Docker Engine inside WSL/Linux (no license concerns):**

```bash
sudo apt-get update && sudo apt-get install -y docker.io
sudo usermod -aG docker "$USER"   # then close and reopen the terminal
```

**Option B — Docker Desktop (Windows/macOS):** install from
https://www.docker.com/products/docker-desktop/ (it manages WSL integration itself).
Check your company's license situation before choosing this at work.

## 3. Build the image

```bash
git clone <this-repository> && cd <repository-dir>
docker build -t place-ratings-analyzer .
```

## 4. Register in Claude Desktop (stdio)

Claude Desktop's HTTP/HTTPS custom connectors originate from Anthropic's cloud and can
never reach `localhost`, so **stdio is the only usable mode** on the same machine.
Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "place-ratings-analyzer": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--shm-size=1g", "place-ratings-analyzer:latest", "python", "-m", "src.server"]
    }
  }
}
```

On Windows, Claude Desktop runs `docker` on the Windows side; with Docker Desktop this
reaches the same daemon. With Option A (Engine inside WSL), use
`"command": "wsl", "args": ["-e", "docker", "run", "-i", "--rm", "--shm-size=1g", "place-ratings-analyzer:latest", "python", "-m", "src.server"]`.

## 5. Other MCP clients on the same machine (HTTP)

```bash
docker compose up --build   # → http://localhost:8888/mcp (no auth)
```

OAuth setup: see the `oauth-setup` skill. Deploying for remote access: see the
`cloud-run-deploy` skill.
