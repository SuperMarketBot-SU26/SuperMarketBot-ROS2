# Nav2 Configuration Guidelines

- **Goal Tolerances**: When tuning goal tolerances (e.g., `xy_goal_tolerance`, `yaw_goal_tolerance`), ALWAYS modify the active goal checker plugin block (e.g., `general_goal_checker`), NOT the controller plugin block (e.g., `FollowPath`). Modifying the controller block will silently fail and cause end-of-path oscillations.
