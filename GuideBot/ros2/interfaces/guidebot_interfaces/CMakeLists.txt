cmake_minimum_required(VERSION 3.8)
project(guidebot_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Anchor.msg" "msg/TextUnit.msg" "msg/SceneTarget.msg" "msg/ActionPlan.msg"
  "msg/InteractionContext.msg" "msg/ConversationInput.msg" "msg/GestureEvent.msg"
  "msg/PlanningInput.msg" "msg/MotionState.msg" "msg/Transcript.msg"
  "srv/SessionControl.srv" "action/PlanGestures.action" "action/ExecuteGesture.action")
ament_export_dependencies(rosidl_default_runtime)
ament_package()
