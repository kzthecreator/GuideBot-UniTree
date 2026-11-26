#!/usr/bin/env bash
# Build in an already extracted webrtc-audio-processing 1.3 source tree.
# Dependencies and binaries remain outside the business-code repository.
set -euo pipefail
apm_source="${1:?Pass the absolute webrtc-audio-processing-1.3 source directory}"
bridge_output="${2:-$HOME/.local/share/guidebot/deps/webrtc-apm/libguidebot_agc2.so}"
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
meson setup "$apm_source/build-local" "$apm_source" --buildtype=release --wrap-mode=forcefallback --reconfigure
meson compile -C "$apm_source/build-local" -j 2
mkdir -p "$(dirname -- "$bridge_output")"
c++ -shared -fPIC -O2 -std=c++17 -DWEBRTC_POSIX \
  -I"$apm_source/webrtc" -I"$apm_source/subprojects/abseil-cpp-20230125.1" \
  "$script_root/../../../GuideBot/conversation/processing/native/agc2_bridge.cpp" \
  -L"$apm_source/build-local/webrtc/modules/audio_processing" \
  -Wl,-rpath,"$apm_source/build-local/webrtc/modules/audio_processing" \
  -l:libwebrtc-audio-processing-1.so.3 -o "$bridge_output"
