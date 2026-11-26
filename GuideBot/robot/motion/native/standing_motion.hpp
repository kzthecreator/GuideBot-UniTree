#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace standing_motion {

constexpr size_t kArmJoints = 14;
constexpr double kDefaultDuration = 0.3;
constexpr double kMaxArmVelocity = 0.4;   // Conservative demo limits, not hardware ratings.
constexpr double kMaxArmAcceleration = 0.8;
constexpr double kMaxYawVelocity = 0.15;
constexpr double kMaxYawAcceleration = 0.3;

using ArmPose = std::array<double, kArmJoints>;

enum class Interpolation { PlayLinear };

struct Waypoint {
    double requested_duration;
    ArmPose arm;
    Interpolation interpolation = Interpolation::PlayLinear;
};

struct Segment {
    double duration;
    ArmPose from;
    ArmPose to;
    Interpolation interpolation = Interpolation::PlayLinear;
};

struct Plan {
    std::vector<Segment> segments;
    double total_duration = 0.0;
    double yaw_from = 0.0;
    double yaw_to = 0.0;
};

struct Sample {
    ArmPose arm;
    double yaw;
};

inline std::vector<Waypoint> load_motion(const std::string& path) {
    std::ifstream file(path);
    if (!file) throw std::runtime_error("cannot open motion: " + path);
    int count = 0, joints = 0;
    if (!(file >> count >> joints) || count < 1 || count > 10000 || joints != 14)
        throw std::runtime_error("motion header must contain 1..10000 waypoints and 14 joints");
    std::string line;
    std::getline(file, line);
    std::vector<Waypoint> points;
    points.reserve(static_cast<size_t>(count));
    for (int row = 0; row < count; ++row) {
        if (!std::getline(file, line))
            throw std::runtime_error("motion has fewer rows than declared");
        std::istringstream stream(line);
        std::vector<double> values;
        double value;
        while (stream >> value) values.push_back(value);
        if (!stream.eof() || (values.size() != 14 && values.size() != 15))
            throw std::runtime_error("motion row " + std::to_string(row + 1) + " has invalid columns");
        const double duration = values.size() == 15 ? values[0] : kDefaultDuration;
        if (!std::isfinite(duration) || duration <= 0.0 || duration > 30.0)
            throw std::runtime_error("motion row " + std::to_string(row + 1) + " has invalid duration");
        Waypoint point{};
        point.requested_duration = duration;
        const size_t offset = values.size() == 15 ? 1 : 0;
        for (size_t i = 0; i < kArmJoints; ++i) {
            const double angle = values[i + offset];
            if (!std::isfinite(angle) || std::abs(angle) > 2.0 * 3.141592653589793)
                throw std::runtime_error("motion row " + std::to_string(row + 1) + " has invalid angle");
            point.arm[i] = angle;
        }
        points.push_back(point);
    }
    while (std::getline(file, line)) {
        if (line.find_first_not_of(" \t\r") != std::string::npos)
            throw std::runtime_error("motion has extra rows");
    }
    return points;
}

inline double minimum_duration(double displacement, double velocity, double) {
    return displacement / velocity;
}

inline Plan make_plan(const ArmPose& start, double yaw_start, double yaw_target,
                      const std::vector<Waypoint>& points) {
    if (points.empty()) throw std::runtime_error("motion must contain a waypoint");
    Plan plan;
    plan.yaw_from = yaw_start;
    plan.yaw_to = yaw_target;
    ArmPose from = start;
    for (const Waypoint& point : points) {
        double duration = point.requested_duration;
        plan.segments.push_back({duration, from, point.arm, point.interpolation});
        plan.total_duration += duration;
        from = point.arm;
    }
    return plan;
}

inline double linear_phase(double phase) {
    return std::max(0.0, std::min(1.0, phase));
}

inline Sample sample(const Plan& plan, double elapsed) {
    elapsed = std::max(0.0, std::min(plan.total_duration, elapsed));
    Sample result{};
    result.yaw = plan.yaw_from + (plan.yaw_to - plan.yaw_from) *
                 linear_phase(elapsed / plan.total_duration);
    double remaining = elapsed;
    for (const Segment& segment : plan.segments) {
        if (remaining <= segment.duration || &segment == &plan.segments.back()) {
            const double phase = remaining / segment.duration;
            const double s = linear_phase(phase);
            for (size_t i = 0; i < kArmJoints; ++i)
                result.arm[i] = segment.from[i] + (segment.to[i] - segment.from[i]) * s;
            return result;
        }
        remaining -= segment.duration;
    }
    throw std::runtime_error("empty trajectory");
}

// Reverse only the executed path, including a partially traversed segment.
inline std::vector<Waypoint> reverse_play_prefix(const Plan& plan, double elapsed) {
    std::vector<Waypoint> result;
    double remaining = std::max(0.0, std::min(plan.total_duration, elapsed));
    for (const auto& segment : plan.segments) {
        const double used = std::min(remaining, segment.duration);
        if (used <= 0.0) break;
        if (segment.from != segment.to)
            result.push_back({used, segment.from, Interpolation::PlayLinear});
        remaining -= used;
    }
    std::reverse(result.begin(), result.end());
    return result;
}

}  // namespace standing_motion
