#pragma once

#include "action_sequence.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace sequence_library {

struct JointLimits {
    standing_motion::ArmPose minimum{};
    standing_motion::ArmPose maximum{};
    bool verified = true;

    static JointLimits load(const std::string& path) {
        const auto data = motion_catalog::read_json(path);
        if (!data.is_object() || data.value("schema_version", 0) != 1 ||
            !data.value("verified", false) ||
            motion_catalog::required_string(data, "verified_by").empty() ||
            motion_catalog::required_string(data, "verified_at").empty() ||
            !data.contains("joint_names") || !data.at("joint_names").is_array() ||
            !data.contains("min_rad") || !data.at("min_rad").is_array() ||
            !data.contains("max_rad") || !data.at("max_rad").is_array() ||
            data.at("joint_names").size() != standing_motion::kArmJoints ||
            data.at("min_rad").size() != standing_motion::kArmJoints ||
            data.at("max_rad").size() != standing_motion::kArmJoints)
            throw std::runtime_error("arm joint limits are missing or not verified: " + path);
        JointLimits limits;
        for (size_t i = 0; i < standing_motion::kArmJoints; ++i) {
            if (data.at("joint_names").at(i) != motion_catalog::kJointNames[i] ||
                !data.at("min_rad").at(i).is_number() ||
                !data.at("max_rad").at(i).is_number())
                throw std::runtime_error("arm joint limits have wrong joint order or values");
            limits.minimum[i] = data.at("min_rad").at(i).get<double>();
            limits.maximum[i] = data.at("max_rad").at(i).get<double>();
            if (!std::isfinite(limits.minimum[i]) || !std::isfinite(limits.maximum[i]) ||
                limits.minimum[i] >= limits.maximum[i])
                throw std::runtime_error("invalid arm joint limit interval");
        }
        return limits;
    }

    static JointLimits for_preview(const std::string& path) {
        const auto data = motion_catalog::read_json(path);
        if (!data.is_object() || data.value("schema_version", 0) != 1 ||
            !data.contains("verified") || !data.at("verified").is_boolean())
            throw std::runtime_error("invalid arm joint limits profile: " + path);
        if (data.at("verified").get<bool>()) return load(path);
        JointLimits limits;
        limits.verified = false;
        return limits;
    }

    void check(const standing_motion::ArmPose& pose) const {
        for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
            if (!std::isfinite(pose[i]) ||
                (verified && (pose[i] < minimum[i] || pose[i] > maximum[i])))
                throw std::runtime_error(std::string("arm joint outside verified limits: ") +
                                         motion_catalog::kJointNames[i]);
    }
};

struct Step {
    std::string type;
    std::string name;
    int duration_ms = 0;
    int hold_ms = 0;
    int transition_ms = 500;
    int repeat = 1;
    std::vector<double> preview_weights;
    int total_ms = 0;
    motion_catalog::TimingProfile timing_profile;
};

struct Definition {
    std::string name;
    std::vector<Step> steps;
};

inline int integer_field(const nlohmann::json& object, const char* key,
                         int fallback, int minimum, int maximum) {
    if (!object.contains(key)) return fallback;
    if (!object.at(key).is_number_integer())
        throw std::runtime_error(std::string("sequence field must be integer: ") + key);
    const auto value = object.at(key).get<int64_t>();
    if (value < minimum || value > maximum)
        throw std::runtime_error(std::string("sequence field outside range: ") + key);
    return static_cast<int>(value);
}

