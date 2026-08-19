#!/usr/bin/env bash

# 이 스크립트는 애플리케이션을 실행할 원격 서버에서 실행한다.
#
# 전제 조건:
#   - 원격 서버에 Docker, AWS CLI, curl, Nginx가 설치되어 있어야 한다.
#   - 서버는 ECR 이미지를 내려받을 권한이 있어야 한다.
#   - Nginx의 서비스 설정은 NGINX_UPSTREAM_NAME으로 지정한 upstream을 사용해야 한다.
#   - 애플리케이션은 HEALTH_PATH 요청에 HTTP 200을 반환해야 한다.
#
# 배포 순서:
#   1. ECR에서 특정 커밋 태그의 이미지를 내려받는다.
#   2. 현재 서비스 중인 컨테이너 반대편에 새 컨테이너를 실행한다.
#   3. 새 컨테이너의 상태 확인 주소가 HTTP 200을 반환할 때까지 기다린다.
#   4. 성공한 경우에만 Nginx가 새 컨테이너로 요청을 보내도록 전환한다.
#   5. 전환이 끝난 뒤 기존 컨테이너를 중단한다.
#
# 새 컨테이너의 실행이나 상태 확인에 실패하면 기존 컨테이너는 그대로 남는다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 예시:
#   AWS_ACCOUNT_ID=123456789012 \
#   ECR_REPOSITORY=etri-capstone \
#   APP_NAME=etri-capstone \
#   IMAGE_TAG=a1b2c3d \
#   CONTAINER_PORT=8000 \
#   HEALTH_PATH=/health \
#   ./scripts/deploy.sh
: "${AWS_ACCOUNT_ID:?AWS 계정 번호를 AWS_ACCOUNT_ID로 전달해야 한다.}"
: "${ECR_REPOSITORY:?ECR 저장소 이름을 ECR_REPOSITORY로 전달해야 한다.}"
: "${APP_NAME:?컨테이너 이름의 기준을 APP_NAME으로 전달해야 한다.}"
: "${IMAGE_TAG:?push.sh가 출력한 커밋 태그를 IMAGE_TAG로 전달해야 한다.}"

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
BLUE_PORT="${BLUE_PORT:-8080}"
GREEN_PORT="${GREEN_PORT:-8081}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-2}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.production}"
DEFAULT_UPSTREAM_NAME="${APP_NAME//-/_}_backend"
NGINX_UPSTREAM_NAME="${NGINX_UPSTREAM_NAME:-$DEFAULT_UPSTREAM_NAME}"
NGINX_UPSTREAM_FILE="${NGINX_UPSTREAM_FILE:-/etc/nginx/conf.d/${APP_NAME}-upstream.conf}"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
REMOTE_IMAGE="${ECR_REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "필요한 명령을 찾을 수 없다: $command_name" >&2
    exit 1
  fi
}

require_command aws
require_command curl
require_command docker
require_command nginx
require_command sudo

# AWS_PROFILE은 원격 서버에 프로필이 있을 때만 사용한다.
# 일반적으로는 서버에 연결된 IAM Role을 사용해 별도의 비밀 키를 두지 않는다.
AWS_OPTIONS=(--region "$AWS_REGION")
if [ -n "${AWS_PROFILE:-}" ]; then
  AWS_OPTIONS+=(--profile "$AWS_PROFILE")
fi

BLUE_NAME="${APP_NAME}-blue"
GREEN_NAME="${APP_NAME}-green"

# 현재 서비스 중인 색을 확인하고 반대쪽을 새 배포 슬롯으로 선택한다.
if docker ps --format '{{.Names}}' | grep -qx "$BLUE_NAME"; then
  OLD_NAME="$BLUE_NAME"
  NEW_NAME="$GREEN_NAME"
  NEW_PORT="$GREEN_PORT"
elif docker ps --format '{{.Names}}' | grep -qx "$GREEN_NAME"; then
  OLD_NAME="$GREEN_NAME"
  NEW_NAME="$BLUE_NAME"
  NEW_PORT="$BLUE_PORT"
else
  # 최초 배포에는 기존 컨테이너가 없으므로 blue 슬롯부터 사용한다.
  OLD_NAME=""
  NEW_NAME="$BLUE_NAME"
  NEW_PORT="$BLUE_PORT"
