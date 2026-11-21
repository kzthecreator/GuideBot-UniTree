#include "standing_motion.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <ifaddrs.h>
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
constexpr int kWaistYawIndex = 12;
constexpr int kWaistRollIndex = 13;
constexpr int kWaistPitchIndex = 14;
constexpr int kWeightIndex = 29;
constexpr uint16_t kKeyR1 = 1u << 0;
constexpr uint16_t kKeyR2 = 1u << 4;
constexpr double kPi = 3.141592653589793;
constexpr double kMaxDemoYawDelta = 15.0 * kPi / 180.0;
constexpr double kMaxDemoYawAbsolute = 0.40;
constexpr auto kTick = std::chrono::milliseconds(10);

std::mutex g_state_mutex;
LowState_ g_state{};
std::chrono::steady_clock::time_point g_last_state{};
bool g_state_received = false;
volatile std::sig_atomic_t g_interrupted = 0;

struct Options {
    double yaw_degrees = 0.0;
    std::string motion_path;
    bool waist_only = false;
    bool dry_run = false;
};

struct Snapshot {
    ArmPose arm{};
    double yaw = 0.0;
    double roll = 0.0;
    double pitch = 0.0;
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

Snapshot snapshot() {
    std::lock_guard<std::mutex> lock(g_state_mutex);
    Snapshot result;
    result.received = g_state_received;
    if (!result.received) return result;
    for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
        result.arm[i] = g_state.motor_state()[kArmIndex[i]].q();
    result.yaw = g_state.motor_state()[kWaistYawIndex].q();
    result.roll = g_state.motor_state()[kWaistRollIndex].q();
    result.pitch = g_state.motor_state()[kWaistPitchIndex].q();
    std::memcpy(&result.keys, &g_state.wireless_remote()[2], sizeof(result.keys));
    result.time = g_last_state;
    return result;
}

bool ready(const Snapshot& state) {
    if (g_interrupted) return false;
    if (!state.received || std::chrono::steady_clock::now() - state.time >
                               std::chrono::milliseconds(300)) return false;
    if ((state.keys & kKeyR1) && (state.keys & kKeyR2)) return false;
    if (!std::isfinite(state.yaw) || !std::isfinite(state.roll) ||
        !std::isfinite(state.pitch)) return false;
    for (double angle : state.arm)
        if (!std::isfinite(angle)) return false;
    return true;
}

void set_command(LowCmd_& cmd, const ArmPose& arm, double yaw,
                 const Snapshot& initial, double weight) {
    for (size_t i = 0; i < standing_motion::kArmJoints; ++i) {
        auto& motor = cmd.motor_cmd()[kArmIndex[i]];
        motor.q(static_cast<float>(arm[i]));
        motor.dq(0.0f); motor.kp(60.0f); motor.kd(1.5f); motor.tau(0.0f);
    }
    auto& waist = cmd.motor_cmd()[kWaistYawIndex];
    waist.q(static_cast<float>(yaw));
    waist.dq(0.0f); waist.kp(60.0f); waist.kd(1.5f); waist.tau(0.0f);
    // This example claims yaw only; do not command roll/pitch against locomotion.
    for (const int joint : {kWaistRollIndex, kWaistPitchIndex}) {
        auto& motor = cmd.motor_cmd()[joint];
        motor.q(static_cast<float>(joint == kWaistRollIndex ? initial.roll : initial.pitch));
        motor.dq(0.0f); motor.kp(0.0f); motor.kd(0.0f); motor.tau(0.0f);
    }
    cmd.motor_cmd()[kWeightIndex].q(static_cast<float>(weight));
}

void publish(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
             const ArmPose& arm, double yaw, const Snapshot& initial, double weight) {
    set_command(cmd, arm, yaw, initial, weight);
    publisher.Write(cmd);
}

bool ramp_up(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
             const Snapshot& initial, double& weight) {
    constexpr int steps = 200;
    auto wake = std::chrono::steady_clock::now();
    for (int i = 0; i < steps; ++i) {
        if (!ready(snapshot())) return false;
        weight = static_cast<double>(i + 1) / steps;
        publish(publisher, cmd, initial.arm, initial.yaw, initial, weight);
        wake += kTick;
        std::this_thread::sleep_until(wake);
    }
    return true;
}

void ramp_down(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
               const Snapshot& initial, const ArmPose& last_arm,
               double last_yaw, double start_weight) {
    const Snapshot measured = snapshot();
    const ArmPose arm = measured.received &&
        std::chrono::steady_clock::now() - measured.time < std::chrono::milliseconds(300)
        ? measured.arm : last_arm;
    const double yaw = measured.received &&
        std::chrono::steady_clock::now() - measured.time < std::chrono::milliseconds(300)
        ? measured.yaw : last_yaw;
    constexpr int steps = 200;
    auto wake = std::chrono::steady_clock::now();
    for (int i = 0; i < steps; ++i) {
        publish(publisher, cmd, arm, yaw, initial,
                start_weight * (1.0 - static_cast<double>(i + 1) / steps));
        wake += kTick;
        std::this_thread::sleep_until(wake);
    }
    publish(publisher, cmd, arm, yaw, initial, 0.0);
}

bool execute(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
             const Snapshot& initial, const standing_motion::Plan& plan,
             ArmPose& last_arm, double& last_yaw) {
    const auto start = std::chrono::steady_clock::now();
    auto wake = start;
    while (true) {
        if (std::chrono::steady_clock::now() - wake > std::chrono::milliseconds(50))
            return false;
        const Snapshot measured = snapshot();
        if (!ready(measured)) return false;
        if (std::abs(measured.yaw - last_yaw) > 0.12) return false;
        for (size_t i = 0; i < standing_motion::kArmJoints; ++i)
            if (std::abs(measured.arm[i] - last_arm[i]) > 0.30) return false;
        const double elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - start).count();
        const standing_motion::Sample value = standing_motion::sample(plan, elapsed);
        publish(publisher, cmd, value.arm, value.yaw, initial, 1.0);
        last_arm = value.arm;
        last_yaw = value.yaw;
        if (elapsed >= plan.total_duration) return true;
        wake += kTick;
        std::this_thread::sleep_until(wake);
    }
}

