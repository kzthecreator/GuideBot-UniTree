#pragma once
#include <cmath>
#include <stdexcept>

namespace motion_deadline {
// Same Linux CLOCK_MONOTONIC domain as Python time.monotonic(). Reserve
// 50ms for native dispatch/ticks; never speed up an already resolved plan.
inline void check(double end, double duration, double now) {
    if (end == 0.0) return;  // Explicit legacy / manually triggered commands.
    if (!std::isfinite(end) || !std::isfinite(duration) || !std::isfinite(now) ||
        end <= now || duration < 0 || now + duration + 0.05 > end)
        throw std::runtime_error("insufficient time before fixed action end deadline");
}
}
