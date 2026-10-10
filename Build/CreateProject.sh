#!/usr/bin/env bash
# Linux counterpart of CreateProject.bat: sets up everything needed to build xLION on Linux and configures it.
#
#   bash Build/CreateProject.sh                configure only (like CreateProject.bat), build dir Build/xLION.linux
#   bash Build/CreateProject.sh --build        ... and build xLION_Headless, xLION, xeditorcli and the asset compilers
#   bash Build/CreateProject.sh --no-packages  skip the apt step (packages already installed / not a Debian-family distro)
#   bash Build/CreateProject.sh --clean        delete the build dir first
#   bash Build/CreateProject.sh --sanitize     a build with AddressSanitizer + UndefinedBehaviorSanitizer, in its own build dir Build/xLION.linux-san (the nightly CI job; see
#                                              source/Platform/xlion_linux_flags.cmake)
#   bash Build/CreateProject.sh --update       bring every repo that follows a branch (ours: main) to the newest commit first
#                                              (third party stays on its pinned commit); the commit of every repo is written to
#                                              <build dir>/manifest.txt, so a build says exactly what it was built from
#
# What it does, in order (every step is safe to run again):
#   1. installs the toolchain and libraries (apt; Ubuntu 24.04+ / Debian 13+, needs sudo)
#   2. builds the project tree CMake expects but, off Windows, will not fetch by itself (the job Install.bat does on
#      Windows): example.lionprj with its Cache/Plugins and Cache/dependencies. Our own repos come from main; third party
#      repos are pinned to the commits this port was tested with.
#   3. configures with CMake + Ninja + clang-20, offline (nothing is fetched during configure)
#
# Run it from a Linux filesystem (e.g. ~/src/xLION), not from /mnt/c or /mnt/d under WSL: those are many times slower.
# Environment: BUILD_DIR (default Build/xLION.linux, or xLION.linux-release for BUILD_TYPE=Release), BUILD_TYPE (Debug or Release, default Debug), GIT_BASE (default https://github.com/LIONant-depot).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANITIZE=0; for a in "$@"; do [ "$a" = --sanitize ] && SANITIZE=1; done
BUILD_TYPE="${BUILD_TYPE:-Debug}"
SUFFIX=""
if [ "$SANITIZE" = 1 ]; then SUFFIX="-san"; fi
if [ "$BUILD_TYPE" = Release ]; then SUFFIX="$SUFFIX-release"; fi       # Debug: xLION.linux, Release: xLION.linux-release
BUILD_DIR="${BUILD_DIR:-$ROOT/Build/xLION.linux$SUFFIX}"
GIT_BASE="${GIT_BASE:-https://github.com/LIONant-depot}"
DO_BUILD=0; DO_PACKAGES=1; DO_CLEAN=0; DO_UPDATE=0
for a in "$@"; do
  case "$a" in
    --build) DO_BUILD=1 ;; --no-packages) DO_PACKAGES=0 ;; --clean) DO_CLEAN=1 ;; --update) DO_UPDATE=1 ;; --sanitize) ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option $a (see --help)"; exit 2 ;;
  esac
