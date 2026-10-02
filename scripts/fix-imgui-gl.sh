#!/usr/bin/env bash
# imgui-bundle's manylinux wheel vendors its own libglvnd (libGLX/libGLdispatch/libOpenGL).
# The system GL drivers (Mesa, NVIDIA) are linked to the system libglvnd, so two dispatch
# tables get loaded and GLFW finds no GLXFBConfigs. Point the vendored copies at the system
# libraries (only inside this project's venv). Re-run after reinstalling imgui-bundle.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
libs=$(ls -d "$root"/.venv/lib/python3*/site-packages/imgui_bundle.libs)
sys=/lib/$(uname -m)-linux-gnu
for pair in libGLX:libGLX.so.0 libGLdispatch:libGLdispatch.so.0 libOpenGL:libOpenGL.so.0; do
  v=${pair%%:*}; s=${pair#*:}
  for f in "$libs"/$v-*.so*; do
    [ -L "$f" ] && continue
    mv "$f" "$f.vendored" && ln -s "$sys/$s" "$f" && echo "linked $(basename "$f") -> $sys/$s"
  done
done
