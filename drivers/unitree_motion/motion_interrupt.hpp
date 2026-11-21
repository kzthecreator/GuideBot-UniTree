#pragma once

#include "action_sequence.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

namespace motion_interrupt {

enum class State { Idle, Running, Braking, Paused, Answering };

struct Checkpoint {
    std::string label;
    size_t phase = 0;
    size_t waypoint = 0;
    double segment_seconds = 0.0;
    size_t step_index = 0;
    std::string step_name;
};

class Player {
public:
    explicit Player(const standing_motion::ArmPose& start) : pose_(start) {}

    State state() const { return state_; }
    const standing_motion::ArmPose& pose() const { return pose_; }
    bool has_checkpoint() const { return has_checkpoint_; }
    Checkpoint checkpoint() const { return checkpoint_; }
    double brake_duration() const { return brake_duration_; }
    size_t active_step_index() const {
        size_t step = 0;
        const size_t waypoint = current_waypoint();
        while (step + 1 < action_.sequence_step_end.size() &&
               waypoint >= action_.sequence_step_end[step]) ++step;
        return step;
    }

    std::vector<standing_motion::Waypoint> preview_return_waypoints() const {
        if (!action_.play_style_preview)
            throw std::runtime_error("reverse preview requires play-style interpolation");
        return standing_motion::reverse_play_prefix(plan_, elapsed_);
    }

    void reset_idle_pose(const standing_motion::ArmPose& pose) {
        if (state_ != State::Idle || has_checkpoint())
            throw std::runtime_error("cannot reset pose during motion");
        pose_ = pose;
    }

    void start(action_sequence::Resolved action) {
        if (state_ != State::Idle) throw std::runtime_error("player is busy");
        action_ = std::move(action);
        plan_ = standing_motion::make_plan(pose_, 0, 0, action_.waypoints);
        elapsed_ = 0;
        state_ = State::Running;
    }

    void interrupt() {
        if (state_ != State::Running) throw std::runtime_error("no running action to interrupt");
        if (action_.play_style_preview)
            throw std::runtime_error("play-style preview supports cancellation, not pause/resume");
        if (!action_.sequence_step_interruptible.empty()) {
            size_t step = 0;
            const size_t waypoint = current_waypoint();
            while (step + 1 < action_.sequence_step_end.size() &&
                   waypoint >= action_.sequence_step_end[step]) ++step;
            if (!action_.sequence_step_interruptible[step])
                throw std::runtime_error("current sequence step does not allow pause");
        }
        braking_for_cancel_ = false;
        begin_braking();
    }

    void cancel() {
        if (action_.play_style_preview && state_ == State::Running) {
            state_ = State::Idle;
            has_checkpoint_ = false;
            brake_duration_ = 0.0;
            return;
        }
        if (state_ == State::Running || state_ == State::Answering) {
            braking_for_cancel_ = true;
            begin_braking();
        } else if (state_ == State::Braking) {
            braking_for_cancel_ = true;
        } else {
            state_ = State::Idle;
            has_checkpoint_ = false;
        }
    }

    void answer(action_sequence::Resolved action) {
        if (state_ != State::Paused) throw std::runtime_error("answer requires paused action");
        answer_brake_max_velocity_ = action.brake_max_velocity;
        answer_brake_max_acceleration_ = action.brake_max_acceleration;
        answer_plan_ = standing_motion::make_plan(pose_, 0, 0, action.waypoints);
        answer_elapsed_ = 0;
        state_ = State::Answering;
    }

    void resume() {
        if (state_ != State::Paused || !has_checkpoint_)
            throw std::runtime_error("no paused action to resume");
        std::vector<standing_motion::Waypoint> remaining;
        double offset = checkpoint_.segment_seconds;
        for (size_t i = checkpoint_.waypoint; i < plan_.segments.size(); ++i) {
            const auto& segment = plan_.segments[i];
            remaining.push_back({std::max(0.01, segment.duration - offset), segment.to,
                                 segment.interpolation});
            offset = 0;
        }
        if (remaining.empty()) {
            state_ = State::Idle;
            has_checkpoint_ = false;
            return;
        }
        action_.waypoints = remaining;
        for (auto& end : action_.phase_end)
            end = end > checkpoint_.waypoint ? end - checkpoint_.waypoint : 0;
        for (auto& end : action_.sequence_step_end)
            end = end > checkpoint_.waypoint ? end - checkpoint_.waypoint : 0;
        plan_ = standing_motion::make_plan(pose_, 0, 0, remaining);
        elapsed_ = 0;
        state_ = State::Running;
        has_checkpoint_ = false;
    }

