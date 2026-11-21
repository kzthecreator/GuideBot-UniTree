cmake_minimum_required(VERSION 3.10)
project(g1_arm7_teach_play)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release)

if(NOT DEFINED UNITREE_SDK2_PATH)
    set(UNITREE_SDK2_PATH "/opt/unitree_robotics/unitree_sdk2")
endif()

include_directories(
    ${UNITREE_SDK2_PATH}/include
    ${UNITREE_SDK2_PATH}/include/ddscxx
    ${UNITREE_SDK2_PATH}/thirdparty/include
    ${UNITREE_SDK2_PATH}/thirdparty/include/ddscxx
)

link_directories(
    ${UNITREE_SDK2_PATH}/lib/${CMAKE_SYSTEM_PROCESSOR}
    ${UNITREE_SDK2_PATH}/thirdparty/lib/${CMAKE_SYSTEM_PROCESSOR}
)

set(UNITREE_LIBS unitree_sdk2 ddscxx ddsc pthread)

add_executable(teach teach.cpp)
target_link_libraries(teach ${UNITREE_LIBS})

add_executable(teach_with_name teach_with_name.cpp)
target_link_libraries(teach_with_name ${UNITREE_LIBS} crypto)

add_executable(demo_standing_waist_gesture demo_standing_waist_gesture.cpp)
target_link_libraries(demo_standing_waist_gesture ${UNITREE_LIBS})

enable_testing()
add_executable(test_standing_motion tests/test_standing_motion.cpp)
add_test(NAME standing_motion COMMAND test_standing_motion)

add_executable(test_action_sequence tests/test_action_sequence.cpp)
target_link_libraries(test_action_sequence crypto)
add_test(NAME action_sequence COMMAND test_action_sequence)

add_executable(test_motion_interrupt tests/test_motion_interrupt.cpp)
target_link_libraries(test_motion_interrupt crypto)
add_test(NAME motion_interrupt COMMAND test_motion_interrupt)

add_executable(test_sequence_library tests/test_sequence_library.cpp)
target_link_libraries(test_sequence_library crypto)
add_test(NAME sequence_library COMMAND test_sequence_library)

add_executable(motion_library_server motion_library_server.cpp)
target_link_libraries(motion_library_server ${UNITREE_LIBS} crypto)
