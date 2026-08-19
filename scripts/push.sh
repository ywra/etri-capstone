#!/usr/bin/env bash

# 이 스크립트는 개발 PC 또는 빌드 서버에서 실행한다.
#
# 역할은 다음 세 단계로 제한한다.
#   1. 현재 소스 코드로 Docker 이미지를 만든다.
#   2. 이미지에 `latest`와 Git 커밋 ID 두 태그를 붙인다.
#   3. 두 이미지를 AWS ECR에 업로드한다.
#
# 실제 애플리케이션을 원격 서버에서 교체하는 일은 deploy.sh가 담당한다.
# 빌드와 운영 반영을 분리하면 이미지 업로드가 끝난 뒤 정확한 버전을 선택해
# 배포할 수 있고, 같은 이미지를 여러 환경에서 다시 사용할 수도 있다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 필요한 값은 스크립트에 직접 적지 않는다.
# 실행 전에 환경 변수로 전달한다.
#
# 예시:
#   AWS_ACCOUNT_ID=123456789012 \
#   ECR_REPOSITORY=etri-capstone \
#   AWS_REGION=ap-northeast-2 \
#   ./scripts/push.sh
: "${AWS_ACCOUNT_ID:?AWS 계정 번호를 AWS_ACCOUNT_ID로 전달해야 한다.}"
: "${ECR_REPOSITORY:?ECR 저장소 이름을 ECR_REPOSITORY로 전달해야 한다.}"

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
IMAGE_PLATFORM="${IMAGE_PLATFORM:-linux/amd64}"

# AWS_PROFILE은 개발 PC에서 여러 AWS 계정을 구분할 때만 사용한다.
# 지정하지 않으면 AWS CLI의 기본 인증 정보를 사용한다.
AWS_OPTIONS=(--region "$AWS_REGION")
if [ -n "${AWS_PROFILE:-}" ]; then
  AWS_OPTIONS+=(--profile "$AWS_PROFILE")
fi

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "필요한 명령을 찾을 수 없다: $command_name" >&2
    exit 1
  fi
}

require_command aws
require_command docker
require_command git

if [ ! -f "$PROJECT_DIR/Dockerfile" ]; then
  echo "프로젝트 루트에 Dockerfile이 필요하다: $PROJECT_DIR/Dockerfile" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker가 실행 중이지 않다." >&2
  exit 1
fi

# 커밋 ID 태그는 어떤 소스에서 만든 이미지인지 추적하는 식별자다.
# `latest`는 편리한 별칭이지만 시간이 지나면 다른 이미지를 가리킬 수 있다.
# 운영 배포에서는 아래 GIT_TAG처럼 변하지 않는 태그를 사용하는 편이 안전하다.
GIT_TAG="$(git -C "$PROJECT_DIR" rev-parse --short HEAD)"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${ECR_REGISTRY}/${ECR_REPOSITORY}"

echo "[1/4] AWS ECR 로그인"
aws ecr get-login-password "${AWS_OPTIONS[@]}" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

echo "[2/4] ECR 저장소 확인"
if ! aws ecr describe-repositories \
  --repository-names "$ECR_REPOSITORY" \
  "${AWS_OPTIONS[@]}" >/dev/null 2>&1; then
  # 교육용 예시는 저장소가 없으면 생성한다.
  # 실제 조직에서는 인프라 관리 도구가 미리 만든 저장소만 사용하도록 제한할 수 있다.
  aws ecr create-repository \
    --repository-name "$ECR_REPOSITORY" \
    "${AWS_OPTIONS[@]}" >/dev/null
fi

echo "[3/4] Docker 이미지 빌드"
docker buildx create \
  --use \
  --name etri-capstone-builder \
  --driver docker-container >/dev/null 2>&1 \
  || docker buildx use etri-capstone-builder

echo "[4/4] Docker 이미지 빌드 및 ECR 업로드"
docker buildx build \
  --platform "$IMAGE_PLATFORM" \
  --tag "${IMAGE_URI}:${GIT_TAG}" \
  --tag "${IMAGE_URI}:latest" \
  --file "$PROJECT_DIR/Dockerfile" \
  --push \
  "$PROJECT_DIR"

echo
echo "업로드 완료"
echo "배포 이미지: ${IMAGE_URI}:${GIT_TAG}"
echo
echo "원격 서버에서는 같은 IMAGE_TAG를 지정해 deploy.sh를 실행한다."
echo "IMAGE_TAG=${GIT_TAG} ./scripts/deploy.sh"
