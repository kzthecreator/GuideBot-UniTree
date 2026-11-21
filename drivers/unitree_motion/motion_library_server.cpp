#include "motion_interrupt.hpp"
#include "sequence_library.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <mutex>
#include <set>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <poll.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <unitree/idl/hg/LowCmd_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_publisher.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

using unitree_hg::msg::dds_::LowCmd_;
using unitree_hg::msg::dds_::LowState_;
using namespace unitree::robot;
using standing_motion::ArmPose;

namespace {

constexpr int kArmIndex[14] = {15, 16, 17, 18, 19, 20, 21,
                               22, 23, 24, 25, 26, 27, 28};
constexpr int kYawIndex = 12;
constexpr int kRollIndex = 13;
constexpr int kPitchIndex = 14;
constexpr int kWeightIndex = 29;
constexpr uint16_t kKeyR1 = 1u << 0;
constexpr uint16_t kKeyR2 = 1u << 4;
constexpr double kPi = 3.141592653589793;
constexpr double kMaxYawDegrees = 15.0;
constexpr double kMaxAbsoluteYaw = 0.40;
constexpr auto kTick = std::chrono::milliseconds(2);
constexpr auto kOwnershipTick = std::chrono::milliseconds(10);
constexpr auto kPlayTick = std::chrono::milliseconds(2);
constexpr char kSocketName[] = "g1_arm_motion_library";

LowState_ g_state{};
std::mutex g_state_mutex;
std::chrono::steady_clock::time_point g_last_state{};
bool g_state_received = false;
volatile std::sig_atomic_t g_interrupted = 0;

struct Snapshot {
    ArmPose arm{};
    double yaw = 0.0;
    double roll = 0.0;
    double pitch = 0.0;
    double max_leg_speed = std::numeric_limits<double>::infinity();
    double max_arm_speed = std::numeric_limits<double>::infinity();
    double max_gyro_speed = std::numeric_limits<double>::infinity();
    uint16_t keys = 0;
    bool received = false;
    std::chrono::steady_clock::time_point time{};
};

void on_state(const void* raw) {
    std::lock_guard<std::mutex> lock(g_state_mutex);
    g_state = *static_cast<const LowState_*>(raw);
    g_last_state = std::chrono::steady_clock::now();
    g_state_received = true;
}

void on_signal(int) { g_interrupted = 1; }

class ControllerLock {
public:
    ControllerLock() {
        fd_ = open("/tmp/g1_arm_motion_library.lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
        if (fd_ < 0) throw std::runtime_error("cannot open motion controller lock");
        if (flock(fd_, LOCK_EX | LOCK_NB) != 0) {
            close(fd_);
            fd_ = -1;
            throw std::runtime_error("another motion library controller is running");
        }
    }

    ~ControllerLock() { if (fd_ >= 0) close(fd_); }

    ControllerLock(const ControllerLock&) = delete;
    ControllerLock& operator=(const ControllerLock&) = delete;

private:
    int fd_ = -1;
};

Snapshot snapshot() {
    std::lock_guard<std::mutex> lock(g_state_mutex);
    Snapshot state;
    state.received = g_state_received;
    if (!state.received) return state;
    for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
        state.arm[i] = g_state.motor_state()[kArmIndex[i]].q();
    state.max_leg_speed = 0.0;
    state.max_arm_speed = 0.0;
    state.max_gyro_speed = 0.0;
    for (int joint = 0; joint < 12; ++joint) {
        const double speed = g_state.motor_state()[joint].dq();
        if (!std::isfinite(speed)) state.max_leg_speed = std::numeric_limits<double>::infinity();
        else state.max_leg_speed = std::max(state.max_leg_speed, std::abs(speed));
    }
    for (int joint : kArmIndex) {
        const double speed = g_state.motor_state()[joint].dq();
        if (!std::isfinite(speed)) state.max_arm_speed = std::numeric_limits<double>::infinity();
        else state.max_arm_speed = std::max(state.max_arm_speed, std::abs(speed));
    }
    for (const auto speed : g_state.imu_state().gyroscope()) {
        if (!std::isfinite(speed)) state.max_gyro_speed = std::numeric_limits<double>::infinity();
        else state.max_gyro_speed = std::max(state.max_gyro_speed,
                                             static_cast<double>(std::abs(speed)));
    }
    state.yaw = g_state.motor_state()[kYawIndex].q();
    state.roll = g_state.motor_state()[kRollIndex].q();
    state.pitch = g_state.motor_state()[kPitchIndex].q();
    std::memcpy(&state.keys, &g_state.wireless_remote()[2], sizeof(state.keys));
    state.time = g_last_state;
    return state;
}

bool ready(const Snapshot& state) {
    if (g_interrupted || !state.received ||
        std::chrono::steady_clock::now() - state.time > std::chrono::milliseconds(300) ||
        ((state.keys & kKeyR1) && (state.keys & kKeyR2)) ||
        !std::isfinite(state.yaw) || !std::isfinite(state.roll) ||
        !std::isfinite(state.pitch)) return false;
    for (double angle : state.arm)
        if (!std::isfinite(angle)) return false;
    return true;
}

bool stationary_base(const Snapshot& state) {
    return ready(state) && state.max_leg_speed < 0.12 &&
           state.max_gyro_speed < 0.15;
}

bool standing_still(const Snapshot& state) {
    return stationary_base(state) && state.max_arm_speed < 0.12;
}

std::string pick_iface() {
    if (const char* value = std::getenv("UNITREE_IFACE"))
        if (*value) return value;
    struct ifaddrs* interfaces = nullptr;
    if (getifaddrs(&interfaces) == 0) {
        for (auto* item = interfaces; item; item = item->ifa_next) {
            if (!item->ifa_addr || item->ifa_addr->sa_family != AF_INET) continue;
            const auto* address = reinterpret_cast<const sockaddr_in*>(item->ifa_addr);
            if ((ntohl(address->sin_addr.s_addr) & 0xffffff00u) == 0xc0a87b00u) {
                const std::string result = item->ifa_name;
                freeifaddrs(interfaces);
                return result;
            }
        }
        freeifaddrs(interfaces);
    }
    throw std::runtime_error("cannot find 192.168.123.x interface; set UNITREE_IFACE");
}

void publish(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
             const Snapshot& initial, const ArmPose& arm, double yaw, double weight) {
    for (size_t i = 0; i < standing_motion::kArmJoints; ++i) {
        auto& motor = cmd.motor_cmd()[kArmIndex[i]];
        motor.q(static_cast<float>(arm[i]));
        motor.dq(0.0f); motor.kp(60.0f); motor.kd(1.5f); motor.tau(0.0f);
    }
    auto& waist = cmd.motor_cmd()[kYawIndex];
    waist.q(static_cast<float>(yaw));
    waist.dq(0.0f); waist.kp(60.0f); waist.kd(1.5f); waist.tau(0.0f);
    for (const int joint : {kRollIndex, kPitchIndex}) {
        auto& motor = cmd.motor_cmd()[joint];
        motor.q(static_cast<float>(joint == kRollIndex ? initial.roll : initial.pitch));
        motor.dq(0.0f); motor.kp(0.0f); motor.kd(0.0f); motor.tau(0.0f);
    }
    cmd.motor_cmd()[kWeightIndex].q(static_cast<float>(weight));
    publisher.Write(cmd);
}

bool ramp_up(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
             const Snapshot& initial, double& weight, bool require_still = false) {
    auto wake = std::chrono::steady_clock::now();
    for (int i = 0; i < 200; ++i) {
        const Snapshot state = snapshot();
        // Arms can move as ownership gains weight. Require base stability here;
        // full-body stillness is checked before ramp-up, arm position afterward.
        if (!ready(state) || (require_still && !stationary_base(state))) {
            std::cerr << "[ACQUIRE-GUARD] step=" << i << "/200"
                      << " received=" << state.received
                      << " age_ms=" << std::chrono::duration<double, std::milli>(
                             std::chrono::steady_clock::now() - state.time).count()
                      << " interrupted=" << static_cast<bool>(g_interrupted)
                      << " remote_exit=" << static_cast<bool>(
                             (state.keys & kKeyR1) && (state.keys & kKeyR2))
                      << " ready=" << ready(state)
                      << " require_still=" << require_still
                      << " leg_speed=" << state.max_leg_speed << " (limit 0.12 rad/s)"
                      << " arm_speed=" << state.max_arm_speed << " (informational during ramp)"
                      << " gyro_speed=" << state.max_gyro_speed << " (limit 0.15 rad/s)\n";
            publish(publisher, cmd, initial, initial.arm, initial.yaw, 0.0);
            weight = 0.0;
            return false;
        }
        weight = static_cast<double>(i + 1) / 200;
        publish(publisher, cmd, initial, initial.arm, initial.yaw, weight);
        wake += kOwnershipTick;
        std::this_thread::sleep_until(wake);
    }
    return true;
}

void ramp_down(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
               const Snapshot& initial, const ArmPose& commanded_arm,
               double commanded_yaw, double starting_weight) {
    const Snapshot measured = snapshot();
    const bool fresh = measured.received &&
        std::chrono::steady_clock::now() - measured.time < std::chrono::milliseconds(300);
    const ArmPose arm = fresh ? measured.arm : commanded_arm;
    const double yaw = fresh ? measured.yaw : commanded_yaw;
    auto wake = std::chrono::steady_clock::now();
    for (int i = 0; i < 200; ++i) {
        publish(publisher, cmd, initial, arm, yaw,
                starting_weight * (1.0 - static_cast<double>(i + 1) / 200));
        wake += kOwnershipTick;
        std::this_thread::sleep_until(wake);
    }
    publish(publisher, cmd, initial, arm, yaw, 0.0);
}

enum class Kind { Action, Sequence, Preview, Answer, Waist, Interrupt, Resume, Stop, Release, Acquire, Quit };

double monotonic_seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

struct Command {
    std::string execution_id;
    double start_before = 0;
    int expected_ms = 0;
    bool combo_preview = false;
    Kind kind;
    action_sequence::Resolved action;
    sequence_library::Definition sequence;
    sequence_library::JointLimits limits;
    double yaw_degrees = 0.0;
};

std::string preview_label(const Command& command) {
    return command.combo_preview ? command.sequence.name : command.sequence.steps.front().name;
}

class CommandQueue {
public:
    bool empty() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return commands_.empty();
    }

