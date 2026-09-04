#!/usr/bin/env python3
import http.server
import socketserver
import os
import json
import base64
import subprocess
import threading

# Lấy thư mục gốc hiện tại (nơi chứa script này, tức là ~/ros2_ws)
ROS2_WS = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(ROS2_WS, "start_pi5_robot.sh")
MAPS_DIR = os.path.join(ROS2_WS, "maps")

PORT = 5000

class RobotAPIHandler(http.server.SimpleHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        if self.path == '/api/robot/status':
            self._set_headers()
            # Check if start_pi5_robot.sh is running
            try:
                subprocess.check_output(["pgrep", "-f", "start_pi5_robot.sh"])
                status = "running"
            except subprocess.CalledProcessError:
                status = "stopped"
            
            # Try to infer mode by looking at processes
            mode = "unknown"
            try:
                subprocess.check_output(["pgrep", "-f", "slam_toolbox"])
                mode = "slam"
            except subprocess.CalledProcessError:
                try:
                    subprocess.check_output(["pgrep", "-f", "amcl|bt_navigator"])
                    mode = "amcl"
                except subprocess.CalledProcessError:
                    pass

            self.wfile.write(json.dumps({"status": status, "mode": mode}).encode('utf-8'))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""
        data = {}
        if post_data:
            try:
                data = json.loads(post_data.decode('utf-8'))
            except Exception:
                pass

        if self.path == '/api/robot/start':
            mode = data.get('mode', 'slam')
            print(f"Starting robot in mode: {mode}")
            
            # Kill existing gracefully first to allow ROS 2 to cleanup children
            os.system('pkill -INT -f "smb.launch.py" 2>/dev/null')
            os.system('sleep 2')
            
            # Force kill any lingering orphans
            os.system('pkill -9 -f "start_pi5_robot.sh" 2>/dev/null')
            os.system('pkill -9 -f "smb.launch.py" 2>/dev/null')
            os.system('pkill -9 -f "slam_toolbox" 2>/dev/null')
            os.system('pkill -9 -f "amcl" 2>/dev/null')
            os.system('pkill -9 -f "bt_navigator" 2>/dev/null')
            os.system('pkill -9 -f "rosbridge_server" 2>/dev/null')
            
            # Build command
            cmd = [SCRIPT_PATH]
            if mode == 'amcl':
                cmd.extend(['--no-slam', '--nav2'])
            elif mode == 'slam':
                cmd.extend(['--slam', '--nav2'])
                
            # Launch in background
            subprocess.Popen(cmd, cwd=ROS2_WS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            self._set_headers()
            self.wfile.write(json.dumps({"success": True, "mode": mode}).encode('utf-8'))

        elif self.path == '/api/robot/stop':
            print("Stopping robot...")
            os.system('pkill -9 -f "start_pi5_robot.sh" 2>/dev/null')
            os.system('pkill -9 -f "smb.launch.py" 2>/dev/null')
            os.system('pkill -9 -f "micro_ros_agent" 2>/dev/null')
            self._set_headers()
            self.wfile.write(json.dumps({"success": True}).encode('utf-8'))

        elif self.path == '/api/robot/upload_map':
            print("Uploading map to robot...")
            yaml_b64 = data.get('yaml_b64')
            pgm_b64 = data.get('pgm_b64')
            if not yaml_b64 or not pgm_b64:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing yaml_b64 or pgm_b64"}).encode('utf-8'))
                return
                
            os.makedirs(MAPS_DIR, exist_ok=True)
            try:
                with open(os.path.join(MAPS_DIR, 'active_map.yaml'), 'wb') as f:
                    f.write(base64.b64decode(yaml_b64))
                with open(os.path.join(MAPS_DIR, 'active_map.pgm'), 'wb') as f:
                    f.write(base64.b64decode(pgm_b64))
                self._set_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

        elif self.path == '/api/robot/save_map':
            print("Saving map from slam_toolbox...")
            os.makedirs(MAPS_DIR, exist_ok=True)
            
            # Use ROS 2 map_saver_cli
            save_cmd = f"source /opt/ros/lyrical/setup.bash && source {ROS2_WS}/install/setup.bash && ros2 run nav2_map_server map_saver_cli -f {MAPS_DIR}/active_map --ros-args -p map_subscribe_transient_local:=true -r __ns:=/"
            
            result = subprocess.run(save_cmd, shell=True, executable='/bin/bash', cwd=ROS2_WS, capture_output=True, text=True)
            if result.returncode != 0:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": "Failed to save map: " + result.stderr}).encode('utf-8'))
                return

            try:
                with open(os.path.join(MAPS_DIR, 'active_map.yaml'), 'rb') as f:
                    yaml_b64 = base64.b64encode(f.read()).decode('utf-8')
                with open(os.path.join(MAPS_DIR, 'active_map.pgm'), 'rb') as f:
                    pgm_b64 = base64.b64encode(f.read()).decode('utf-8')
                
                self._set_headers()
                self.wfile.write(json.dumps({"yaml_b64": yaml_b64, "pgm_b64": pgm_b64}).encode('utf-8'))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": "Error reading saved map: " + str(e)}).encode('utf-8'))

        elif self.path == '/api/robot/shutdown':
            print("Shutting down Raspberry Pi...")
            self._set_headers()
            self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            # Schedule shutdown in 1 second
            threading.Timer(1.0, lambda: os.system('sudo shutdown -h now')).start()

        else:
            self.send_error(404, "Not Found")

def run_server():
    os.makedirs(MAPS_DIR, exist_ok=True)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), RobotAPIHandler) as httpd:
        print(f"Robot Agent Server running on port {PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()