bool hold(ChannelPublisher<LowCmd_>& publisher, LowCmd_& cmd,
          const Snapshot& initial, const ArmPose& arm, double yaw) {
    auto wake = std::chrono::steady_clock::now();
    for (int i = 0; i < 100; ++i) {
        if (!ready(snapshot())) return false;
        publish(publisher, cmd, arm, yaw, initial, 1.0);
        wake += kTick;
        std::this_thread::sleep_until(wake);
    }
    return true;
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

Options parse_options(int argc, char** argv) {
    Options options;
    bool have_yaw = false;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--help") {
            std::cout << "Usage: " << argv[0]
                      << " --yaw-deg ANGLE (--motion PATH | --waist-only) [--dry-run]\n"
                      << "ANGLE is relative to startup yaw and limited to +/-15 degrees.\n";
            std::exit(0);
        } else if (argument == "--yaw-deg" && i + 1 < argc) {
            char* end = nullptr;
            options.yaw_degrees = std::strtod(argv[++i], &end);
            if (!end || *end || !std::isfinite(options.yaw_degrees))
                throw std::runtime_error("--yaw-deg requires a finite number");
            have_yaw = true;
        } else if (argument == "--motion" && i + 1 < argc) {
            options.motion_path = argv[++i];
        } else if (argument == "--waist-only") {
            options.waist_only = true;
        } else if (argument == "--dry-run") {
            options.dry_run = true;
        } else {
            throw std::runtime_error("unknown or incomplete argument: " + argument);
        }
    }
    if (!have_yaw || std::abs(options.yaw_degrees) > 15.0)
        throw std::runtime_error("--yaw-deg is required and must be within +/-15");
    if (options.waist_only == !options.motion_path.empty())
        throw std::runtime_error("choose exactly one of --motion and --waist-only");
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        std::vector<standing_motion::Waypoint> points;
        if (!options.waist_only)
            points = standing_motion::load_motion(options.motion_path);
        std::cout << "Standing waist + arm demo: yaw " << options.yaw_degrees
                  << " deg relative, " << points.size() << " arm waypoints\n";
        if (options.dry_run) {
            std::cout << "Dry run complete. No robot connection was made.\n";
            return 0;
        }

        std::signal(SIGINT, on_signal);
        std::signal(SIGTERM, on_signal);
        std::cout << "Confirm robot is standing, supported, and no other arm_sdk publisher is running.\n"
                  << "Type RUN then Enter to engage: " << std::flush;
        std::string confirmation;
        if (!std::getline(std::cin, confirmation) || confirmation != "RUN") return 0;

        const std::string iface = pick_iface();
        ChannelFactory::Instance()->Init(0, iface);
        ChannelSubscriber<LowState_> subscriber("rt/lowstate");
        subscriber.InitChannel(on_state, 10);
        ChannelPublisher<LowCmd_> publisher("rt/arm_sdk");
        publisher.InitChannel();
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!snapshot().received && !g_interrupted &&
               std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        const Snapshot initial = snapshot();
        if (!ready(initial)) throw std::runtime_error("lowstate unavailable or stop requested");
        const double yaw_target = initial.yaw + options.yaw_degrees * kPi / 180.0;
        if (std::abs(options.yaw_degrees * kPi / 180.0) > kMaxDemoYawDelta ||
            std::abs(yaw_target) > kMaxDemoYawAbsolute)
            throw std::runtime_error("yaw target exceeds conservative demo limit");
        if (options.waist_only) points.push_back({2.0, initial.arm});

        LowCmd_ command{};
        for (auto& motor : command.motor_cmd()) {
            motor.q(0.0f); motor.dq(0.0f); motor.kp(0.0f);
            motor.kd(0.0f); motor.tau(0.0f);
        }
        ArmPose last_arm = initial.arm;
        double last_yaw = initial.yaw;
        double current_weight = 0.0;
        std::cout << "Engaging arm_sdk on " << iface << "...\n";
        if (!ramp_up(publisher, command, initial, current_weight)) {
            ramp_down(publisher, command, initial, last_arm, last_yaw, current_weight);
            return 1;
        }
        current_weight = 1.0;
        const Snapshot engaged = snapshot();
        if (!ready(engaged)) {
            ramp_down(publisher, command, initial, last_arm, last_yaw, current_weight);
            return 1;
        }
        const standing_motion::Plan forward = standing_motion::make_plan(
            engaged.arm, engaged.yaw, yaw_target, points);
        std::cout << "Executing synchronized trajectory, " << forward.total_duration
                  << " s. R1+R2 or Ctrl+C stops it.\n";
        bool completed = execute(publisher, command, initial, forward, last_arm, last_yaw);
        if (completed) completed = hold(publisher, command, initial, last_arm, last_yaw);
        if (completed) {
            const Snapshot actual = snapshot();
            if (!ready(actual)) completed = false;
            else {
                const standing_motion::Waypoint home{2.0, initial.arm};
                const standing_motion::Plan back = standing_motion::make_plan(
                    actual.arm, actual.yaw, initial.yaw, {home});
                last_arm = actual.arm;
                last_yaw = actual.yaw;
                std::cout << "Returning to startup pose, " << back.total_duration << " s.\n";
                completed = execute(publisher, command, initial, back, last_arm, last_yaw);
            }
        }
        if (!completed) std::cerr << "Stopped: input, stale state, or invalid feedback.\n";
        ramp_down(publisher, command, initial, last_arm, last_yaw, current_weight);
        std::cout << "Released arm_sdk.\n";
        return completed ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << "\n";
        return 1;
    }
}