    bool push(Command command) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (command.kind == Kind::Stop || command.kind == Kind::Release ||
            command.kind == Kind::Quit) commands_.clear();
        if (commands_.size() >= 8) return false;
        if (command.kind == Kind::Interrupt || command.kind == Kind::Stop ||
            command.kind == Kind::Release || command.kind == Kind::Quit)
            commands_.push_front(std::move(command));
        else
            commands_.push_back(std::move(command));
        return true;
    }

    std::vector<Command> take_all() {
        std::lock_guard<std::mutex> lock(mutex_);
        std::vector<Command> result;
        while (!commands_.empty()) {
            result.push_back(std::move(commands_.front()));
            commands_.pop_front();
        }
        return result;
    }

private:
    mutable std::mutex mutex_;
    std::deque<Command> commands_;
};

class StatusStore {
public:
    void set_skip_limits(bool value) {
        std::lock_guard<std::mutex> lock(mutex_);
        skip_limits_ = value;
    }

    void set_offline() {
        std::lock_guard<std::mutex> lock(mutex_);
        offline_ = true;
    }

    bool seen_execution(const std::string& id) const {
        std::lock_guard<std::mutex> lock(mutex_);
        return execution_ids_.count(id) != 0;
    }

    bool reserve_history_space() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (executions_.size() < 64) return true;
        for (auto it = executions_.begin(); it != executions_.end(); ++it) {
            const std::string state = it.value().value("state", std::string());
            if (state == "completed" || state == "cancelled" || state == "rejected") {
                executions_.erase(it);
                return true;
            }
        }
        return false;
    }

    void execution(const std::string& id, const std::string& state,
                   const std::string& error = "", double planned_seconds = 0) {
        std::lock_guard<std::mutex> lock(mutex_);
        execution_ids_.insert(id);
        auto& item = executions_[id];
        item["job_id"] = id;
        const auto old = item.value("state", std::string());
        std::string effective = state;
        if (state == "running" && (old == "cancelled" || old == "cancelling")) effective = "cancelling";
        if (state == "completed" && (old == "cancelled" || old == "cancelling")) effective = "cancelled";
        item["state"] = effective;
        item[effective + "_at"] = monotonic_seconds();
        if (!error.empty()) item["error"] = error;
        if (planned_seconds > 0) item["planned_seconds"] = planned_seconds;
    }

    void cancel_executions() {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& item : executions_.items()) {
            auto& value = item.value();
            const std::string state = value.value("state", std::string());
            if (state == "accepted" || state == "running") {
                value["state"] = state == "accepted" ? "cancelled" : "cancelling";
                value[value["state"].get<std::string>() + "_at"] = monotonic_seconds();
            }
        }
    }

    void set_preview(const std::string& name, const std::string& state,
                     const std::string& error = "", bool limits_verified = true,
                     double planned_seconds = 0.0,
                     double planned_core_seconds = 0.0) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (preview_.is_object() && preview_.value("name", std::string()) == name)
            limits_verified = preview_.value("joint_limits_verified", limits_verified);
        if (planned_seconds == 0.0 && preview_.is_object())
            planned_seconds = preview_.value("planned_seconds", 0.0);
        if (planned_core_seconds == 0.0 && preview_.is_object())
            planned_core_seconds = preview_.value("planned_core_seconds", 0.0);
        preview_ = {{"name", name}, {"state", state}, {"error", error},
                    {"joint_limits_verified", limits_verified},
                    {"planned_seconds", planned_seconds},
                    {"planned_core_seconds", planned_core_seconds}};
        status_["preview"] = preview_;
    }

    void set_ownership(const std::string& ownership) {
        std::lock_guard<std::mutex> lock(mutex_);
        ownership_ = ownership;
        status_["ownership"] = ownership_;
    }

    std::string ownership() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return ownership_;
    }

    nlohmann::json get() const {
        std::lock_guard<std::mutex> lock(mutex_);
        auto value = status_;
        value["execution_v1"] = true;
        value["joint_limits_skipped"] = skip_limits_;
        value["offline_execution_v1"] = offline_;
        value["executions"] = executions_;
        return value;
    }

    void update(const motion_interrupt::Player& player) {
        static const char* names[] = {"idle", "running", "braking", "paused", "answering"};
        nlohmann::json checkpoint = nullptr;
        if (player.has_checkpoint()) {
            const auto point = player.checkpoint();
            checkpoint = {{"label", point.label},
                          {"phase", action_sequence::kSteps[point.phase]},
                          {"waypoint", point.waypoint},
                          {"segment_seconds", point.segment_seconds},
                          {"step_index", point.step_index},
                          {"step_name", point.step_name}};
        }
        std::lock_guard<std::mutex> lock(mutex_);
        status_ = {{"state", names[static_cast<int>(player.state())]},
                   {"checkpoint", checkpoint}, {"ownership", ownership_},
                   {"active_step_index", player.state() == motion_interrupt::State::Running ?
                        nlohmann::json(player.active_step_index()) : nlohmann::json(nullptr)},
                   {"preview", preview_}};
    }

private:
    mutable std::mutex mutex_;
    bool skip_limits_ = false;
    bool offline_ = false;
    std::set<std::string> execution_ids_;
    nlohmann::json executions_ = nlohmann::json::object();
    std::string ownership_ = "owned";
    nlohmann::json preview_ = nullptr;
    nlohmann::json status_ = {{"state", "idle"}, {"checkpoint", nullptr},
                              {"ownership", "owned"}, {"preview", nullptr}};
};

sequence_library::Definition preview_definition(const motion_catalog::Asset& asset) {
    sequence_library::Definition definition;
    definition.name = "preview_" + asset.entry.name;
    sequence_library::Step step;
    step.type = asset.entry.type;
    step.name = asset.entry.name;
    step.transition_ms = 300;
    step.hold_ms = 500;
    if (asset.timing_profile.enabled) {
        step.total_ms = asset.timing_profile.minimum_total_ms;
    }
    if (step.type == "motion") {
        if (asset.nominal_duration_ms > 60000)
            throw std::runtime_error("preview motion exceeds 60 s nominal duration");
        step.duration_ms = asset.nominal_duration_ms;
    }
    definition.steps.push_back(step);
    return definition;
}