    void tick(double seconds) {
        if (seconds < 0 || !std::isfinite(seconds)) throw std::runtime_error("invalid tick");
        if (state_ == State::Running) {
            elapsed_ = std::min(plan_.total_duration, elapsed_ + seconds);
            pose_ = standing_motion::sample(plan_, elapsed_).arm;
            if (elapsed_ >= plan_.total_duration) state_ = State::Idle;
        } else if (state_ == State::Answering) {
            answer_elapsed_ = std::min(answer_plan_.total_duration, answer_elapsed_ + seconds);
            pose_ = standing_motion::sample(answer_plan_, answer_elapsed_).arm;
            if (answer_elapsed_ >= answer_plan_.total_duration) state_ = State::Paused;
        } else if (state_ == State::Braking) {
            brake_elapsed_ = std::min(brake_duration_, brake_elapsed_ + seconds);
            const double u = brake_elapsed_ / brake_duration_;
            const double progress = brake_follow_original_ ? brake_start_ + brake_elapsed_ :
                brake_start_ + brake_duration_ * (u - u * u / 2);
            const auto& active = braking_answer_ ? answer_plan_ : plan_;
            const double stopped_at = std::min(brake_end_, progress);
            pose_ = standing_motion::sample(active, stopped_at).arm;
            if (brake_elapsed_ >= brake_duration_) {
                if (braking_for_cancel_) {
                    state_ = State::Idle;
                    has_checkpoint_ = false;
                } else {
                    set_checkpoint(stopped_at);
                    state_ = State::Paused;
                }
            }
        }
    }

private:
    size_t current_waypoint() const {
        double remaining = elapsed_;
        for (size_t i = 0; i < plan_.segments.size(); ++i) {
            if (remaining < plan_.segments[i].duration || i + 1 == plan_.segments.size())
                return i;
            remaining -= plan_.segments[i].duration;
        }
        return 0;
    }
    static bool brake_within_limits(const standing_motion::Plan& plan,
                                    double start, double end, double duration,
                                    double max_velocity, double max_acceleration) {
        for (int step = 0; step <= 128; ++step) {
            const double u = static_cast<double>(step) / 128;
            double remaining = std::min(end,
                start + duration * (u - u * u / 2));
            for (size_t index = 0; index < plan.segments.size(); ++index) {
                const auto& segment = plan.segments[index];
                if (remaining < segment.duration || index + 1 == plan.segments.size()) {
                    for (size_t joint = 0; joint < standing_motion::kArmJoints; ++joint) {
                        const double delta = segment.to[joint] - segment.from[joint];
                        const double velocity = delta / segment.duration;
                        const double warped_velocity = velocity * (1 - u);
                        const double warped_acceleration = -velocity / duration;
                        if (std::abs(warped_velocity) > max_velocity + 1e-6 ||
                            std::abs(warped_acceleration) > max_acceleration + 1e-6)
                            return false;
                    }
                    break;
                }
                remaining -= segment.duration;
            }
        }
        return true;
    }

    void begin_braking() {
        braking_answer_ = state_ == State::Answering;
        const auto& active = braking_answer_ ? answer_plan_ : plan_;
        brake_start_ = braking_answer_ ? answer_elapsed_ : elapsed_;
        brake_end_ = active.total_duration;
        double max_velocity = braking_answer_ ? answer_brake_max_velocity_ :
                                                action_.brake_max_velocity;
        double max_acceleration = braking_answer_ ? answer_brake_max_acceleration_ :
                                                    action_.brake_max_acceleration;
        if (!braking_answer_ && !action_.sequence_step_end.empty()) {
            size_t step = 0;
            const size_t waypoint = current_waypoint();
            while (step + 1 < action_.sequence_step_end.size() &&
                   waypoint >= action_.sequence_step_end[step]) ++step;
            max_velocity = action_.sequence_step_max_velocity[step];
            max_acceleration = action_.sequence_step_max_acceleration[step];
            brake_end_ = 0;
            for (size_t i = 0; i < action_.sequence_step_end[step]; ++i)
                brake_end_ += plan_.segments[i].duration;
        }
        brake_elapsed_ = 0;
        brake_duration_ = 0.5;
        brake_follow_original_ = false;
        while (brake_duration_ < 8.0 &&
               !brake_within_limits(active, brake_start_, brake_end_, brake_duration_,
                                    max_velocity, max_acceleration))
            brake_duration_ *= 1.5;
        if (!brake_within_limits(active, brake_start_, brake_end_, brake_duration_,
                                 max_velocity, max_acceleration)) {
            brake_duration_ = std::max(0.01, brake_end_ - brake_start_);
            brake_follow_original_ = true;
        }
        state_ = State::Braking;
    }

    void set_checkpoint(double stopped_at) {
        double remaining = stopped_at;
        for (size_t i = 0; i < plan_.segments.size(); ++i) {
            const auto& segment = plan_.segments[i];
            if (remaining < segment.duration || i + 1 == plan_.segments.size()) {
                checkpoint_.label = action_.request.label;
                checkpoint_.waypoint = i;
                checkpoint_.segment_seconds = std::min(remaining, segment.duration);
                checkpoint_.phase = 0;
                while (checkpoint_.phase < action_.phase_end.size() - 1 &&
                       i >= action_.phase_end[checkpoint_.phase]) ++checkpoint_.phase;
                checkpoint_.step_index = 0;
                checkpoint_.step_name.clear();
                if (!action_.sequence_step_end.empty()) {
                    while (checkpoint_.step_index + 1 < action_.sequence_step_end.size() &&
                           i >= action_.sequence_step_end[checkpoint_.step_index])
                        ++checkpoint_.step_index;
                    checkpoint_.step_name = action_.sequence_step_names[checkpoint_.step_index];
                }
                has_checkpoint_ = true;
                return;
            }
            remaining -= segment.duration;
        }
    }

    State state_ = State::Idle;
    standing_motion::ArmPose pose_{};
    action_sequence::Resolved action_{};
    standing_motion::Plan plan_{};
    standing_motion::Plan answer_plan_{};
    double elapsed_ = 0;
    double answer_elapsed_ = 0;
    double brake_start_ = 0;
    double brake_end_ = 0;
    double brake_elapsed_ = 0;
    double brake_duration_ = 0;
    bool braking_answer_ = false;
    bool brake_follow_original_ = false;
    double answer_brake_max_velocity_ = standing_motion::kMaxArmVelocity;
    double answer_brake_max_acceleration_ = standing_motion::kMaxArmAcceleration;
    bool braking_for_cancel_ = false;
    bool has_checkpoint_ = false;
    Checkpoint checkpoint_{};
};

}  // namespace motion_interrupt