inline Definition parse(const nlohmann::json& input) {
    if (!input.is_object() || !input.contains("sequence_name") ||
        !input.contains("steps") || !input.at("steps").is_array() ||
        input.at("steps").empty() || input.at("steps").size() > 64)
        throw std::runtime_error("sequence needs sequence_name and 1..64 steps");
    if (input.size() != 2)
        throw std::runtime_error("unknown sequence fields");
    Definition definition;
    definition.name = motion_catalog::required_string(input, "sequence_name");
    if (!motion_catalog::valid_name(definition.name))
        throw std::runtime_error("invalid sequence_name");
    for (const auto& item : input.at("steps")) {
        Step step;
        step.type = motion_catalog::required_string(item, "type");
        step.name = motion_catalog::required_string(item, "name");
        if (!motion_catalog::valid_name(step.name) ||
            (step.type != "pose" && step.type != "motion"))
            throw std::runtime_error("invalid sequence step type or name");
        for (auto it = item.begin(); it != item.end(); ++it)
            if (it.key() != "type" && it.key() != "name" && it.key() != "duration_ms" &&
                it.key() != "hold_ms" && it.key() != "transition_ms" && it.key() != "repeat" &&
                it.key() != "total_ms")
                throw std::runtime_error("unknown sequence step field: " + it.key());
        step.duration_ms = integer_field(item, "duration_ms", 0, 0, 120000);
        step.hold_ms = integer_field(item, "hold_ms", 0, 0, 60000);
        step.transition_ms = integer_field(item, "transition_ms", 500, 0, 30000);
        step.repeat = integer_field(item, "repeat", 1, 1, 10);
        step.total_ms = integer_field(item, "total_ms", 0, 1, 600000);
        if (step.total_ms && (item.contains("duration_ms") || item.contains("hold_ms") ||
                              item.contains("transition_ms") || step.repeat != 1))
            throw std::runtime_error("total_ms cannot be mixed with legacy phase times or repeat > 1");
        if (step.type == "pose" && (step.duration_ms != 0 || step.repeat != 1))
            throw std::runtime_error("pose step cannot set duration_ms or repeat");
        definition.steps.push_back(step);
    }
    return definition;
}

inline void append_timed_step(action_sequence::Resolved& result,
                             const motion_catalog::Asset& asset,
                             const JointLimits& limits,
                             const motion_catalog::TimingProfile& profile,
                             int requested_ms, standing_motion::ArmPose& previous) {
    if (!profile.enabled) throw std::runtime_error("total_ms requires a saved timing_profile");
    const double total = std::max(requested_ms, profile.minimum_total_ms) / 1000.0;
    const double unit = total / profile.weight_sum();
    auto append = [&](double duration, const standing_motion::ArmPose& target) {
        limits.check(target);
        result.waypoints.push_back({duration, target, standing_motion::Interpolation::PlayLinear});
        previous = target;
    };
    append(profile.transition * unit, asset.waypoints.front().arm);
    const double sum = std::accumulate(profile.frame_weights.begin(), profile.frame_weights.end(), 0.0);
    for (size_t i = 1; i < asset.waypoints.size(); ++i) {
        const double share = profile.frame_weights.empty() ?
            static_cast<double>(asset.keyframe_times_ms[i] - asset.keyframe_times_ms[i - 1]) /
                asset.nominal_duration_ms : profile.frame_weights[i - 1] / sum;
        append(profile.core * unit * share, asset.waypoints[i].arm);
    }
    if (profile.hold) append(profile.hold * unit, previous);
}