double preview_core_seconds(const standing_motion::Plan& plan,
                            const sequence_library::Step& step,
                            const motion_catalog::Asset& asset) {
    const size_t core_count = asset.waypoints.size() - 1;
    const auto& profile = step.timing_profile.enabled ? step.timing_profile : asset.timing_profile;
    const size_t hold_count = (step.total_ms ? profile.hold : step.hold_ms) > 0 ? 1 : 0;
    if (plan.segments.size() < core_count + hold_count)
        throw std::runtime_error("preview plan is missing core segments");
    const size_t end = plan.segments.size() - hold_count;
    double seconds = 0.0;
    for (size_t index = end - core_count; index < end; ++index)
        seconds += plan.segments[index].duration;
    return seconds;
}

double preview_core_seconds(const standing_motion::Plan& plan, const Command& command,
                            const motion_catalog::Library& library) {
    if (command.combo_preview) return 0.0;
    const auto& step = command.sequence.steps.front();
    return preview_core_seconds(plan, step, library.load_asset(step.name, true, true));
}

Command parse_command(const nlohmann::json& input, const motion_catalog::Library& library,
                      const std::string& limits_path, double initial_yaw, bool skip_limits = false) {
    if (!input.is_object()) throw std::runtime_error("command must be a JSON object");
    Command command{};
    if (input.contains("组合试播")) {
        if (input.size() != 1) throw std::runtime_error("combo preview has extra fields");
        command.kind = Kind::Preview;
        command.combo_preview = true;
        command.sequence = sequence_library::parse(input.at("组合试播"));
        command.limits = sequence_library::JointLimits::for_preview(limits_path);
        for (const auto& step : command.sequence.steps) {
            const auto asset = library.load_asset(step.name, true, true);
            if (!step.total_ms || step.repeat != 1 || asset.entry.type != step.type ||
                !asset.timing_profile.enabled)
                throw std::runtime_error("combo preview requires total_ms and a saved timing profile: " + step.name);
        }
        return command;
    }
    if (input.contains("试播")) {
        if (input.size() != 1)
            throw std::runtime_error("preview has extra fields");
        command.kind = Kind::Preview;
        const auto& options = input.at("试播");
        const bool detailed = options.is_object();
        if (!detailed && !options.is_string())
            throw std::runtime_error("preview requires an action name or options");
        if (detailed) {
            for (auto it = options.begin(); it != options.end(); ++it)
                if (it.key() != "name" && it.key() != "duration_ms" &&
                    it.key() != "weights" && it.key() != "hold_ms" &&
                    it.key() != "transition_ms" && it.key() != "interpolation" &&
                    it.key() != "total_ms" && it.key() != "timing_profile")
                    throw std::runtime_error("unknown preview option: " + it.key());
        }
        const auto name = detailed ? motion_catalog::required_string(options, "name") :
                                     options.get<std::string>();
        const auto asset = library.load_asset(name, true, true);
        command.limits = sequence_library::JointLimits::for_preview(limits_path);
        command.sequence = preview_definition(asset);
        if (detailed) {
            auto& step = command.sequence.steps.front();
            const bool legacy = options.contains("duration_ms") || options.contains("hold_ms") ||
                options.contains("transition_ms") || options.contains("weights") ||
                options.contains("interpolation");
            if (legacy) step.total_ms = 0;
            if (options.contains("total_ms") && legacy)
                throw std::runtime_error("total_ms cannot be mixed with legacy preview options");
            step.total_ms = sequence_library::integer_field(
                options, "total_ms", step.total_ms, 1, 600000);
            if (options.contains("timing_profile")) {
                if (!step.total_ms)
                    throw std::runtime_error("timing_profile override requires total_ms");
                step.timing_profile = motion_catalog::TimingProfile::parse(
                    options.at("timing_profile"), asset.waypoints.size());
            }
            step.duration_ms = sequence_library::integer_field(
                options, "duration_ms", step.duration_ms, 1, 120000);
            step.hold_ms = sequence_library::integer_field(
                options, "hold_ms", step.hold_ms, 0, 60000);
            step.transition_ms = sequence_library::integer_field(
                options, "transition_ms", step.transition_ms, 1, 30000);
            if (options.contains("interpolation")) {
                if (!options.at("interpolation").is_string())
                    throw std::runtime_error("only linear interpolation is supported");
                const std::string interpolation = options.at("interpolation").get<std::string>();
                if (interpolation != "linear")
                    throw std::runtime_error("only linear interpolation is supported");
            }
            if (options.contains("weights")) {
                const auto& weights = options.at("weights");
                if (step.type != "motion" || !weights.is_array() ||
                    weights.size() != asset.waypoints.size() - 1)
                    throw std::runtime_error("preview weights must match motion segments");
                for (const auto& item : weights) {
                    if (!item.is_number())
                        throw std::runtime_error("preview weight must be a number");
                    const double weight = item.get<double>();
                    if (!std::isfinite(weight) || weight < 0.05 || weight > 20.0)
                        throw std::runtime_error("preview weight outside [0.05, 20]");
                    step.preview_weights.push_back(weight);
                }
            }
        }
        return command;
    }
    if (input.contains("序列")) {
        if (input.size() != 1) throw std::runtime_error("sequence command has extra fields");
        command.kind = Kind::Sequence;
        command.sequence = sequence_library::parse(input.at("序列"));
        command.limits = skip_limits ? sequence_library::JointLimits::unchecked() :
            sequence_library::JointLimits::load(limits_path);
        for (const auto& step : command.sequence.steps) {
            const auto asset = library.load_asset(step.name, true);
            if (asset.entry.type != step.type || (step.repeat > 1 && !asset.loopable))
                throw std::runtime_error("sequence step type or loop policy mismatch: " + step.name);
        }
        return command;
    }
    if (input.contains("回答动作")) {
        if (input.size() != 1) throw std::runtime_error("answer command has extra fields");
        command.kind = Kind::Answer;
        command.action = action_sequence::resolve(action_sequence::parse(input.at("回答动作")), library);
        return command;
    }
    if (input.contains("动作") || input.contains("时间")) {
        command.kind = Kind::Action;
        command.action = action_sequence::resolve(action_sequence::parse(input), library);
        return command;
    }
    if (input.size() != 1) throw std::runtime_error("unknown command fields");
    if (input.contains("腰部角度")) {
        const auto& angle = input.at("腰部角度");
        if (!angle.is_number()) throw std::runtime_error("腰部角度 must be numeric degrees");
        command.yaw_degrees = angle.get<double>();
        if (!std::isfinite(command.yaw_degrees) ||
            std::abs(command.yaw_degrees) > kMaxYawDegrees ||
            std::abs(initial_yaw + command.yaw_degrees * kPi / 180.0) > kMaxAbsoluteYaw)
            throw std::runtime_error("waist yaw exceeds demo limits");
        command.kind = Kind::Waist;
    } else if (input.value("停止", false)) {
        command.kind = Kind::Stop;
    } else if (input.value("中断", false)) {
        command.kind = Kind::Interrupt;
    } else if (input.value("恢复", false)) {
        command.kind = Kind::Resume;
    } else if (input.value("释放", false)) {
        command.kind = Kind::Release;
    } else if (input.value("接管", false)) {
        command.kind = Kind::Acquire;
    } else if (input.value("退出", false)) {
        command.kind = Kind::Quit;
    } else {
        throw std::runtime_error("unknown command");
    }
    return command;
}

action_sequence::Resolved resolve_execution(const Command& command,
    const motion_catalog::Library& library, const ArmPose& pose) {
    const auto& step = command.sequence.steps.front();
    auto effective = command.sequence;
    const auto asset = library.load_asset(step.name, true);
    if (asset.waypoints.size() == 1) {
        effective.steps.front().duration_ms = step.transition_ms;
        effective.steps.front().hold_ms = step.duration_ms;
    }
    auto action = sequence_library::resolve(effective, library, command.limits, pose);
    double seconds = 0;
    for (const auto& point : action.waypoints) seconds += point.requested_duration;
    if (std::abs(seconds - step.duration_ms / 1000.0) < 0.000001) {
        const auto first = library.load_asset(step.name, true).waypoints.front().arm;
        action.waypoints.insert(action.waypoints.begin(), {step.transition_ms / 1000.0, first});
        for (auto& end : action.sequence_step_end) ++end;
        action.phase_end.fill(action.waypoints.size());
        seconds += step.transition_ms / 1000.0;
    }
    if (std::abs(seconds - command.expected_ms / 1000.0) > 0.000001)
        throw std::runtime_error("resolved duration differs from requested timing");
    if (monotonic_seconds() > command.start_before)
        throw std::runtime_error("execution start deadline expired");
    return action;
}

