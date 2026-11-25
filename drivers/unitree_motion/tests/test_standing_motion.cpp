#include "standing_motion.hpp"

#include <cmath>
#include <stdexcept>
#include <string>

void require(bool condition) {
    if (!condition) throw std::runtime_error("standing motion test failed");
}

int main() {
    using namespace standing_motion;
    ArmPose start{};
    ArmPose target{};
    target[3] = 1.8;
    const Plan plan = make_plan(start, 0.0, 0.2, {{0.3, target}});
    require(std::abs(plan.total_duration - 0.3) < 1e-9);
    require(std::abs(sample(plan, 0.0).arm[3]) < 1e-9);
    require(std::abs(sample(plan, 0.0).yaw) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration / 2).arm[3] - 0.9) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration / 2).yaw - 0.1) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration / 4).arm[3] - 0.45) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration / 4).yaw - 0.05) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration).arm[3] - 1.8) < 1e-9);
    require(std::abs(sample(plan, plan.total_duration).yaw - 0.2) < 1e-9);

    ArmPose second = target;
    second[3] = 0.0;
    const Plan chain = make_plan(start, 0.0, 0.1, {{0.3, target}, {0.3, second}});
    require(chain.total_duration > plan.total_duration);
    require(std::abs(sample(chain, chain.total_duration).arm[3]) < 1e-9);

    ArmPose short_target{};
    short_target[0] = 0.395;
    const Plan linear = make_plan(start, 0, 0, {{0.5, short_target,
        Interpolation::PlayLinear}});
    require(std::abs(linear.total_duration - 0.5) < 1e-9);
    require(std::abs(sample(linear, linear.total_duration / 2).arm[0] - 0.1975) < 1e-9);
    require(std::abs(sample(linear, linear.total_duration).arm[0] - 0.395) < 1e-9);

    ArmPose first{}, last{};
    first[0] = 1.8;
    last[0] = -0.5;
    const Plan original = make_plan(start, 0, 0, {
        {0.3, first, Interpolation::PlayLinear},
        {0.6, last, Interpolation::PlayLinear}, {0.5, last}});
    require(std::abs(original.total_duration - 1.4) < 1e-9);
    for (int tick = 0; tick <= 450; ++tick) {
        const double time = tick * 0.002;
        const double expected = time <= 0.3 ? first[0] * time / 0.3 :
            first[0] + (last[0] - first[0]) * (time - 0.3) / 0.6;
        require(std::abs(sample(original, time).arm[0] - expected) < 1e-9);
    }
    for (double stopped : {0.0, 0.1, 0.3, 0.5, 0.9, 1.4}) {
        const auto backwards = reverse_play_prefix(original, stopped);
        if (backwards.empty()) { require(stopped == 0.0); continue; }
        const auto current = sample(original, stopped).arm;
        const Plan reverse = make_plan(current, 0, 0, backwards);
        require(std::abs(reverse.total_duration - std::min(stopped, 0.9)) < 1e-9);
        for (double time = 0; time <= reverse.total_duration; time += 0.002) {
            const auto expected = sample(original, std::min(stopped, 0.9) - time).arm;
            require(std::abs(sample(reverse, time).arm[0] - expected[0]) < 1e-8);
        }
        require(std::abs(sample(reverse, reverse.total_duration).arm[0]) < 1e-9);
    }

    const std::string directory = std::string(__FILE__).substr(0, std::string(__FILE__).find_last_of('/'));
    const auto legacy = load_motion(directory + "/fixtures/standing_legacy.dat");
    require(legacy.size() == 1 && legacy[0].requested_duration == kDefaultDuration);
    const auto timed = load_motion(directory + "/fixtures/standing_timed.dat");
    require(timed.size() == 1 && timed[0].requested_duration == 1.5);
    try {
        load_motion(directory + "/fixtures/standing_invalid.dat");
        throw std::runtime_error("invalid motion was accepted");
    } catch (const std::runtime_error& error) {
        require(std::string(error.what()) != "invalid motion was accepted");
    }
    return 0;
}
