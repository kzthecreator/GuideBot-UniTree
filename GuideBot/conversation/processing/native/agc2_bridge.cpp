// Standalone AGC2: every other WebRTC audio enhancement is disabled.
#include "modules/audio_processing/include/audio_processing.h"
#include <cstdint>
#include <cmath>
#include <algorithm>

struct GuidebotAgc2 {
  webrtc::AudioProcessing* apm;
  float output_gain;
  int peak_limit;
  uint64_t limiter_boundary_samples = 0;
};

extern "C" {
void* guidebot_agc2_new_config(float speed, float noise, float margin, float ceiling_dbfs) {
  if (!(speed > 0 && speed <= 10 && noise >= -90 && noise <= 0 &&
        margin >= 0 && margin <= 50 && ceiling_dbfs <= -1 && ceiling_dbfs >= -12)) return nullptr;
  auto* apm = webrtc::AudioProcessingBuilder().Create();
  if (!apm) return nullptr;
  apm->AddRef();
  webrtc::AudioProcessing::Config config;
  config.echo_canceller.enabled = false;
  config.noise_suppression.enabled = false;
  config.high_pass_filter.enabled = false;
  config.gain_controller1.enabled = false;
  config.residual_echo_detector.enabled = false;
  config.gain_controller2.enabled = true;
  config.gain_controller2.fixed_digital.gain_db = 0;
  config.gain_controller2.adaptive_digital.enabled = true;
  config.gain_controller2.adaptive_digital.max_gain_change_db_per_second = speed;
  config.gain_controller2.adaptive_digital.max_output_noise_level_dbfs = noise;
  config.gain_controller2.adaptive_digital.initial_saturation_margin_db = margin;
  apm->ApplyConfig(config);
  if (apm->Initialize() != 0) { apm->Release(); return nullptr; }
  float gain = std::pow(10.f, ceiling_dbfs / 20.f);
  return new GuidebotAgc2{apm, gain, static_cast<int>(std::floor(32768.0 * gain))};
}
int guidebot_agc2_process(void* context, const int16_t* input, int16_t* output) {
  auto* state = static_cast<GuidebotAgc2*>(context);
  const webrtc::StreamConfig stream(16000, 1);
  float source[160], destination[160];
  for (int i=0; i<160; ++i) source[i] = input[i] / 32768.f;
  const float* src[] = {source};
  float* dst[] = {destination};
  int result = state->apm->ProcessStream(src, stream, stream, dst);
  if (result) return result;
  // Keep floating point through AGC/limiter, apply headroom BEFORE PCM16
  // quantization. Do not first clip to int16 and then turn the damage down.
  for (int i=0; i<160; ++i) {
    if (!std::isfinite(destination[i])) return -1;
    if (std::abs(destination[i]) >= 32767.f / 32768.f) ++state->limiter_boundary_samples;
    long value = std::lround(destination[i] * state->output_gain * 32768.f);
    output[i] = static_cast<int16_t>(std::max(-static_cast<long>(state->peak_limit),
                                           std::min(static_cast<long>(state->peak_limit), value)));
  }
  return 0;
}
uint64_t guidebot_agc2_boundary_samples(void* context) {
  return static_cast<GuidebotAgc2*>(context)->limiter_boundary_samples;
}
void guidebot_agc2_free(void* context) {
  if (context) {
    auto* state = static_cast<GuidebotAgc2*>(context);
    state->apm->Release();
    delete state;
  }
}
}