class SocketServer {
public:
    SocketServer(CommandQueue& queue, StatusStore& status,
                 const motion_catalog::Library& library,
                 const std::string& limits_path, double initial_yaw,
                 bool allow_preview = false,
                 const std::string& socket_name = kSocketName)
        : queue_(queue), status_(status), library_(library),
          limits_path_(limits_path), initial_yaw_(initial_yaw),
          allow_preview_(allow_preview), socket_name_(socket_name) {
        fd_ = socket(AF_UNIX, SOCK_STREAM, 0);
        if (fd_ < 0) throw std::runtime_error("cannot create command socket");
        sockaddr_un address{};
        if (!motion_catalog::valid_name(socket_name_) ||
            socket_name_.size() >= sizeof(address.sun_path)) {
            close(fd_);
            throw std::runtime_error("invalid command socket name");
        }
        address.sun_family = AF_UNIX;
        address.sun_path[0] = '\0';
        std::memcpy(address.sun_path + 1, socket_name_.data(), socket_name_.size());
        const socklen_t length = static_cast<socklen_t>(
            offsetof(sockaddr_un, sun_path) + 1 + socket_name_.size());
        if (bind(fd_, reinterpret_cast<sockaddr*>(&address), length) != 0 ||
            listen(fd_, 8) != 0) {
            close(fd_);
            throw std::runtime_error("cannot bind command socket; is another controller running?");
        }
        thread_ = std::thread([this]() { run(); });
    }

    ~SocketServer() {
        stop_ = true;
        if (thread_.joinable()) thread_.join();
        close(fd_);
    }

    bool healthy() const { return healthy_; }
    void set_initial_yaw(double yaw) { initial_yaw_ = yaw; }

private:
    void handle(int client) {
        timeval timeout{2, 0};
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        nlohmann::json response;
        try {
            std::string payload;
            char buffer[2048];
            while (payload.find('\n') == std::string::npos) {
                const ssize_t count = recv(client, buffer, sizeof(buffer), 0);
                if (count < 0) throw std::runtime_error("command read timed out");
                if (count == 0) break;
                payload.append(buffer, static_cast<size_t>(count));
                if (payload.size() > 65536) throw std::runtime_error("command too large");
            }
            if (payload.empty()) throw std::runtime_error("empty command");
            const auto input = nlohmann::json::parse(payload);
            if (input.is_object() && input.size() == 1 && input.value("状态", false)) {
                response = {{"ok", true}, {"status", status_.get()}};
            } else {
                auto payload = input;
                if (input.is_object() && input.size() == 1 && input.contains("cancel_execution")) {
                    const std::string id = input.at("cancel_execution").get<std::string>();
                    const auto entries = status_.get().at("executions");
                    if (!entries.contains(id)) throw std::runtime_error("unknown execution id");
                    const std::string state = entries.at(id).at("state");
                    if (state != "accepted" && state != "running" && state != "cancelling") {
                        const std::string line = nlohmann::json({{"ok", true}, {"message", "already terminal"}}).dump() + "\n";
                        send(client, line.data(), line.size(), MSG_NOSIGNAL);
                        return;
                    }
                    payload = {{"停止", true}};
                }
                std::string execution_id;
                double start_before = 0;
                int expected_ms = 0;
                if (input.contains("execution")) {
                    if (allow_preview_)
                        throw std::runtime_error("execution protocol requires normal service, not preview");
                    const auto& execution = input.at("execution");
                    if (input.size() != 1 || !execution.is_object() || execution.size() != 4)
                        throw std::runtime_error("invalid execution envelope");
                    if (!execution.at("job_id").is_string() ||
                        !execution.at("start_before").is_number() ||
                        !execution.at("expected_ms").is_number_integer())
                        throw std::runtime_error("invalid execution field types");
                    execution_id = execution.at("job_id").get<std::string>();
                    start_before = execution.at("start_before").get<double>();
                    expected_ms = execution.at("expected_ms").get<int>();
                    if (!motion_catalog::valid_name(execution_id) || !std::isfinite(start_before) ||
                        start_before <= monotonic_seconds() || expected_ms < 1 || expected_ms > 180000)
                        throw std::runtime_error("invalid execution id, deadline or duration");
                    const auto current = status_.get();
                    if (status_.seen_execution(execution_id))
                        throw std::runtime_error("duplicate execution id");
                    if (!status_.reserve_history_space())
                        throw std::runtime_error("execution history has no terminal slot");
                    for (const auto& item : current.at("executions").items()) {
                        const std::string state = item.value().at("state");
                        if (state == "accepted" || state == "running" || state == "cancelling")
                            throw std::runtime_error("execution busy");
                    }
                    if (!queue_.empty() || current.at("state") != "idle")
                        throw std::runtime_error("execution busy");
                    payload = {{"序列", execution.at("sequence")}};
                }
                Command parsed = parse_command(payload, library_, limits_path_, initial_yaw_.load(),
                    status_.get().value("joint_limits_skipped", false));
                if (!execution_id.empty()) {
                    if (parsed.sequence.steps.size() != 1)
                        throw std::runtime_error("offline execution requires one motion step");
                    const auto& step = parsed.sequence.steps.front();
                    const auto asset = library_.load_asset(step.name, true);
                    if (step.type != "motion" || step.total_ms || step.repeat != 1 ||
                        step.transition_ms <= 0 || step.duration_ms <= 0 || step.hold_ms != 0 ||
                        expected_ms != step.transition_ms + step.duration_ms ||
                        (asset.timing_profile.enabled && expected_ms < asset.timing_profile.minimum_total_ms))
                        throw std::runtime_error("execution timing incompatible with motion or minimum duration");
                    parsed.execution_id = execution_id;
                    parsed.start_before = start_before;
                    parsed.expected_ms = expected_ms;
                }
                const std::string ownership = status_.ownership();
                if (allow_preview_ && parsed.kind != Kind::Preview &&
                    parsed.kind != Kind::Acquire && parsed.kind != Kind::Release &&
                    parsed.kind != Kind::Stop && parsed.kind != Kind::Quit)
                    throw std::runtime_error("preview session accepts only preview and control commands");
                if (parsed.kind == Kind::Preview && !allow_preview_)
                    throw std::runtime_error("preview requires server --allow-preview");
                if (parsed.kind == Kind::Acquire && ownership != "released")
                    throw std::runtime_error("acquire requires released ownership");
                if (parsed.kind == Kind::Release && ownership != "owned")
                    throw std::runtime_error("release requires owned upper body");
                if (parsed.kind != Kind::Acquire && parsed.kind != Kind::Release &&
                    parsed.kind != Kind::Quit && ownership != "owned")
                    throw std::runtime_error("upper body is released; acquire after robot stops");
                if (parsed.kind == Kind::Preview) {
                    if (preview_requested_ || !queue_.empty() ||
                        status_.get().at("state") != "idle")
                        throw std::runtime_error("preview session permits one idle action");
                }
                const Kind kind = parsed.kind;
                const std::string preview_name = kind == Kind::Preview ?
                    preview_label(parsed) : "";
                const bool preview_limits_verified = kind == Kind::Preview ?
                    parsed.limits.verified : true;
                if (kind == Kind::Release) status_.set_ownership("releasing");
                if (kind == Kind::Acquire) status_.set_ownership("acquiring");
                if (kind == Kind::Preview)
                    status_.set_preview(preview_name, "queued", "", preview_limits_verified);
                if (!execution_id.empty()) status_.execution(execution_id, "accepted");
                if (!queue_.push(std::move(parsed))) {
                    if (!execution_id.empty()) status_.execution(execution_id, "rejected", "queue full");
                    status_.set_ownership(ownership);
                    if (kind == Kind::Preview)
                        status_.set_preview(preview_name, "rejected", "command queue is full");
                    throw std::runtime_error("command queue is full");
                }
                if (kind == Kind::Preview) preview_requested_ = true;
                if (preview_requested_ && (kind == Kind::Stop ||
                                           kind == Kind::Release || kind == Kind::Quit)) {
                    const auto preview = status_.get().at("preview");
                    if (preview.is_object() &&
                        (preview.at("state") == "queued" || preview.at("state") == "running"))
                        status_.set_preview(preview.at("name").get<std::string>(), "cancelled");
                }
                if (kind == Kind::Stop || kind == Kind::Release || kind == Kind::Quit)
                    status_.cancel_executions();
                response = {{"ok", true}, {"message", "queued"}};
                if (!execution_id.empty()) response["execution_id"] = execution_id;
                if (kind == Kind::Preview && !preview_limits_verified)
                    response["warning"] = "joint limits unverified; preview has no per-joint range check";
            }
        } catch (const std::exception& error) {
            response = {{"ok", false}, {"error", error.what()}};
        }
        const std::string line = response.dump() + "\n";
        send(client, line.data(), line.size(), MSG_NOSIGNAL);
    }

