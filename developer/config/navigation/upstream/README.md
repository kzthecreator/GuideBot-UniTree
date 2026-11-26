# Upstream navigation configuration

Unmodified files from https://github.com/maxwellrobotics/g1-ros2 at
`ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff`, paths
`workspace/src/g1_navigation/config/{g1_navigation.rviz,localization.yaml}`.
BSD-3-Clause copyright/terms are preserved in LICENSE.

GuideBot generates a separate effective configuration for Foxy at runtime. It
replaces the simulator map and robot frames, uses Foxy's `omnidirectional` AMCL
model and PoseArray particle display, and disables displays for absent robot,
camera, manipulation and navigation-control topics. No upstream launch starts
simulators, learned gait, lowcmd, base_approach or a velocity writer here.