inline action_sequence::Resolved resolve(const Definition& definition,
                                          const motion_catalog::Library& library,
                                          const JointLimits& limits,
                                          const standing_motion::ArmPose& commanded,
                                          const standing_motion::ArmPose& actual,
                                          bool allow_preview = false) {
    limits.check(commanded);
    limits.check(actual);
    action_sequence::Resolved result;
    result.request.label = definition.name;
    result.play_style_preview = allow_preview;
    double tracking_gap = 0;
    for (size_t joint = 0; joint < standing_motion::kArmJoints; ++joint)
        tracking_gap = std::max(tracking_gap, std::abs(actual[joint] - commanded[joint]));
    if (tracking_gap > 0.03)
        throw std::runtime_error("arm has not settled at commanded pose");
    const bool timed_entry = !definition.steps.empty() && definition.steps.front().total_ms > 0;
    if (tracking_gap > 1e-6 && !result.play_style_preview && !timed_entry) {
        result.waypoints.push_back({0.5, actual});
    }
    standing_motion::ArmPose previous = (result.play_style_preview || timed_entry) ? commanded : actual;
    for (const Step& step : definition.steps) {
        const auto asset = library.load_asset(step.name, true, allow_preview);
        result.brake_max_velocity = std::min(result.brake_max_velocity, asset.max_velocity);
        result.brake_max_acceleration = std::min(result.brake_max_acceleration, asset.max_acceleration);
        if (step.type != asset.entry.type || (step.repeat > 1 && !asset.loopable))
            throw std::runtime_error("sequence step type or loop policy mismatch: " + step.name);
        if (step.total_ms) {
            if (step.repeat != 1 || !step.preview_weights.empty())
                throw std::runtime_error("total_ms uses profile timing and a single execution");
            if (step.timing_profile.enabled && !allow_preview)
                throw std::runtime_error("timing profile overrides are only allowed in preview");
            const auto& profile = step.timing_profile.enabled ? step.timing_profile : asset.timing_profile;
            append_timed_step(result, asset, limits, profile, step.total_ms, previous);
            result.sequence_step_end.push_back(result.waypoints.size());
            result.sequence_step_names.push_back(step.name);
            result.sequence_step_interruptible.push_back(asset.interruptible);
            result.sequence_step_max_velocity.push_back(asset.max_velocity);
            result.sequence_step_max_acceleration.push_back(asset.max_acceleration);
            continue;
        }
        const int core_ms = step.duration_ms ? step.duration_ms : asset.nominal_duration_ms;
        const bool target_motion = step.type == "motion" && asset.waypoints.size() == 1;
        if (step.type == "motion" && !target_motion && core_ms <= 0)
            throw std::runtime_error("motion has no nominal duration: " + step.name);
        if (!step.preview_weights.empty() &&
            step.preview_weights.size() != asset.waypoints.size() - 1)
            throw std::runtime_error("preview weight count does not match motion segments");
        const double preview_weight_total = std::accumulate(
            step.preview_weights.begin(), step.preview_weights.end(), 0.0);
        if (!step.preview_weights.empty() &&
            (!std::isfinite(preview_weight_total) || preview_weight_total <= 0))
            throw std::runtime_error("invalid preview weights");
        const size_t step_start = result.waypoints.size();
        for (int repeat = 0; repeat < step.repeat; ++repeat) {
            const auto& anchor = asset.waypoints.front().arm;
            limits.check(anchor);
            double displacement = 0;
            for (size_t joint = 0; joint < standing_motion::kArmJoints; ++joint)
                displacement = std::max(displacement, std::abs(anchor[joint] - previous[joint]));
            if (displacement > 1e-6) {
                const int transition_ms = target_motion && step.duration_ms > 0 ?
                    step.duration_ms : step.transition_ms;
                if (transition_ms == 0)
                    throw std::runtime_error("nonzero transition cannot take 0 ms: " + step.name);
                double duration = transition_ms / 1000.0;
                result.waypoints.push_back({duration, anchor});
            }
            previous = anchor;
            for (size_t i = 1; i < asset.waypoints.size(); ++i) {
                const auto& frame = asset.waypoints[i].arm;
                limits.check(frame);
                const int interval = asset.keyframe_times_ms[i] - asset.keyframe_times_ms[i - 1];
                double duration = static_cast<double>(core_ms) * interval /
                                  asset.nominal_duration_ms / 1000.0;
                if (!step.preview_weights.empty()) {
                    duration = core_ms * step.preview_weights[i - 1] /
                               preview_weight_total / 1000.0;
                }
                result.waypoints.push_back({duration, frame});
                previous = frame;
            }
        }
        if (step.hold_ms > 0) result.waypoints.push_back({step.hold_ms / 1000.0, previous});
        if (target_motion && result.waypoints.size() == step_start)
            result.waypoints.push_back({0.01, previous});
        result.sequence_step_end.push_back(result.waypoints.size());
        result.sequence_step_names.push_back(step.name);
        result.sequence_step_interruptible.push_back(asset.interruptible);
        result.sequence_step_max_velocity.push_back(asset.max_velocity);
        result.sequence_step_max_acceleration.push_back(asset.max_acceleration);
    }
    if (result.waypoints.empty())
        throw std::runtime_error("sequence has no movement or hold time");
    result.phase_end.fill(result.waypoints.size());
    return result;
}

inline action_sequence::Resolved resolve(const Definition& definition,
                                          const motion_catalog::Library& library,
                                          const JointLimits& limits,
                                          const standing_motion::ArmPose& actual) {
    return resolve(definition, library, limits, actual, actual);
}

}  // namespace sequence_library