    void run() {
        while (!stop_) {
            pollfd descriptor{fd_, POLLIN, 0};
            const int result = poll(&descriptor, 1, 100);
            if (result < 0) {
                if (!stop_) healthy_ = false;
                return;
            }
            if (result == 0) continue;
            if (!(descriptor.revents & POLLIN)) {
                healthy_ = false;
                return;
            }
            const int client = accept(fd_, nullptr, nullptr);
            if (client < 0) continue;
            handle(client);
            close(client);
        }
    }

    CommandQueue& queue_;
    StatusStore& status_;
    const motion_catalog::Library& library_;
    std::string limits_path_;
    std::atomic<double> initial_yaw_;
    bool allow_preview_ = false;
    bool preview_requested_ = false;
    std::string socket_name_;
    int fd_ = -1;
    std::atomic<bool> stop_{false};
    std::atomic<bool> healthy_{true};
    std::thread thread_;
};

bool return_home(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
                 const Snapshot& initial, ArmPose& arm_command, double& yaw_command,
                 bool check_leg_motion,
                 const std::vector<standing_motion::Waypoint>* play_return = nullptr);

bool control_loop(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
                  Snapshot session_initial, CommandQueue& queue,
                  SocketServer& server, StatusStore& status,
                  const motion_catalog::Library& library,
                  ArmPose& arm_command, double& yaw_command,
                  double& weight, bool start_owned,
                  bool operator_preview) {
    std::deque<Command> pending_actions;
    std::unique_ptr<action_sequence::Resolved> pending_answer;
    bool pending_resume = false;
    bool pending_quit = false;
    bool pending_release = false;
    std::string active_execution;
    bool preview_running = false;
    bool play_style_active = false;
    bool reverse_return_active = false;
    bool owned = start_owned;
    motion_interrupt::Player player(session_initial.arm);
    double yaw_from = session_initial.yaw;
    double yaw_to = session_initial.yaw;
    double yaw_duration = 1.0;
    bool yaw_active = false;
    bool yaw_braking = false;
    double yaw_brake_start = 0.0;
    double yaw_brake_duration = 0.0;
    double saved_yaw_target = session_initial.yaw;
    std::chrono::steady_clock::time_point yaw_start{};
    auto wake = std::chrono::steady_clock::now();
    auto previous = wake;
    std::chrono::steady_clock::time_point stable_since{};

    while (true) {
        const auto now = std::chrono::steady_clock::now();
        if (now - wake > std::chrono::milliseconds(50) || !server.healthy()) return false;
        const Snapshot measured = snapshot();
        if (!ready(measured)) return false;
        if (owned) {
            if (!operator_preview && measured.max_leg_speed >= 0.12) {
                std::cerr << "[SAFETY] leg motion detected while upper body is owned; releasing control\n";
                publish(publisher, cmd, session_initial, measured.arm, measured.yaw, 0.0);
                weight = 0.0;
                status.set_ownership("released");
                return false;
            }
            if (std::abs(measured.yaw - yaw_command) > 0.12) return false;
            for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
                if (std::abs(measured.arm[i] - arm_command[i]) > 0.30) return false;
        } else if (operator_preview || standing_still(measured)) {
            if (stable_since.time_since_epoch().count() == 0) stable_since = now;
        } else {
            stable_since = {};
        }

        player.tick(play_style_active ? std::chrono::duration<double>(kPlayTick).count() :
                    std::chrono::duration<double>(now - previous).count());
        previous = now;
        if (!active_execution.empty() && player.state() == motion_interrupt::State::Idle) {
            const auto execution = status.get().at("executions").at(active_execution);
            status.execution(active_execution,
                execution.at("state") == "cancelling" ? "cancelled" : "completed");
            active_execution.clear();
        }
        if (preview_running && player.state() == motion_interrupt::State::Idle) {
            const auto preview = status.get().at("preview");
            if (preview.at("state") == "running")
                status.set_preview(preview.at("name").get<std::string>(), "completed");
            preview_running = false;
            pending_release = true;
            status.set_ownership("releasing");
        }

        for (Command& command : queue.take_all()) {
          try {
            if (pending_quit) continue;
            if (command.kind == Kind::Acquire) {
                if (owned || stable_since.time_since_epoch().count() == 0 ||
                    now - stable_since < std::chrono::milliseconds(500) ||
                    (!operator_preview && std::abs(measured.yaw) > kMaxAbsoluteYaw))
                    throw std::runtime_error(operator_preview ?
                        "acquire requires 500 ms of fresh lowstate" :
                        "acquire requires 500 ms of stable standing");
                session_initial = measured;
                if (!ramp_up(publisher, cmd, session_initial, weight, !operator_preview)) {
                    std::cerr << "[REJECTED] acquire ramp interrupted by stale lowstate, "
                                 "remote exit or movement guard\n";
                    status.set_ownership("released");
                    wake = std::chrono::steady_clock::now();
                    previous = wake;
                    continue;
                }
                owned = true;
                const Snapshot acquired = snapshot();
                if (!ready(acquired)) return false;
                double arm_error = 0.0;
                for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
                    arm_error = std::max(arm_error,
                        std::abs(acquired.arm[i] - session_initial.arm[i]));
                if (arm_error > (operator_preview ? 0.30 : 0.03) ||
                    std::abs(acquired.yaw - session_initial.yaw) >
                        (operator_preview ? 0.12 : 0.05)) {
                    ramp_down(publisher, cmd, session_initial, arm_command, yaw_command, weight);
                    weight = 0.0;
                    owned = false;
                    status.set_ownership("released");
                    wake = std::chrono::steady_clock::now();
                    previous = wake;
                    std::cerr << "[REJECTED] arm failed to settle during acquire: "
                              << "arm_error=" << arm_error << " rad, yaw_error="
                              << std::abs(acquired.yaw - session_initial.yaw)
                              << " rad\n";
                    continue;
                }
                player.reset_idle_pose(acquired.arm);
                play_style_active = false;
                reverse_return_active = false;
                arm_command = acquired.arm;
                yaw_command = acquired.yaw;
                yaw_from = yaw_to = saved_yaw_target = acquired.yaw;
                yaw_active = yaw_braking = false;
                server.set_initial_yaw(session_initial.yaw);
                status.set_ownership("owned");
                stable_since = {};
                wake = std::chrono::steady_clock::now();
                previous = wake;
                std::cout << "[ACQUIRE] upper body control active\n";
                continue;
            }
            if (command.kind == Kind::Quit && !owned) return true;
            if (!owned) throw std::runtime_error("upper body is released");
            if (command.kind == Kind::Action || command.kind == Kind::Sequence ||
                command.kind == Kind::Preview) {
                pending_actions.push_back(std::move(command));
            } else if (command.kind == Kind::Answer) {
                if (player.state() != motion_interrupt::State::Paused &&
                    player.state() != motion_interrupt::State::Braking)
                    throw std::runtime_error("answer requires interrupted action");
                pending_answer.reset(new action_sequence::Resolved(std::move(command.action)));
            } else if (command.kind == Kind::Waist) {
                if (player.state() == motion_interrupt::State::Paused ||
                    player.state() == motion_interrupt::State::Braking)
                    throw std::runtime_error("waist update requires active motion");
                yaw_from = yaw_command;
                yaw_to = session_initial.yaw + command.yaw_degrees * kPi / 180.0;
                saved_yaw_target = yaw_to;
                yaw_duration = std::max(1.0, standing_motion::minimum_duration(
                    std::abs(yaw_to - yaw_from), standing_motion::kMaxYawVelocity,
                    standing_motion::kMaxYawAcceleration));
                yaw_start = now;
                yaw_active = true;
                yaw_braking = false;
                std::cout << "[WAIST] target " << command.yaw_degrees
                          << " deg relative, planned " << yaw_duration << " s\n";
            } else if (command.kind == Kind::Stop || command.kind == Kind::Release) {
                pending_actions.clear();
                pending_answer.reset();
                pending_resume = false;
                player.cancel();
                if (yaw_active && !yaw_braking) {
                    yaw_brake_start = std::chrono::duration<double>(now - yaw_start).count();
                    yaw_brake_duration = std::min(0.5, std::max(0.1, 2 * (yaw_duration - yaw_brake_start)));
                    yaw_start = now;
                    yaw_braking = true;
                }
                if (command.kind == Kind::Release) pending_release = true;
                std::cout << (pending_release ? "[RELEASE]" : "[STOP]")
                          << " braking and cancelling action\n";
            } else if (command.kind == Kind::Interrupt) {
                player.interrupt();
                if (yaw_active && !yaw_braking) {
                    yaw_brake_start = std::chrono::duration<double>(now - yaw_start).count();
                    yaw_brake_duration = std::min(0.5, std::max(0.1, 2 * (yaw_duration - yaw_brake_start)));
                    yaw_start = now;
                    yaw_braking = true;
                }
                std::cout << "[INTERRUPT] braking, checkpoint pending\n";
            } else if (command.kind == Kind::Resume) {
                if (player.state() != motion_interrupt::State::Paused &&
                    player.state() != motion_interrupt::State::Answering &&
                    player.state() != motion_interrupt::State::Braking)
                    throw std::runtime_error("no interrupted action to resume");
                pending_resume = true;
            } else if (command.kind == Kind::Quit) {
                pending_actions.clear();
                pending_answer.reset();
                pending_resume = false;
                player.cancel();
                if (yaw_active && !yaw_braking) {
                    yaw_brake_start = std::chrono::duration<double>(now - yaw_start).count();
                    yaw_brake_duration = std::min(0.5, std::max(0.1, 2 * (yaw_duration - yaw_brake_start)));
                    yaw_start = now;
                    yaw_braking = true;
                }
                pending_quit = true;
            }
          } catch (const std::exception& error) {
            if (command.kind == Kind::Acquire) status.set_ownership("released");
            if (command.kind == Kind::Release) status.set_ownership("owned");
            std::cerr << "[REJECTED] " << error.what() << "\n";
          }
        }

        if (owned && (pending_release || pending_quit) &&
            player.state() == motion_interrupt::State::Idle && !yaw_active) {
            arm_command = player.pose();
            const auto play_return = reverse_return_active ? player.preview_return_waypoints() :
                std::vector<standing_motion::Waypoint>{};
            if (!return_home(publisher, cmd, session_initial, arm_command, yaw_command,
                             !operator_preview, reverse_return_active ? &play_return : nullptr))
                return false;
            ramp_down(publisher, cmd, session_initial, arm_command, yaw_command, weight);
            weight = 0.0;
            owned = false;
            pending_release = false;
            status.set_ownership("released");
            const Snapshot released = snapshot();
            if (!ready(released)) return false;
            player.reset_idle_pose(released.arm);
            arm_command = released.arm;
            yaw_command = released.yaw;
            status.update(player);
            std::cout << "[RELEASE] arm_sdk weight is zero; native control owns upper body\n";
            if (pending_quit) return true;
            stable_since = {};
            wake = std::chrono::steady_clock::now();
            previous = wake;
            continue;
        }

        if (player.state() == motion_interrupt::State::Paused && pending_answer) {
            player.answer(std::move(*pending_answer));
            pending_answer.reset();
        } else if (player.state() == motion_interrupt::State::Paused && pending_resume) {
            player.resume();
            pending_resume = false;
            yaw_from = yaw_command;
            yaw_to = saved_yaw_target;
            yaw_duration = std::max(1.0, standing_motion::minimum_duration(
                std::abs(yaw_to - yaw_from), standing_motion::kMaxYawVelocity,
                standing_motion::kMaxYawAcceleration));
            yaw_start = now;
            yaw_active = true;
            yaw_braking = false;
            std::cout << "[RESUME] continuing unfinished action\n";
        }

        if (player.state() == motion_interrupt::State::Idle && !pending_actions.empty()) {
            Command queued = std::move(pending_actions.front());
            pending_actions.pop_front();
            try {
                if (!queued.execution_id.empty() &&
                    status.get().at("executions").at(queued.execution_id).at("state") == "cancelled") continue;
                if (queued.kind == Kind::Sequence || queued.kind == Kind::Preview) {
                    const bool preview = queued.kind == Kind::Preview;
                    const auto action = queued.execution_id.empty() ? sequence_library::resolve(
                        queued.sequence, library, queued.limits, player.pose(), measured.arm,
                        preview) : resolve_execution(queued, library, player.pose());
                    const auto plan = standing_motion::make_plan(
                        player.pose(), 0.0, 0.0, action.waypoints);
                    double planned_core = 0.0;
                    if (preview) planned_core = preview_core_seconds(plan, queued, library);
                    std::cout << (preview ? "[PREVIEW] " : "[SEQUENCE] ")
                              << queued.sequence.name << " started; "
                              << plan.total_duration << " s planned"
                              << (action.play_style_preview ? "; play-style linear, 2 ms commands" : "")
                              << "\n";
                    player.start(action);
                    if (!queued.execution_id.empty()) {
                        active_execution = queued.execution_id;
                        status.execution(active_execution, "running", "", plan.total_duration);
                        if (status.get().at("executions").at(active_execution).at("state") == "cancelling")
                            player.cancel();
                    }
                    play_style_active = action.play_style_preview;
                    reverse_return_active = action.play_style_preview && !queued.combo_preview;
                    wake = std::chrono::steady_clock::now();
                    previous = wake;
                    if (preview) {
                        preview_running = true;
                        status.set_preview(preview_label(queued), "running", "",
                                           queued.limits.verified, plan.total_duration,
                                           planned_core);
                    }
                } else {
                    const auto arm_plan = standing_motion::make_plan(
                        player.pose(), 0.0, 0.0, queued.action.waypoints);
                    const auto actual = action_sequence::actual_phase_durations(
                        queued.action, arm_plan);
                    std::cout << "[ACTION] " << queued.action.request.label
                              << " started; requested/actual seconds:";
                    for (size_t i = 0; i < actual.size(); ++i)
                        std::cout << " " << action_sequence::kSteps[i] << "="
                                  << queued.action.request.steps[i].requested_seconds
                                  << "/" << actual[i];
                    std::cout << "\n";
                    player.start(std::move(queued.action));
                }
            } catch (const std::exception& error) {
                if (!queued.execution_id.empty())
                    status.execution(queued.execution_id, "rejected", error.what());
                if (queued.kind == Kind::Preview) {
                    status.set_preview(preview_label(queued), "rejected", error.what());
                    pending_release = true;
                    status.set_ownership("releasing");
                }
                std::cerr << "[REJECTED] " << error.what() << "\n";
            }
        }
        arm_command = player.pose();
        if (yaw_active) {
            const double elapsed = std::chrono::duration<double>(now - yaw_start).count();
            if (yaw_braking) {
                const double u = std::min(1.0, elapsed / yaw_brake_duration);
                const double progress = std::min(yaw_duration,
                    yaw_brake_start + yaw_brake_duration * (u - u * u / 2));
                yaw_command = yaw_from + (yaw_to - yaw_from) *
                              standing_motion::linear_phase(progress / yaw_duration);
                if (u >= 1.0) { yaw_active = false; yaw_braking = false; }
            } else {
                yaw_command = yaw_from + (yaw_to - yaw_from) *
                              standing_motion::linear_phase(elapsed / yaw_duration);
                if (elapsed >= yaw_duration) yaw_active = false;
            }
        }
        status.update(player);
        if (owned) publish(publisher, cmd, session_initial, arm_command, yaw_command, 1.0);
        if (play_style_active) {
            wake = std::chrono::steady_clock::now();
            std::this_thread::sleep_for(kPlayTick);
        } else {
            wake += kTick;
            std::this_thread::sleep_until(wake);
        }
    }
}

