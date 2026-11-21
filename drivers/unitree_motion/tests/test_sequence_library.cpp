#include "../sequence_library.hpp"
#include "../motion_interrupt.hpp"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>

#define require(value) do { if (!(value)) throw std::runtime_error( \
    "sequence library test failed at line " + std::to_string(__LINE__)); } while (false)

void write_frame(std::ofstream& output, double duration, double first_joint) {
    output << duration << " " << first_joint;
    for (size_t i = 1; i < standing_motion::kArmJoints; ++i) output << " 0";
    output << "\n";
}

int main() {
    char temporary[] = "/tmp/g1-sequence-test-XXXXXX";
    const char* created = mkdtemp(temporary);
    require(created != nullptr);
    const std::string root = created;
    require(mkdir((root + "/poses").c_str(), 0700) == 0);
    require(mkdir((root + "/poses/basic").c_str(), 0700) == 0);
    require(mkdir((root + "/motions").c_str(), 0700) == 0);
    require(mkdir((root + "/motions/reception").c_str(), 0700) == 0);
    {
        std::ofstream file(root + "/poses/basic/neutral.dat");
        file << "1\n14\n";
        write_frame(file, 0.3, 0);
    }
    {
        std::ofstream file(root + "/motions/reception/greet_open.dat");
        file << "3\n14\n";
        write_frame(file, 0.3, 0.02);
        write_frame(file, 0.5, 0.04);
        write_frame(file, 0.5, 0.02);
    }
    {
        std::ofstream file(root + "/catalog.json");
        file << R"({"schema_version":1,"actions":[{"name":"neutral","category":"basic","priority":"P0","type":"pose"},{"name":"greet_open","category":"reception","priority":"P0","type":"motion"}]})";
    }
    const motion_catalog::Library library{
        motion_catalog::Catalog::load(root + "/catalog.json", 2),
        root + "/motions", root + "/metadata", false, root + "/poses"};
    sequence_library::JointLimits limits;
    limits.minimum.fill(-1);
    limits.maximum.fill(1);
    const auto definition = sequence_library::parse(nlohmann::json::parse(R"({
      "sequence_name":"greet_guest",
      "steps":[
        {"type":"pose","name":"neutral","hold_ms":300},
        {"type":"motion","name":"greet_open","duration_ms":1200,"hold_ms":800,"transition_ms":400},
        {"type":"pose","name":"neutral","hold_ms":300,"transition_ms":500}
      ]})"));
    standing_motion::ArmPose actual{};
    const auto resolved = sequence_library::resolve(definition, library, limits, actual);
    require(resolved.waypoints.size() == 7);
    require(resolved.sequence_step_end == std::vector<size_t>({1, 5, 7}));
    require(std::abs(resolved.waypoints[1].arm[0] - 0.02) < 1e-9);
    require(std::abs(resolved.waypoints[4].requested_duration - 0.8) < 1e-9);
    const auto plan = standing_motion::make_plan(actual, 0, 0, resolved.waypoints);
    require(plan.total_duration >= 3.5);
    double elapsed = 0;
    for (const auto& segment : plan.segments) {
        elapsed += segment.duration;
        const double left = standing_motion::sample(plan, elapsed - 1e-5).arm[0];
        const double right = standing_motion::sample(plan, elapsed + 1e-5).arm[0];
        require(std::abs(left - right) < 1e-4);
    }
    double segment_start = 0;
    for (const auto& segment : plan.segments) {
        require(std::abs(standing_motion::sample(plan, segment_start + segment.duration * 0.25).arm[0] -
            (segment.from[0] + (segment.to[0] - segment.from[0]) * 0.25)) < 1e-9);
        segment_start += segment.duration;
    }
    require(std::abs(standing_motion::sample(plan, plan.total_duration).arm[0]) < 1e-9);

    auto weighted = sequence_library::parse(nlohmann::json::parse(R"({
      "sequence_name":"timing_preview",
      "steps":[{"type":"motion","name":"greet_open","duration_ms":4000}]
    })"));
    weighted.steps.front().preview_weights = {1.0, 3.0};
    const auto weighted_action = sequence_library::resolve(weighted, library, limits, actual);
    require(weighted_action.waypoints.size() == 3);
    require(std::abs(weighted_action.waypoints[1].requested_duration - 1.0) < 1e-9);
    require(std::abs(weighted_action.waypoints[2].requested_duration - 3.0) < 1e-9);

    auto profiled = weighted;
    auto& timed = profiled.steps.front();
    timed.duration_ms = 0;
    timed.preview_weights.clear();
    timed.total_ms = 6000;
    timed.timing_profile = motion_catalog::TimingProfile::parse(nlohmann::json::parse(R"({
      "phase_weights":{"transition":1,"core":4,"hold":1},
      "minimum_total_ms":12000,"frame_weights":[1,3]
    })"), 3);
    const auto timed_action = sequence_library::resolve(profiled, library, limits, actual, actual, true);
    require(timed_action.play_style_preview);
    require(timed_action.waypoints.size() == 4);
    const std::array<double, 4> expected{{2, 2, 6, 2}};
    for (size_t i = 0; i < expected.size(); ++i)
        require(std::abs(timed_action.waypoints[i].requested_duration - expected[i]) < 1e-9);
    auto nearby_measured = actual;
    nearby_measured[0] = 0.01;
    const auto tracked_timing = sequence_library::resolve(
        profiled, library, limits, actual, nearby_measured, true);
    require(tracked_timing.waypoints.size() == timed_action.waypoints.size());
    timed.total_ms = 24000;
    const auto longer = sequence_library::resolve(profiled, library, limits, actual, actual, true);
    for (size_t i = 0; i < expected.size(); ++i)
        require(std::abs(longer.waypoints[i].requested_duration - 2 * expected[i]) < 1e-9);
    timed.total_ms = 3000;
    timed.timing_profile.minimum_total_ms = 3000;
    auto far_start = actual;
    far_start[0] = -0.9;
    const auto three_second_action = sequence_library::resolve(
        profiled, library, limits, far_start, far_start, true);
    const auto three_second_plan = standing_motion::make_plan(
        far_start, 0, 0, three_second_action.waypoints);
    require(std::abs(three_second_plan.total_duration - 3.0) < 1e-9);
    timed.total_ms = 1;
    timed.timing_profile.minimum_total_ms = 1;
    const auto constrained = sequence_library::resolve(profiled, library, limits, actual, actual, true);
    const auto constrained_plan = standing_motion::make_plan(actual, 0, 0, constrained.waypoints);
    require(std::abs(constrained_plan.total_duration - 0.001) < 1e-12);
    for (size_t i = 0; i < expected.size(); ++i) {
        require(std::abs(constrained.waypoints[i].requested_duration /
                         constrained.waypoints[0].requested_duration - expected[i] / expected[0]) < 1e-9);
        require(std::abs(constrained_plan.segments[i].duration -
                         constrained.waypoints[i].requested_duration) < 1e-9);
    }
    require(std::abs(standing_motion::sample(constrained_plan,
        constrained_plan.segments.front().duration * 0.25).arm[0] - 0.005) < 1e-12);
    bool mixed_rejected = false;
    try { sequence_library::parse(nlohmann::json::parse(R"({
      "sequence_name":"mixed","steps":[{"type":"motion","name":"greet_open",
      "total_ms":6000,"duration_ms":1000}]})")); }
    catch (const std::runtime_error&) { mixed_rejected = true; }
    require(mixed_rejected);

    weighted.steps.front().duration_ms = 20;
    const auto linear_action = sequence_library::resolve(
        weighted, library, limits, actual, actual, true);
    require(linear_action.play_style_preview);
    require(linear_action.waypoints.front().interpolation ==
            standing_motion::Interpolation::PlayLinear);
    require(linear_action.waypoints[1].interpolation ==
            standing_motion::Interpolation::PlayLinear);
    require(linear_action.waypoints[2].interpolation ==
            standing_motion::Interpolation::PlayLinear);
    const auto linear_plan = standing_motion::make_plan(actual, 0, 0,
                                                       linear_action.waypoints);
    require(std::abs(linear_plan.segments[1].duration - 0.005) < 1e-9);
    require(std::abs(linear_plan.segments[2].duration - 0.015) < 1e-9);
    const auto formal_linear = sequence_library::resolve(weighted, library, limits, actual);
    const auto formal_plan = standing_motion::make_plan(actual, 0, 0, formal_linear.waypoints);
    require(std::abs(formal_plan.segments[1].duration - 0.005) < 1e-9);

    standing_motion::ArmPose measured{};
    measured[0] = 0.02;
    const auto direct = sequence_library::resolve(
        weighted, library, limits, actual, measured, true);
    require(direct.waypoints.size() == linear_action.waypoints.size());
    const auto reconciled = sequence_library::resolve(definition, library, limits, actual, measured);
    require(reconciled.waypoints.size() == resolved.waypoints.size() + 2);
    require(std::abs(reconciled.waypoints.front().arm[0] - measured[0]) < 1e-9);
    const auto reconciled_plan = standing_motion::make_plan(actual, 0, 0, reconciled.waypoints);
    require(std::abs(standing_motion::sample(reconciled_plan, 0).arm[0]) < 1e-9);
    measured[0] = 0.04;
    bool gap_rejected = false;
    try { sequence_library::resolve(definition, library, limits, actual, measured); }
    catch (const std::runtime_error&) { gap_rejected = true; }
    require(gap_rejected);

    motion_interrupt::Player player(actual);
    player.start(resolved);
    player.tick(plan.segments[0].duration + plan.segments[1].duration + 0.1);
    player.interrupt();
    player.tick(player.brake_duration());
    require(player.state() == motion_interrupt::State::Paused);
    require(player.checkpoint().step_name == "greet_open");
    player.resume();
    player.tick(30);
    require(player.state() == motion_interrupt::State::Idle);

    {
        std::ofstream file(root + "/motions/reception/greet_open.dat");
        file << "1\n14\n";
        write_frame(file, 0.3, 0.08);
    }
    auto target = sequence_library::parse(nlohmann::json::parse(R"({
      "sequence_name":"point_target",
      "steps":[{"type":"motion","name":"greet_open","duration_ms":1200,
                "transition_ms":400,"hold_ms":300}]
    })"));
    const auto target_asset = library.load_asset("greet_open", true);
    require(target_asset.nominal_duration_ms == 0);
    require(target_asset.keyframe_times_ms == std::vector<int>({0}));
    const auto target_action = sequence_library::resolve(target, library, limits, actual);
    require(target_action.waypoints.size() == 2);
    require(std::abs(target_action.waypoints[0].requested_duration - 1.2) < 1e-9);
    require(std::abs(target_action.waypoints[1].requested_duration - 0.3) < 1e-9);
    const auto target_plan = standing_motion::make_plan(actual, 0, 0, target_action.waypoints);
    require(std::abs(standing_motion::sample(target_plan, target_plan.total_duration).arm[0] - 0.08) < 1e-9);
    auto default_target = sequence_library::parse(nlohmann::json::parse(R"({
      "sequence_name":"point_default",
      "steps":[{"type":"motion","name":"greet_open","hold_ms":300}]
    })"));
    require(sequence_library::resolve(default_target, library, limits, actual).waypoints.size() == 2);
    const auto already_there = target_asset.waypoints.front().arm;
    default_target.steps.front().hold_ms = 0;
    require(sequence_library::resolve(default_target, library, limits, already_there)
            .waypoints.size() == 1);

    limits.maximum[0] = 0.03;
    bool rejected = false;
    try { sequence_library::resolve(definition, library, limits, actual); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected);

    const std::string source = __FILE__;
    const std::string project = source.substr(0, source.rfind("/tests/"));
    rejected = false;
    try { sequence_library::JointLimits::load(project + "/config/arm_joint_limits.json"); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
    return 0;
}
