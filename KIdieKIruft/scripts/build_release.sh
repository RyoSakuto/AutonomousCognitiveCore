#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PACKAGE_DIR="spielpaket_vertical_slice"
DIST_DIR="${REPO_ROOT}/dist"
ARTIFACT_NAME="${PACKAGE_DIR}-release.tar.gz"
ARTIFACT_PATH="${DIST_DIR}/${ARTIFACT_NAME}"

# Deterministic timestamp for reproducible archives (overridable for standards tooling).
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-0}"

cd "${REPO_ROOT}"

if ! command -v tar >/dev/null 2>&1; then
  echo "Fehler: 'tar' ist nicht installiert." >&2
  exit 1
fi

if ! command -v gzip >/dev/null 2>&1; then
  echo "Fehler: 'gzip' ist nicht installiert." >&2
  exit 1
fi

required_paths=(
  "${PACKAGE_DIR}/README.md"
  "${PACKAGE_DIR}/start_game.sh"
  "${PACKAGE_DIR}/CHANGELOG_SHORT.md"
  "${PACKAGE_DIR}/VERSION"
  "${PACKAGE_DIR}/game"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "${path}" ]]; then
    echo "Fehler: Erwarteter Pfad fehlt: ${path}" >&2
    exit 1
  fi
done

mkdir -p "${DIST_DIR}"

# Build a deterministic tar stream and gzip it without filename/timestamp header metadata.
tar \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --sort=name \
  --mtime="@${SOURCE_DATE_EPOCH}" \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  --format=gnu \
  -cf - \
  "${PACKAGE_DIR}/README.md" \
  "${PACKAGE_DIR}/VERSION" \
  "${PACKAGE_DIR}/CHANGELOG_SHORT.md" \
  "${PACKAGE_DIR}/start_game.sh" \
  "${PACKAGE_DIR}/run_tests.sh" \
  "${PACKAGE_DIR}/game" \
  "${PACKAGE_DIR}/docs" \
  | gzip -n -9 > "${ARTIFACT_PATH}"

sha256="$(sha256sum "${ARTIFACT_PATH}" | awk '{print $1}')"
size_bytes="$(wc -c < "${ARTIFACT_PATH}")"

echo "Release-Paket erstellt: ${ARTIFACT_PATH}"
echo "Groesse (Bytes): ${size_bytes}"
echo "SHA256: ${sha256}"