bool return_home(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
                 const Snapshot& initial, ArmPose& arm_command, double& yaw_command,
                 bool check_leg_motion,
                 const std::vector<standing_motion::Waypoint>* play_return) {
    const Snapshot measured = snapshot();
    if (!ready(measured)) return false;
    if (play_return && play_return->empty()) return true;
    const ArmPose start_arm = play_return ? arm_command : measured.arm;
    const double start_yaw = play_return ? yaw_command : measured.yaw;
    const standing_motion::Plan plan = standing_motion::make_plan(
        start_arm, start_yaw, play_return ? start_yaw : initial.yaw,
        play_return ? *play_return : std::vector<standing_motion::Waypoint>{{2.0, initial.arm}});
    arm_command = start_arm;
    yaw_command = start_yaw;
    const auto start = std::chrono::steady_clock::now();
    auto wake = start;
    double play_elapsed = 0.0;
    std::cout << "Returning to startup pose in " << plan.total_duration << " s.\n";
    while (true) {
        const auto now = std::chrono::steady_clock::now();
        const Snapshot state = snapshot();
        if (now - wake > std::chrono::milliseconds(50) || !ready(state) ||
            (check_leg_motion && state.max_leg_speed >= 0.12) ||
            std::abs(state.yaw - yaw_command) > 0.12) return false;
        for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
            if (std::abs(state.arm[i] - arm_command[i]) > 0.30) return false;
        const double elapsed = play_return ? play_elapsed :
            std::chrono::duration<double>(now - start).count();
        const auto sample = standing_motion::sample(plan, elapsed);
        arm_command = sample.arm;
        yaw_command = sample.yaw;
        publish(publisher, cmd, initial, arm_command, yaw_command, 1.0);
        if (elapsed >= plan.total_duration) return true;
        if (play_return) {
            play_elapsed += std::chrono::duration<double>(kPlayTick).count();
            wake = std::chrono::steady_clock::now();
            std::this_thread::sleep_for(kPlayTick);
        } else {
            wake += kTick;
            std::this_thread::sleep_until(wake);
        }
    }
}

