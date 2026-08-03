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
# セキュリティ対応のため、go.mod の依存の一部をバージョンアップ。ビルド時に
# go get で差し替えを実施する（upstream を都度 clone する構成のため、go.mod
# 自体をこのリポジトリ側で保持・編集する形にはなっていない）。
RUN . /versions.env \
    && git clone --depth 1 --branch "${GMS_REF}" "${GMS_REPO}" . \
    && go get \
         golang.org/x/crypto@v0.53.0 \
         golang.org/x/net@v0.56.0 \
         golang.org/x/text@v0.39.0 \
         github.com/jackc/pgx/v5@v5.9.2 \
         github.com/aws/aws-sdk-go-v2/aws/protocol/eventstream@v1.7.8 \
         github.com/aws/aws-sdk-go-v2/service/lambda@v1.88.5 \
         github.com/aws/aws-sdk-go-v2/service/s3@v1.97.3 \
    && go mod tidy \
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
    PYTHONUNBUFFERED=1 \
    PORT=8888

# Chromium の実行に必要な共有ライブラリと、日本語表示用フォント。
# （Chromium 本体は下の PLAYWRIGHT_INSTALL_ONLY で入るので、ここでは依存だけ）
# セキュリティ対応のため libexpat1 をバージョンアップする。libgbm1 等のインストールに
# 付随して入るバージョンではセキュリティ対応が不十分な場合があるため、
# 修正された版 2.8.2-1~deb13u1 を指定する。
#
# セキュリティ対応のため libcairo2 / libcups2t64 を除去する。実際に起動する
# chrome-headless-shell はこれらを参照しないことを readelf -d / strings で
# 確認済み。この影響で avahi・krb5/gnutls/p11-kit チェーンもインストールされなく
# なる（apt-cache rdepends --installed で他パッケージからの依存が無いことを
# 確認済み）。
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      fonts-noto-cjk \
      libasound2t64 \
      libatk-bridge2.0-0t64 \
      libatk1.0-0t64 \
      libatspi2.0-0t64 \
      libdbus-1-3 \
      libdrm2 \
      libexpat1=2.8.2-1~deb13u1 \
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

# 脆弱性対策のため perl 関連のパッケージを除去。perl-base はベースイメージの
# Essential パッケージだが、除去後は apt/dpkg を使わないため、Essential 除去
# 特有のリスクはここでは当たらない。
RUN apt-get purge -y --allow-remove-essential perl-base

# セキュリティ対応のため gzip も除去する。perl-base と同じ扱い（Essential
# パッケージだが正式なDepends・メンテナスクリプト参照なし、grep で確認済み）。
# diffutils は同様に見えたが dpkg 自身が removal 時に diff コマンドを呼ぶため
# 除去不可（ビルド失敗で判明）、対象から外す。
RUN apt-get purge -y --allow-remove-essential gzip

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

# セキュリティ対応のため、ベースイメージ同梱の pip を26.2にアップグレードする。
COPY requirements.txt ./
RUN pip install --no-cache-dir pip==26.2 && pip install --no-cache-dir -r requirements.txt

# versions.env は実行時にも /app/src/playwright_driver.py が import 時に読む
COPY config.json versions.env ./
COPY src/ ./src/
COPY data/ ./data/

EXPOSE 8888

# 認証はデフォルト OFF。MCP_CLIENT_ID 等が環境に無ければ setup_oauth() が None を返す。
# 認証を有効にするには MCP_CLIENT_ID/MCP_CLIENT_SECRET/MCP_BASE_URL をコンテナの
# 環境変数として渡す（.agents/skills/mcp-server/SKILL.md 参照）。
# ポートは --port を固定せず、上の ENV PORT=8888（未上書き時の既定値）に委ねる。
# Cloud Run 等は起動時に PORT を独自の値で上書きするため、そちらが自動的に優先される。
CMD ["python", "-m", "src.server", "--transport", "http", "--host", "0.0.0.0"]