done
case "$ROOT" in /mnt/[a-z]/*) echo "warning: $ROOT is a Windows drive mounted in WSL - expect a very slow build; clone to ~/src instead" ;; esac

# ---------------------------------------------------------------------------------------------------------------------
# 1. Packages
#    clang-20: clang 18 crashes on the ECS code. libx11-dev/libvulkan-dev/glslc: the X11 window backend of xGPU and the
#    shader compiler; libshaderc-dev: the material asset compiler (xmaterial.plugin) links the distribution shaderc. zenity + xdg-utils: file dialogs and "open" in the editor (runtime only). libXrandr/libXcursor: runtime.
# ---------------------------------------------------------------------------------------------------------------------
PACKAGES="build-essential git cmake ninja-build pkg-config python3 clang-20 lld-20 libomp-20-dev libvulkan-dev glslc libshaderc-dev libx11-dev libxrandr2 libxcursor1 zenity xdg-utils"
if [ "$DO_PACKAGES" = 1 ]; then
  if command -v apt-get >/dev/null; then
    SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo"
    $SUDO apt-get update -q
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q $PACKAGES
  else
    echo "No apt-get here: install the equivalents of: $PACKAGES"
  fi
fi
command -v clang++-20 >/dev/null || { echo "clang++-20 not found (clang 18 is not enough). Install clang-20 and run again."; exit 1; }

# ---------------------------------------------------------------------------------------------------------------------
# 2. The project tree
# ---------------------------------------------------------------------------------------------------------------------
# clone_at <url> <dir> <ref>: a branch/tag is cloned shallow; a 40 hex commit is fetched shallow. A half finished clone is redone.
# Submodules (msdf-atlas-gen has msdfgen and artery-font-format) are initialised too, also for a clone that already exists.
submodules() { [ -f "$1/.gitmodules" ] && git -C "$1" submodule update -q --init --recursive --depth 1 || true; }
clone_at() {
  local url="$1" dir="$2" ref="$3"
  if [ -d "$dir/.git" ] && git -C "$dir" rev-parse -q --verify HEAD >/dev/null; then
    # --update: a clone that follows a branch or tag (not a pinned 40 hex commit) is moved to its newest commit. The tree is a CI/build
    # checkout: nothing in it is edited by hand, so the reset is safe, and a repo already at the newest commit costs one small fetch.
    if [ "$DO_UPDATE" = 1 ] && ! [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
      git -C "$dir" fetch -q --depth 1 origin "$ref" && git -C "$dir" -c advice.detachedHead=false reset -q --hard FETCH_HEAD
    fi
    submodules "$dir"; return 0
  fi
  rm -rf "$dir"; mkdir -p "$(dirname "$dir")"
  echo "  cloning $(basename "$dir")"
  if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
    git init -q "$dir"; git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$ref"; git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
  else
    git clone -q --depth 1 --branch "$ref" "$url" "$dir"
  fi
  submodules "$dir"
}

PRJ="$ROOT/example.lionprj"
DEPS="$PRJ/Cache/dependencies"
PLUGINS="$PRJ/Cache/Plugins"
echo "== project tree: $PRJ"
clone_at "$GIT_BASE/example.lionprj.git" "$PRJ" main      # an existing example.lionprj is never touched

# our repos (branch main, xproperty's is master)
for d in xresource_pipeline_v2 xeditor xresource_guid xmath xstrtool xLIONCore xundo xECSV2 xresource_mgr xprim_geom xlog xbitmap \
         xscheduler xbmp_tools xserializer xGPU xraw3d xerr xeditor_tools xdelegate xtextfile xcontainer xbits xLIONRender \
         xsource_control xfile xcmdline xcompression actions.imgui toolbar.imgui; do
  clone_at "$GIT_BASE/$d.git" "$DEPS/$d" main
done
clone_at "$GIT_BASE/xproperty.git" "$DEPS/xproperty" master

# the third party libraries are pinned in Build/third_party.txt, which the CMake configure reads (FetchAndPopulate clones them at those commits): nothing to do for them here

# plugins: the project's own Install.sh (the counterpart of Install.bat: clone every plugin, give each its "dependencies" link)
[ -f "$PRJ/Install.sh" ] || { echo "example.lionprj/Install.sh is missing: the project repo is older than the Linux setup (use --update)"; exit 1; }
GIT_BASE="$GIT_BASE" bash "$PRJ/Install.sh" $([ "$DO_UPDATE" = 1 ] && echo --update) || exit 1

# ---------------------------------------------------------------------------------------------------------------------
# 3. Configure (like CreateProject.bat: cmake ../ -B xLION.<platform>)
#    xcmake_tools (Common.cmake) is placed in the build tree up front, then configure runs disconnected from the network.
# ---------------------------------------------------------------------------------------------------------------------
echo "== configure: $BUILD_DIR"
[ "$DO_CLEAN" = 1 ] && rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/_deps"
clone_at "$GIT_BASE/xcmake_tools.git" "$BUILD_DIR/_deps/xcmake_tools" main
# ccache, when it is installed: a rebuild of what did not change (a build from scratch of the same sources) is a few minutes. ccache keys on the compiler, the flags and the preprocessed source (not
# on file times), so a hit is the same object a compile would make. Its entries are compressed (zstd) and it is capped (4G): it can never take the disk. XLION_CCACHE=0 turns it off.
CCACHE_ARGS() { if [ "${XLION_CCACHE:-1}" = 1 ] && command -v ccache >/dev/null 2>&1; then echo "-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"; fi; }
export CCACHE_MAXSIZE="${CCACHE_MAXSIZE:-4G}"
CC=clang-20 CXX=clang++-20 cmake -S "$ROOT" -B "$BUILD_DIR" -G Ninja -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
      -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON $([ "$SANITIZE" = 1 ] && echo -DXLION_SANITIZE=ON) $(CCACHE_ARGS)

# What this build is made of: one line per repo (commit and name), the root repo first
{
  echo "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown) xLION"
  for d in "$PRJ" "$DEPS"/*/ "$PLUGINS"/*/; do
    [ -L "${d%/}" ] && continue
    [ -d "$d/.git" ] && echo "$(git -C "$d" rev-parse HEAD 2>/dev/null) $(basename "$d")"
  done
} > "$BUILD_DIR/manifest.txt"
echo "manifest: $BUILD_DIR/manifest.txt ($(wc -l < "$BUILD_DIR/manifest.txt") repos)"

if [ "$DO_BUILD" = 1 ]; then
  echo "== build"
  cmake --build "$BUILD_DIR" --target xLION_Headless xLION xeditorcli xlion_compilers
fi

cat <<EOF

Done. Next:
  cmake --build "$BUILD_DIR" --target xLION_Headless xLION xeditorcli xlion_compilers    (skip if you used --build)
  "$BUILD_DIR/xLION" "$PRJ"             the editor (needs a display: X11, WSLg or Wayland with XWayland)
  "$BUILD_DIR/xLION_Headless" "$PRJ"    the editor without a window, driven with "$BUILD_DIR/xeditorcli"
EOF
