#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLCHAIN_SETUP=""
ARCH="x86"

usage() {
    echo "Usage: $0 [--toolchain=<path>] [--arch=<name>]" >&2
    echo "Builds the instance-startup-delay C service using the SDK toolchain." >&2
    echo "--toolchain is required; --arch defaults to ${ARCH}." >&2
}

for arg in "$@"; do
    case "${arg}" in
        --toolchain=*)
            TOOLCHAIN_SETUP="${arg#*=}"
            ;;
        --arch=*)
            ARCH="${arg#*=}"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: ${arg}" >&2
            usage
            exit 1
            ;;
    esac
done

SRC_DIR="${SCRIPT_DIR}/instance-startup-delay-c"
BUILD_DIR="${SCRIPT_DIR}/build/${ARCH}/instance-startup-delay-c"
OUT_DIR="${SRC_DIR}/${ARCH}"

if [[ -z "${TOOLCHAIN_SETUP}" ]]; then
    echo "Missing required argument: --toolchain=<path>" >&2
    usage
    exit 1
fi

if [[ ! -f "${TOOLCHAIN_SETUP}" ]]; then
    echo "Toolchain setup file not found: ${TOOLCHAIN_SETUP}" >&2
    exit 1
fi

# shellcheck disable=SC1090
. "${TOOLCHAIN_SETUP}"

mkdir -p "${BUILD_DIR}"

cd "${BUILD_DIR}"
cmake "${SRC_DIR}"
make -j"$(nproc)"

mkdir -p "${OUT_DIR}"
# Unlink first: if a previous instance of the binary is still running, the file
# is "busy" and cannot be overwritten in place. Removing the directory entry
# lets us drop in a fresh file while the running process keeps the old inode.
rm -f "${OUT_DIR}/startup-delay-demo-service"
cp "${BUILD_DIR}/startup-delay-demo-service" "${OUT_DIR}/startup-delay-demo-service"

echo "Built ${OUT_DIR}/startup-delay-demo-service"
