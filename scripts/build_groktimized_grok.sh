#!/bin/sh
set -eu

SOURCE_REPO="${GROK_BUILD_SOURCE_REPO:-https://github.com/xai-org/grok-build.git}"
SOURCE_REV="8a14c91d88875a831a38b3a066b1683116bcb31c"
PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PATCH_FILE="$PROJECT_ROOT/integrations/grok-build/groktimized-ui.patch"
NOTICE_FILE="$PROJECT_ROOT/integrations/grok-build/GROKTIMIZER-NOTICE.txt"
OUTPUT_DIR="${GROKTIMIZED_BUILD_OUTPUT:-$PROJECT_ROOT/dist/grok-build-ui}"
PLATFORM="$(uname -s)"
ARCH="$(uname -m)"

if [ "$PLATFORM" != "Darwin" ] || [ "$ARCH" != "arm64" ]; then
  printf '%s\n' 'This release recipe currently targets macOS on Apple Silicon.' >&2
  exit 1
fi

for command in git cargo dotslash zip shasum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Missing build dependency: %s\n' "$command" >&2
    exit 1
  fi
done

worktree="$(mktemp -d "${TMPDIR:-/tmp}/groktimized-grok-build.XXXXXX")"
trap 'rm -rf "$worktree"' EXIT HUP INT TERM

git clone --filter=blob:none "$SOURCE_REPO" "$worktree/source"
git -C "$worktree/source" checkout --detach "$SOURCE_REV"
git -C "$worktree/source" apply --unidiff-zero --check "$PATCH_FILE"
git -C "$worktree/source" apply --unidiff-zero "$PATCH_FILE"

(
  cd "$worktree/source"
  cargo test -p xai-grok-pager groktimized
  cargo build -p xai-grok-pager-bin --release
)

bundle="$worktree/bundle"
mkdir -p "$bundle" "$OUTPUT_DIR"
cp "$worktree/source/target/release/xai-grok-pager" "$bundle/grok"
cp "$worktree/source/LICENSE" "$bundle/LICENSE"
cp "$worktree/source/THIRD-PARTY-NOTICES" "$bundle/THIRD-PARTY-NOTICES"
cp "$NOTICE_FILE" "$bundle/GROKTIMIZER-NOTICE.txt"

archive="$OUTPUT_DIR/groktimized-grok-build-darwin-arm64.zip"
(
  cd "$bundle"
  zip -q -9 "$archive" grok LICENSE THIRD-PARTY-NOTICES GROKTIMIZER-NOTICE.txt
)
shasum -a 256 "$archive" > "$archive.sha256"
printf 'Built %s\n' "$archive"
cat "$archive.sha256"