fi

wait_until_healthy() {
  local container_name="$1"
  local host_port="$2"
  local elapsed=0
  local status="000"

  while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(curl -sS -o /dev/null -w '%{http_code}' \
      "http://127.0.0.1:${host_port}${HEALTH_PATH}" 2>/dev/null || true)"
    if [ "$status" = "200" ]; then
      echo "상태 확인 성공: HTTP 200"
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
    elapsed=$((elapsed + HEALTH_INTERVAL))
  done

  echo "상태 확인 실패: 마지막 HTTP 상태 ${status}" >&2
  docker logs --tail 50 "$container_name" >&2 || true
  return 1
}

echo "[1/6] ECR 로그인"
aws ecr get-login-password "${AWS_OPTIONS[@]}" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "[2/6] 배포할 이미지 다운로드"
docker pull --platform "$IMAGE_PLATFORM" "$REMOTE_IMAGE"

echo "[3/6] 새 배포 슬롯 정리 및 컨테이너 실행"
# NEW_NAME은 현재 트래픽을 받지 않는 슬롯이다.
# 이전 실패 과정에서 남은 컨테이너만 정리하므로 서비스 중인 OLD_NAME은 건드리지 않는다.
docker stop "$NEW_NAME" >/dev/null 2>&1 || true
docker rm "$NEW_NAME" >/dev/null 2>&1 || true

RUN_OPTIONS=(
  --detach
  --name "$NEW_NAME"
  --restart unless-stopped
  --publish "${NEW_PORT}:${CONTAINER_PORT}"
)

# 애플리케이션 환경 파일은 Git에 올리지 않고 원격 서버에 별도로 둔다.
if [ -f "$ENV_FILE" ]; then
  RUN_OPTIONS+=(--env-file "$ENV_FILE")
fi

docker run "${RUN_OPTIONS[@]}" "$REMOTE_IMAGE"

echo "[4/6] 새 컨테이너 상태 확인"
if ! wait_until_healthy "$NEW_NAME" "$NEW_PORT"; then
  docker stop "$NEW_NAME" >/dev/null 2>&1 || true
  docker rm "$NEW_NAME" >/dev/null 2>&1 || true
  echo "새 컨테이너를 제거했다. 기존 서비스는 변경하지 않았다." >&2
  exit 1
fi

echo "[5/6] Nginx 트래픽 전환"
# 기존 upstream 파일을 보관해 Nginx 설정 검증 실패 시 되돌릴 수 있게 한다.
UPSTREAM_BACKUP="$(mktemp)"
HAD_UPSTREAM=0
if sudo test -f "$NGINX_UPSTREAM_FILE"; then
  sudo cat "$NGINX_UPSTREAM_FILE" > "$UPSTREAM_BACKUP"
  HAD_UPSTREAM=1
fi

echo "upstream ${NGINX_UPSTREAM_NAME} { server 127.0.0.1:${NEW_PORT}; }" \
  | sudo tee "$NGINX_UPSTREAM_FILE" >/dev/null

if ! sudo nginx -t; then
  if [ "$HAD_UPSTREAM" -eq 1 ]; then
    sudo cp "$UPSTREAM_BACKUP" "$NGINX_UPSTREAM_FILE"
  else
    sudo rm "$NGINX_UPSTREAM_FILE"
  fi
  docker stop "$NEW_NAME" >/dev/null 2>&1 || true
  docker rm "$NEW_NAME" >/dev/null 2>&1 || true
  echo "Nginx 설정을 되돌렸다. 기존 서비스는 변경하지 않았다." >&2
  exit 1
fi

sudo nginx -s reload
rm -f "$UPSTREAM_BACKUP"

echo "[6/6] 기존 컨테이너 정리"
if [ -n "$OLD_NAME" ]; then
  # Nginx 전환 이후 잠시 기다려 기존 요청이 끝날 시간을 준다.
  sleep 2
  docker stop "$OLD_NAME" >/dev/null 2>&1 || true
  docker rm "$OLD_NAME" >/dev/null 2>&1 || true
fi

docker image prune -f >/dev/null 2>&1

echo
echo "배포 완료"
echo "실행 컨테이너: $NEW_NAME"
echo "배포 이미지: $REMOTE_IMAGE"
