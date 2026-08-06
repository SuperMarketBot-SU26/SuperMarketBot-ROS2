import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
import math
import sys

def euler_from_quaternion(x, y, z, w):
    t3 = +2.0 * (w * z + x * y)
    t4 = +1.0 - 2.0 * (y * y + z * z)
    yaw_z = math.atan2(t3, t4)
    return yaw_z

class RotationDebugger(Node):
    def __init__(self):
        super().__init__('rotation_debugger')
        self.sub_odom = self.create_subscription(Odometry, '/odom_relay', self.odom_callback, 10)
        
        self.last_odom_yaw = None
        self.odom_accumulated = 0.0
        
        self.timer = self.create_timer(0.5, self.print_status)
        print("======================================================")
        print("                 ROTATION DEBUGGER                    ")
        print("======================================================")
        print("INSTRUCTIONS:")
        print("1. Leave the robot on the ground.")
        print("2. Pick it up and rotate it 90 degrees to the LEFT.")
        print("3. Watch the output below to diagnose the issue.")
        print("======================================================\n")

    def odom_callback(self, msg):
        q = msg.pose.pose.orientation
        yaw = euler_from_quaternion(q.x, q.y, q.z, q.w)
        if self.last_odom_yaw is not None:
            dyaw = yaw - self.last_odom_yaw
            # Handle wrap around
            if dyaw > math.pi: dyaw -= 2*math.pi
            elif dyaw < -math.pi: dyaw += 2*math.pi
            self.odom_accumulated += dyaw
        self.last_odom_yaw = yaw

    def print_status(self):
        if self.last_odom_yaw is None:
            return
            
        odom_deg = math.degrees(self.odom_accumulated)
        sys.stdout.write(f"\rTotal Odometry Rotation: {odom_deg:7.2f} degrees")
        sys.stdout.flush()
        
        if abs(odom_deg) > 45:
            print("\n\n--- DIAGNOSIS ---")
            if odom_deg < -20:
                print("❌ Your IMU is INVERTED!")
                print("   You physically turned LEFT (+), but Odometry went RIGHT (-).")
                print("   Fix: Change IMU_YAW_INVERTED to 1 in Config.h on the ESP32.")
            elif odom_deg > 20 and odom_deg < 75:
                print("❌ Your IMU Scale is WRONG!")
                print("   You turned 90 deg, but Odometry only registered a fraction of it.")
                print("   Fix: Check MPU6050 FS_SEL setting or Gyro calibration.")
            elif odom_deg > 75 and odom_deg < 105:
                print("✅ Your IMU and Odometry are WORKING PERFECTLY!")
                print("   The issue must be SLAM Toolbox params or timestamp lag.")
            elif odom_deg > 105:
                print("❌ Your IMU Scale is WRONG (Overshooting)!")
            print("-----------------\n")
            print("Press Ctrl+C to exit.")
            self.timer.cancel()

rclpy.init()
node = RotationDebugger()
try:
    rclpy.spin(node)
except KeyboardInterrupt:
    pass
rclpy.shutdown()