struct Options {
    std::string directory = "motions";
    std::string poses = "poses";
    std::string catalog = "config/motion_catalog.json";
    std::string metadata = "metadata";
    std::string limits = "config/arm_joint_limits.json";
    std::string check_request;
    bool check_only = false;
    std::string check_sequence;
    bool check_sequence_only = false;
    std::string check_preview;
    bool check_preview_only = false;
    std::string check_preview_request;
    bool check_preview_request_only = false;
    bool skip_joint_limits = false;
    bool offline_server = false;
    bool allow_preview = false;
    bool auto_preview = false;
    bool start_released = true;
    std::string socket_name = kSocketName;
};

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--help") {
            std::cout << "Usage: " << argv[0]
                      << " [--dir MOTIONS] [--poses POSES] [--catalog FILE]"
                      << " [--metadata DIR] [--limits FILE]"
                      << " [--check-request FILE | --check-sequence JSON | --check-preview NAME"
                      << " | --check-preview-request JSON | --offline-server]"
                      << " [--allow-preview] [--auto-preview] [--socket-name NAME]"
                      << " [--start-released (default)] [--skip-joint-limits]\n";
            std::exit(0);
        } else if (argument == "--dir" && i + 1 < argc) {
            options.directory = argv[++i];
        } else if (argument == "--poses" && i + 1 < argc) {
            options.poses = argv[++i];
        } else if (argument == "--catalog" && i + 1 < argc) {
            options.catalog = argv[++i];
        } else if (argument == "--metadata" && i + 1 < argc) {
            options.metadata = argv[++i];
        } else if (argument == "--limits" && i + 1 < argc) {
            options.limits = argv[++i];
        } else if (argument == "--check-request" && i + 1 < argc) {
            options.check_request = argv[++i];
            options.check_only = true;
        } else if (argument == "--check-sequence" && i + 1 < argc) {
            options.check_sequence = argv[++i];
            options.check_sequence_only = true;
        } else if (argument == "--check-preview" && i + 1 < argc) {
            options.check_preview = argv[++i];
            options.check_preview_only = true;
        } else if (argument == "--check-preview-request" && i + 1 < argc) {
            options.check_preview_request = argv[++i];
            options.check_preview_request_only = true;
        } else if (argument == "--offline-server") {
            options.offline_server = true;
        } else if (argument == "--allow-preview") {
            options.allow_preview = true;
        } else if (argument == "--auto-preview") {
            options.auto_preview = true;
        } else if (argument == "--socket-name" && i + 1 < argc) {
            options.socket_name = argv[++i];
        } else if (argument == "--skip-joint-limits") {
            options.skip_joint_limits = true;
        } else if (argument == "--start-released") {
            options.start_released = true;
        } else {
            throw std::runtime_error("unknown or incomplete argument: '" + argument + "'");
        }
    }
    if (static_cast<int>(options.check_only) + static_cast<int>(options.check_sequence_only) +
        static_cast<int>(options.check_preview_only) +
        static_cast<int>(options.check_preview_request_only) +
        static_cast<int>(options.offline_server) > 1)
        throw std::runtime_error("choose one offline mode");
    if (options.auto_preview && !options.allow_preview)
        throw std::runtime_error("--auto-preview requires --allow-preview");
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        if (options.skip_joint_limits)
            std::cerr << "JOINT LIMIT CHECKS SKIPPED by explicit operator option; profile unchanged.\n";
        const motion_catalog::Library library{
            motion_catalog::Catalog::load(options.catalog), options.directory,
            options.metadata, true, options.poses};
        if (options.check_only) {
            std::ifstream file(options.check_request);
            if (!file) throw std::runtime_error("cannot open request file");
            const std::string text((std::istreambuf_iterator<char>(file)),
                                   std::istreambuf_iterator<char>());
            const auto action = action_sequence::resolve(
                action_sequence::parse(text), library);
            std::cout << "Request valid: " << action.waypoints.size()
                      << " waypoints across 4 actions. No robot connection was made.\n";
            return 0;
        }

        if (options.check_sequence_only) {
            std::ifstream file;
            if (options.check_sequence != "-") file.open(options.check_sequence);
            if (options.check_sequence != "-" && !file)
                throw std::runtime_error("cannot open sequence JSON file");
            std::istream& input = options.check_sequence == "-" ? std::cin : file;
            const auto document = nlohmann::json::parse(input);
            const auto definition = sequence_library::parse(document);
            const auto limits = options.skip_joint_limits ? sequence_library::JointLimits::unchecked() :
                sequence_library::JointLimits::load(options.limits);
            const auto start = library.load_asset(definition.steps.front().name, true)
                                   .waypoints.front().arm;
            const auto action = sequence_library::resolve(definition, library, limits, start);
            const auto plan = standing_motion::make_plan(start, 0.0, 0.0, action.waypoints);
            std::cout << "Sequence valid: " << action.sequence_step_end.size()
                      << " steps, " << plan.total_duration
                      << " s from first entry pose. No robot connection was made.\n";
            return 0;
        }

        if (options.check_preview_only) {
            const auto asset = library.load_asset(options.check_preview, true, true);
            const auto limits = sequence_library::JointLimits::for_preview(options.limits);
            const auto definition = preview_definition(asset);
            const ArmPose start = asset.waypoints.front().arm;
            const auto action = sequence_library::resolve(
                definition, library, limits, start, start, true);
            const auto plan = standing_motion::make_plan(start, 0.0, 0.0, action.waypoints);
            std::cout << "Preview valid: " << asset.entry.name << ", "
                      << plan.total_duration
                      << " s from entry pose. No robot connection was made.\n";
            if (!limits.verified)
                std::cout << "Warning: joint limits unverified; per-joint range was not checked.\n";
            return 0;
        }

        if (options.check_preview_request_only) {
            std::ifstream file;
            if (options.check_preview_request != "-") file.open(options.check_preview_request);
            if (options.check_preview_request != "-" && !file)
                throw std::runtime_error("cannot open preview request JSON");
            std::istream& input = options.check_preview_request == "-" ? std::cin : file;
            const auto command = parse_command(nlohmann::json::parse(input), library,
                                               options.limits, 0.0);
            if (command.kind != Kind::Preview)
                throw std::runtime_error("expected a preview request");
            const auto& step = command.sequence.steps.front();
            const auto asset = library.load_asset(step.name, true, true);
            const ArmPose start = asset.waypoints.front().arm;
            const auto action = sequence_library::resolve(
                command.sequence, library, command.limits, start, start, true);
            const auto plan = standing_motion::make_plan(start, 0.0, 0.0, action.waypoints);
            std::cout << "Preview valid: " << preview_label(command);
            if (!command.combo_preview && asset.waypoints.size() > 1) {
                const auto& profile = step.timing_profile.enabled ? step.timing_profile : asset.timing_profile;
                const double requested_core = step.total_ms ?
                    std::max(step.total_ms, profile.minimum_total_ms) / 1000.0 * profile.core / profile.weight_sum() :
                    step.duration_ms / 1000.0;
                std::cout << ", core requested " << requested_core
                          << " s, core planned " << preview_core_seconds(plan, step, asset)
                          << " s";
            }
            std::cout << ", total planned " << plan.total_duration
                      << " s from entry pose. No robot connection was made.\n";
            if (action.play_style_preview)
                std::cout << "Play-style linear preview: 2 ms commands; requested timing, "
                             "no velocity/acceleration retiming; "
                          << (command.combo_preview ? "return directly to startup pose.\n" :
                              "reverse the traversed path on return.\n");
            if (!command.limits.verified)
                std::cout << "Warning: joint limits unverified; per-joint range was not checked.\n";
            return 0;
        }

        if (options.offline_server) {
            std::signal(SIGINT, on_signal);
            CommandQueue queue;
            StatusStore status;
            status.set_skip_limits(options.skip_joint_limits);
            status.set_offline();
            if (options.start_released) status.set_ownership("released");
            SocketServer server(queue, status, library, options.limits, 0.0,
                                options.allow_preview, options.socket_name);
            motion_interrupt::Player player(ArmPose{});
            std::string active_execution;
            bool preview_running = false;
            auto previous = std::chrono::steady_clock::now();
            std::cout << "Offline command server ready. No robot connection was made.\n";
            while (!g_interrupted && server.healthy()) {
                const auto now = std::chrono::steady_clock::now();
                player.tick(std::chrono::duration<double>(now - previous).count());
                previous = now;
                if (!active_execution.empty() && player.state() == motion_interrupt::State::Idle) {
                    const auto execution = status.get().at("executions").at(active_execution);
                    status.execution(active_execution,
                        execution.at("state") == "cancelling" ? "cancelled" : "completed");
                    active_execution.clear();
                }
                if (preview_running && player.state() == motion_interrupt::State::Idle) {
                    const auto preview = status.get().at("preview");
                    if (preview.at("state") == "running")
                        status.set_preview(preview.at("name").get<std::string>(), "completed");
                    preview_running = false;
                    status.set_ownership("releasing");
                }
                for (Command& command : queue.take_all()) {
                    if (command.kind == Kind::Quit) return 0;
                    try {
                        if (!command.execution_id.empty()) {
                            const auto entry = status.get().at("executions").at(command.execution_id);
                            if (entry.at("state") == "cancelled") continue;
                            if (monotonic_seconds() > command.start_before)
                                throw std::runtime_error("execution start deadline expired");
                        }
                        if (command.kind == Kind::Release) {
                            player.cancel();
                            status.set_ownership("releasing");
                        }
                        if (command.kind == Kind::Acquire) {
                            if (player.state() != motion_interrupt::State::Idle)
                                throw std::runtime_error("cannot acquire during motion");
                            status.set_ownership("owned");
                        }
                        if (command.kind == Kind::Action) player.start(std::move(command.action));
                        if (command.kind == Kind::Sequence) {
                            const auto action = command.execution_id.empty() ? sequence_library::resolve(
                                command.sequence, library, command.limits, player.pose()) :
                                resolve_execution(command, library, player.pose());
                            if (!command.execution_id.empty()) {
                                double seconds = 0;
                                for (const auto& point : action.waypoints) seconds += point.requested_duration;
                                if (std::abs(seconds - command.expected_ms / 1000.0) > 0.000001)
                                    throw std::runtime_error("resolved duration differs from requested timing");
                                if (monotonic_seconds() > command.start_before)
                                    throw std::runtime_error("execution start deadline expired");
                                player.start(action);
                                active_execution = command.execution_id;
                                status.execution(active_execution, "running", "", seconds);
                                if (status.get().at("executions").at(active_execution).at("state") == "cancelling")
                                    player.cancel();
                            } else player.start(action);
                        }
                        if (command.kind == Kind::Preview) {
                            const auto action = sequence_library::resolve(
                                command.sequence, library, command.limits,
                                player.pose(), player.pose(), true);
                            const auto plan = standing_motion::make_plan(
                                player.pose(), 0.0, 0.0, action.waypoints);
                            const double planned_core = preview_core_seconds(plan, command, library);
                            player.start(action);
                            preview_running = true;
                            status.set_preview(preview_label(command), "running", "",
                                               command.limits.verified, plan.total_duration,
                                               planned_core);
                        }
                        if (command.kind == Kind::Answer) player.answer(std::move(command.action));
                        if (command.kind == Kind::Interrupt) player.interrupt();
                        if (command.kind == Kind::Resume) player.resume();
                        if (command.kind == Kind::Stop) player.cancel();
                    } catch (const std::exception& error) {
                        if (!command.execution_id.empty())
                            status.execution(command.execution_id, "rejected", error.what());
                        if (command.kind == Kind::Acquire) status.set_ownership("released");
                        if (command.kind == Kind::Preview)
                            status.set_preview(preview_label(command),
                                               "rejected", error.what());
                        if (command.kind == Kind::Preview)
                            status.set_ownership("releasing");
                        std::cerr << "[OFFLINE REJECTED] " << error.what() << "\n";
                    }
                }
                if (status.ownership() == "releasing" &&
                    player.state() == motion_interrupt::State::Idle)
                    status.set_ownership("released");
                status.update(player);
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
            return server.healthy() ? 0 : 1;
        }

        std::signal(SIGINT, on_signal);
        std::signal(SIGTERM, on_signal);
        ControllerLock controller_lock;
        std::cout << "Upper-body controller. No other rt/arm_sdk publisher may run.\n"
                  << "Starting released; arms will not be commanded until acquire.\n";
        if (!options.auto_preview) {
            std::cout << (options.allow_preview ?
                          "Preview session (one action). Type PREVIEW then Enter: " :
                          "Type RUN then Enter: ") << std::flush;
            std::string answer;
            if (!std::getline(std::cin, answer) ||
                answer != (options.allow_preview ? "PREVIEW" : "RUN")) return 0;
        }

        ChannelFactory::Instance()->Init(0, pick_iface());
        ChannelSubscriber<LowState_> subscriber("rt/lowstate");
        subscriber.InitChannel(on_state, 10);
        ChannelPublisher<LowCmd_> publisher("rt/arm_sdk");
        publisher.InitChannel();
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!snapshot().received && !g_interrupted &&
               std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        const Snapshot initial = snapshot();
        if (!ready(initial) || (!options.start_released &&
                                std::abs(initial.yaw) > kMaxAbsoluteYaw))
            throw std::runtime_error("robot state unavailable or startup yaw outside demo range");

        LowCmd_ cmd{};
        for (auto& motor : cmd.motor_cmd()) {
            motor.q(0.0f); motor.dq(0.0f); motor.kp(0.0f);
            motor.kd(0.0f); motor.tau(0.0f);
        }
        ArmPose arm_command = initial.arm;
        double yaw_command = initial.yaw;
        double weight = 0.0;
        try {
            if (!options.start_released && !ramp_up(publisher, cmd, initial, weight)) {
                return 1;
            }
            CommandQueue queue;
            StatusStore status;
            status.set_skip_limits(options.skip_joint_limits);
            if (options.start_released) status.set_ownership("released");
            bool clean_exit = false;
            {
                SocketServer server(queue, status, library, options.limits,
                                    initial.yaw, options.allow_preview,
                                    options.socket_name);
                std::cout << "Ready. Send action and waist commands from another terminal.\n";
                clean_exit = control_loop(publisher, cmd, initial, queue, server, status,
                                          library,
                                          arm_command, yaw_command, weight,
                                          !options.start_released,
                                          options.auto_preview);
            }
            if (weight > 0.0)
                ramp_down(publisher, cmd, initial, arm_command, yaw_command, weight);
            std::cout << "Released arm_sdk.\n";
            return clean_exit ? 0 : 1;
        } catch (...) {
            try {
                if (weight > 0.0)
                    ramp_down(publisher, cmd, initial, arm_command, yaw_command, weight);
            }
            catch (...) { std::cerr << "Failed to release arm_sdk cleanly.\n"; }
            throw;
        }
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }
}
