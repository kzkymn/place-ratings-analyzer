# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: Go scraper のビルド
#
# google-maps-scraper/ は .gitignore 対象でこのリポジトリに同梱されていない
# （ローカル開発では手動で clone する。手順は .agents/skills/build-go/ 参照）。
# イメージを本リポジトリのクリーンな clone だけから再現できるよう、ここで upstream から取得する。
# ---------------------------------------------------------------------------
# ベースイメージの major.minor は versions.env の GO_VERSION に追従させること
# （FROM にはファイルの値を注入できないためここだけ手動。不整合はビルドが失敗して教えてくれる）
FROM golang:1.26-trixie AS scraper-builder

ARG GMS_REPO=https://github.com/gosom/google-maps-scraper.git

WORKDIR /build
# バージョンピンは versions.env（single source of truth、run_mcp_server.py も同じものを読む）
COPY versions.env /versions.env
RUN . /versions.env \
    && git clone --depth 1 --branch "${GMS_REF}" "${GMS_REPO}" . \
    && go mod download \
    && CGO_ENABLED=0 go build -ldflags="-w -s" -o /out/google_maps_scraper .

# ---------------------------------------------------------------------------
# Stage 2: 実行イメージ（Python + FastMCP + scraper バイナリ + Chromium）
#
# Playwright driver は src/playwright_driver.py がビルド時に組み立てる（廃止済みCDNの
# 回避策。背景・PW_CLI_VERSION と GMS_REF の結合はそのモジュールの docstring 参照。
# ローカル実行時も src/pipeline.py 経由で同じモジュールが同じことをする）。
# ---------------------------------------------------------------------------
FROM python:3.12-slim-trixie

ENV PLAYWRIGHT_DRIVER_PATH=/opt/ms-playwright-go \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PYTHONUNBUFFERED=1

# Chromium の実行に必要な共有ライブラリと、日本語表示用フォント。
# （Chromium 本体は下の PLAYWRIGHT_INSTALL_ONLY で入るので、ここでは依存だけ）
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      fonts-noto-cjk \
      libasound2t64 \
      libatk-bridge2.0-0t64 \
      libatk1.0-0t64 \
      libatspi2.0-0t64 \
      libcairo2 \
      libcups2t64 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libglib2.0-0t64 \
      libnspr4 \
      libnss3 \
      libpango-1.0-0 \
      libx11-6 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxkbcommon0 \
      libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# driver 組み立てモジュールだけ先にCOPYし、重いダウンロード層をコード変更から切り離す。
# versions.env は /tmp/playwright_driver.py から見た project root（= /）に置く
COPY versions.env /versions.env
COPY src/playwright_driver.py /tmp/playwright_driver.py
RUN python /tmp/playwright_driver.py --dest /opt/ms-playwright-go && rm /tmp/playwright_driver.py

# src/pipeline.py の既定パス（<project_root>/google-maps-scraper/bin/）に置くことで、
# Python 側のパス解決に手を入れずに済ませる。
COPY --from=scraper-builder /out/google_maps_scraper /app/google-maps-scraper/bin/google_maps_scraper

# driver は上で用意済みなので、ここで入るのは Chromium だけ。
RUN PLAYWRIGHT_INSTALL_ONLY=1 /app/google-maps-scraper/bin/google_maps_scraper

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# versions.env は実行時にも /app/src/playwright_driver.py が import 時に読む
COPY config.json versions.env ./
COPY src/ ./src/
COPY data/ ./data/

EXPOSE 8888

# 認証はデフォルト OFF。MCP_CLIENT_ID 等が環境に無ければ setup_oauth() が None を返す。
# 認証を有効にするには docker-compose.auth.yml を重ねて .env を注入する。
CMD ["python", "-m", "src.server", "--transport", "http", "--host", "0.0.0.0", "--port", "8888"]
