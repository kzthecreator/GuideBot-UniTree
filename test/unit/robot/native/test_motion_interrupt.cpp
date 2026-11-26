#include "motion_interrupt.hpp"

#include <cmath>
#include <stdexcept>

void require(bool value) {
    if (!value) throw std::runtime_error("motion interrupt test failed");
}

action_sequence::Resolved action(double target) {
    action_sequence::Resolved result;
    result.request.label = "guide";
    result.phase_end = {{1, 2, 3, 4}};
    for (int i = 1; i <= 4; ++i) {
        standing_motion::ArmPose pose{};
        pose[0] = target * i / 4;
        result.waypoints.push_back({1.0, pose});
    }
    return result;
}

int main() {
    standing_motion::ArmPose initial{};
    motion_interrupt::Player player(initial);
    player.start(action(0.4));
    player.tick(1.3);
    player.interrupt();
    require(player.state() == motion_interrupt::State::Braking);
    const double before = player.pose()[0];
    require(player.brake_duration() < 5.0);
    player.tick(player.brake_duration());
    require(player.state() == motion_interrupt::State::Paused);
    require(player.pose()[0] >= before);
    const auto checkpoint = player.checkpoint();
    require(checkpoint.phase == 1 && checkpoint.waypoint == 1);
    const double held = player.pose()[0];
    player.tick(1.0);
    require(player.pose()[0] == held);
    player.answer(action(-0.1));
    player.tick(20.0);
    require(player.state() == motion_interrupt::State::Paused);
    require(player.checkpoint().waypoint == checkpoint.waypoint);
    player.resume();
    player.tick(1.0);
    player.interrupt();
    require(player.brake_duration() < 5.0);
    player.tick(player.brake_duration());
    require(player.has_checkpoint());
    require(player.checkpoint().phase >= checkpoint.phase);
    player.resume();
    player.tick(30.0);
    require(player.state() == motion_interrupt::State::Idle);
    require(std::abs(player.pose()[0] - 0.4) < 1e-9);
    auto linear = action(0.2);
    for (auto& waypoint : linear.waypoints)
        waypoint.interpolation = standing_motion::Interpolation::PlayLinear;
    player.start(linear);
    player.tick(0.3);
    const double linear_before = player.pose()[0];
    player.cancel();
    player.tick(0.001);
    require(std::abs(player.pose()[0] - linear_before) < 0.001);
    player.tick(player.brake_duration());
    require(player.state() == motion_interrupt::State::Idle);
    require(player.pose()[0] <= linear_before);

    player.reset_idle_pose(initial);
    auto original = action(1.8);
    original.play_style_preview = true;
    for (auto& waypoint : original.waypoints) {
        waypoint.interpolation = standing_motion::Interpolation::PlayLinear;
        waypoint.requested_duration = 0.3;
    }
    player.start(original);
    player.tick(0.4);
    const double stopped_pose = player.pose()[0];
    player.cancel();
    require(player.state() == motion_interrupt::State::Idle);
    player.tick(1.0);
    require(player.pose()[0] == stopped_pose);
    const auto retract = standing_motion::make_plan(
        player.pose(), 0, 0, player.preview_return_waypoints());
    require(std::abs(retract.total_duration - 0.4) < 1e-9);
    require(std::abs(standing_motion::sample(retract, 0).arm[0] - stopped_pose) < 1e-9);
    require(std::abs(standing_motion::sample(retract, 0.4).arm[0]) < 1e-9);

    player.start(action(0.2));
    player.tick(0.4);
    player.cancel();
    require(player.brake_duration() < 5.0);
    player.tick(player.brake_duration());
    require(player.state() == motion_interrupt::State::Idle);
    require(!player.has_checkpoint());
    player.start(action(0.2));
    player.tick(0.4);
    player.interrupt();
    player.cancel();
    require(player.state() == motion_interrupt::State::Braking);
    require(player.brake_duration() < 5.0);
    player.tick(player.brake_duration());
    require(player.state() == motion_interrupt::State::Idle);
    return 0;
}
