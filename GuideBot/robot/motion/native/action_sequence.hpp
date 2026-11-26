#pragma once

#include "standing_motion.hpp"
#include "motion_catalog.hpp"

#include <array>
#include <cmath>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace action_sequence {

constexpr std::array<const char*, 4> kSteps{{"a", "b", "c", "d"}};

struct Step {
    std::string name;
    double requested_seconds;
};

struct Request {
    std::string label;
    std::array<Step, 4> steps;
};

struct Resolved {
    Request request;
    std::vector<standing_motion::Waypoint> waypoints;
    std::array<size_t, 4> phase_end{};
    std::vector<size_t> sequence_step_end;
    std::vector<std::string> sequence_step_names;
    std::vector<bool> sequence_step_interruptible;
    std::vector<double> sequence_step_max_velocity;
    std::vector<double> sequence_step_max_acceleration;
    double brake_max_velocity = standing_motion::kMaxArmVelocity;
    double brake_max_acceleration = standing_motion::kMaxArmAcceleration;
    bool play_style_preview = false;
};

inline bool valid_name(const std::string& name) {
    if (name.empty() || name[0] < 'a' || name[0] > 'z') return false;
    for (const char c : name)
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'))
            return false;
    return true;
}

inline Request parse(const nlohmann::json& input) {
    if (!input.is_object() || !input.contains("动作") || !input.contains("时间"))
        throw std::runtime_error("request needs 动作 and 时间 objects");
    for (auto it = input.begin(); it != input.end(); ++it)
        if (it.key() != "动作" && it.key() != "时间" && it.key() != "标签")
            throw std::runtime_error("unknown request field: " + it.key());
    const auto& actions = input.at("动作");
    const auto& times = input.at("时间");
    if (!actions.is_object() || !times.is_object() || actions.size() != 4 || times.size() != 4)
        throw std::runtime_error("动作 and 时间 must each contain a, b, c, d");
    Request request;
    if (input.contains("标签")) {
        if (!input.at("标签").is_string())
            throw std::runtime_error("标签 must be a string");
        request.label = input.at("标签").get<std::string>();
    }
    for (size_t i = 0; i < kSteps.size(); ++i) {
        const std::string key = kSteps[i];
        if (!actions.contains(key) || !actions.at(key).is_string() ||
            !times.contains(key) || !times.at(key).is_number())
            throw std::runtime_error("step " + key + " needs an action name and numeric duration");
        Step& step = request.steps[i];
        step.name = actions.at(key).get<std::string>();
        step.requested_seconds = times.at(key).get<double>();
        if (!valid_name(step.name))
            throw std::runtime_error("invalid action name at step " + key);
        if (!std::isfinite(step.requested_seconds) ||
            step.requested_seconds <= 0.0 || step.requested_seconds > 30.0)
            throw std::runtime_error("duration for step " + key + " must be within (0, 30] seconds");
    }
    return request;
}

inline Request parse(const std::string& text) {
    try {
        return parse(nlohmann::json::parse(text));
    } catch (const nlohmann::json::exception& error) {
        throw std::runtime_error(std::string("invalid JSON request: ") + error.what());
    }
}

inline Resolved resolve(const Request& request, const motion_catalog::Library& library) {
    Resolved resolved;
    resolved.request = request;
    for (size_t phase = 0; phase < kSteps.size(); ++phase) {
        const Step& step = request.steps[phase];
        auto points = library.load(step.name);
        double recorded_seconds = 0.0;
        for (const auto& point : points) recorded_seconds += point.requested_duration;
        for (auto& point : points) {
            point.requested_duration *= step.requested_seconds / recorded_seconds;
            resolved.waypoints.push_back(point);
        }
        resolved.phase_end[phase] = resolved.waypoints.size();
    }
    return resolved;
}

inline std::array<double, 4> actual_phase_durations(
    const Resolved& action, const standing_motion::Plan& plan) {
    if (plan.segments.size() != action.waypoints.size())
        throw std::runtime_error("plan and action waypoint counts differ");
    std::array<double, 4> result{};
    size_t start = 0;
    for (size_t phase = 0; phase < result.size(); ++phase) {
        for (size_t i = start; i < action.phase_end[phase]; ++i)
            result[phase] += plan.segments[i].duration;
        start = action.phase_end[phase];
    }
    return result;
}

}  // namespace action_sequence
