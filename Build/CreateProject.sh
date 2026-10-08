#!/usr/bin/env bash
# Linux counterpart of CreateProject.bat: sets up everything needed to build xLION on Linux and configures it.
#
#   bash Build/CreateProject.sh                configure only (like CreateProject.bat), build dir Build/xLION.linux
#   bash Build/CreateProject.sh --build        ... and build xLION_Headless, xLION, xeditorcli and the asset compilers
#   bash Build/CreateProject.sh --no-packages  skip the apt step (packages already installed / not a Debian-family distro)
#   bash Build/CreateProject.sh --clean        delete the build dir first
#
# What it does, in order (every step is safe to run again):
#   1. installs the toolchain and libraries (apt; Ubuntu 24.04+ / Debian 13+, needs sudo)
#   2. builds the project tree CMake expects but, off Windows, will not fetch by itself (the job Install.bat does on
#      Windows): example.lionprj with its Cache/Plugins and Cache/dependencies. Our own repos come from main; third party
#      repos are pinned to the commits this port was tested with.
#   3. configures with CMake + Ninja + clang-20, offline (nothing is fetched during configure)
#
# Run it from a Linux filesystem (e.g. ~/src/xLION), not from /mnt/c or /mnt/d under WSL: those are many times slower.
# Environment: BUILD_DIR (default Build/xLION.linux), BUILD_TYPE (default Debug), GIT_BASE (default https://github.com/LIONant-depot).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/Build/xLION.linux}"
BUILD_TYPE="${BUILD_TYPE:-Debug}"
GIT_BASE="${GIT_BASE:-https://github.com/LIONant-depot}"
DO_BUILD=0; DO_PACKAGES=1; DO_CLEAN=0
for a in "$@"; do
  case "$a" in
    --build) DO_BUILD=1 ;; --no-packages) DO_PACKAGES=0 ;; --clean) DO_CLEAN=1 ;;
    -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option $a (see --help)"; exit 2 ;;
  esac
done
case "$ROOT" in /mnt/[a-z]/*) echo "warning: $ROOT is a Windows drive mounted in WSL - expect a very slow build; clone to ~/src instead" ;; esac

# ---------------------------------------------------------------------------------------------------------------------
# 1. Packages
#    clang-20: clang 18 crashes on the ECS code. libx11-dev/libvulkan-dev/glslc: the X11 window backend of xGPU and the
#    shader compiler. zenity + xdg-utils: file dialogs and "open" in the editor (runtime only). libXrandr/libXcursor: runtime.
# ---------------------------------------------------------------------------------------------------------------------
PACKAGES="build-essential git cmake ninja-build pkg-config python3 clang-20 lld-20 libomp-20-dev libvulkan-dev glslc libx11-dev libxrandr2 libxcursor1 zenity xdg-utils"
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
clone_at() {
  local url="$1" dir="$2" ref="$3"
  if [ -d "$dir/.git" ] && git -C "$dir" rev-parse -q --verify HEAD >/dev/null; then return 0; fi
  rm -rf "$dir"; mkdir -p "$(dirname "$dir")"
  echo "  cloning $(basename "$dir")"
  if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
    git init -q "$dir"; git -C "$dir" remote add origin "$url"
    git -C "$dir" fetch -q --depth 1 origin "$ref"; git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
  else
    git clone -q --depth 1 --branch "$ref" "$url" "$dir"
  fi
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
clone_at "$GIT_BASE/xECS.git"      "$DEPS/xECS"      Lesson09_Prefabs
# repo names that differ only by case / the same repo under two names
ln -sfn actions.imgui "$DEPS/Actions.imgui"
ln -sfn xlog          "$DEPS/xlog_editor"

# third party, pinned to the commits this port was verified with
while read -r name url ref; do clone_at "$url" "$DEPS/$name" "$ref"; done <<'EOF'
imgui              https://github.com/ocornut/imgui.git                      3bae66c735670619baf51391eba7f3d90a25d125
imgui-node-editor  https://github.com/thedmd/imgui-node-editor.git           021aa0ea4da13fed864bafb2a92d4c5205076866
ImGuizmo           https://github.com/CedricGuillemet/ImGuizmo.git           18cef5e031d8c6973d80284c67f60549fafd78c1
MikkTSpace         https://github.com/mmikk/MikkTSpace.git                   3e895b49d05ea07e4c2133156cfa94369e19e409
assimp             https://github.com/assimp/assimp.git                      a4eff9f89585c590d7b43daf5065f7bdf398bbc6
basis_universal    https://github.com/BinomialLLC/basis_universal.git        99f52d63aa6799cbdaecfe977111dc5ec3b31d47
box3d              https://github.com/erincatto/box3d.git                    5d83df83ab47172c2c745b44315e7538ead02397
compressonator     https://github.com/GPUOpen-Tools/compressonator.git       f4b53d79ec5abbb50924f58aebb7bf2793200b94
crunch             https://github.com/BinomialLLC/crunch.git                 36479bc697be19168daafbf15f47f3c60ccec004
freetype           https://gitlab.freedesktop.org/freetype/freetype.git      42608f77f20749dd6ddc9e0536788eaad70ea4b5
meshoptimizer      https://github.com/zeux/meshoptimizer.git                 717ca3489b457f781e5cd3e3a8bbc0229619415c
msdf-atlas-gen     https://github.com/Chlumsky/msdf-atlas-gen.git           6148900d59423059bafde2f51a0cb303184404bd
stb                https://github.com/nothings/stb.git                       2c980bb59875b0d32144a71867fbdebb2f77cd20
tinyddsloader      https://github.com/benikabocha/tinyddsloader.git          a2ce2fdcef9c6c3687d1def2c8bb07ba27f4d1ba
tinyexr            https://github.com/syoyo/tinyexr.git                      644148d0fd6b1b204a68a902dc963a70c749b417
zstd               https://github.com/facebook/zstd.git                      f8745da6ff1ad1e7bab384bd1f9d742439278e99
EOF

# plugins (what Install.bat clones, plus the header-only ones the root CMakeLists clones on Windows)
for p in xvirtual_folders xmaterial xtexture xmaterial_instance xgeom xgeom_static xskeleton xanim_package xfont xgeom_skin \
         xscene xlevel xscript_module xgame xPhysicsMaterial xShareComponent xprefab; do
  clone_at "$GIT_BASE/$p.plugin.git" "$PLUGINS/$p.plugin" main
  # every plugin except xvirtual_folders reaches the shared dependencies through its own "dependencies" link
  if [ "$p" != xvirtual_folders ] && [ ! -e "$PLUGINS/$p.plugin/dependencies" ]; then ln -s ../../dependencies "$PLUGINS/$p.plugin/dependencies"; fi
done

# ---------------------------------------------------------------------------------------------------------------------
# 3. Configure (like CreateProject.bat: cmake ../ -B xLION.<platform>)
#    xcmake_tools (Common.cmake) is placed in the build tree up front, then configure runs disconnected from the network.
# ---------------------------------------------------------------------------------------------------------------------
echo "== configure: $BUILD_DIR"
[ "$DO_CLEAN" = 1 ] && rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/_deps"
clone_at "$GIT_BASE/xcmake_tools.git" "$BUILD_DIR/_deps/xcmake_tools" main
CC=clang-20 CXX=clang++-20 cmake -S "$ROOT" -B "$BUILD_DIR" -G Ninja -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
      -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

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
