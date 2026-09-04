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
            # Check if docker container is running
            try:
                output = subprocess.check_output(["docker", "ps", "-q", "-f", "name=supermarket-bot-ros2"]).decode('utf-8').strip()
                status = "running" if output else "stopped"
            except subprocess.CalledProcessError:
                status = "stopped"
            
            # Try to infer mode by looking at processes inside docker
            mode = "unknown"
            if status == "running":
                import socket
                is_booted = False
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    try:
                        s.connect(('127.0.0.1', 9090))
                        is_booted = True
                    except Exception:
                        pass
                
                if not is_booted:
                    status = "starting"
                else:
                    try:
                        subprocess.check_output(["docker", "exec", "supermarket-bot-ros2", "pgrep", "-f", "slam_toolbox"])
                        mode = "slam"
                    except subprocess.CalledProcessError:
                        try:
                            subprocess.check_output(["docker", "exec", "supermarket-bot-ros2", "pgrep", "-f", "amcl|bt_navigator"])
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
            print(f"Starting robot in mode: {mode} (via Docker)")
            
            # Kill existing docker container
            os.system('docker stop supermarket-bot-ros2 2>/dev/null; docker rm supermarket-bot-ros2 2>/dev/null')
            
            # Build command for docker
            bash_cmd = "cd /ros2_ws && source /opt/ros/lyrical/setup.bash && ./start_pi5_robot.sh"
            if mode == 'amcl':
                bash_cmd += " --no-slam --nav2"
            elif mode == 'slam':
                bash_cmd += " --slam --nav2"
                
            cmd = ['docker', 'run', '-d', '--rm', '--name', 'supermarket-bot-ros2', '-v', f'{ROS2_WS}:/ros2_ws', '--network', 'host', '--privileged', 'supermarket-bot-ros2:latest', 'bash', '-c', bash_cmd]
            
            # Launch docker in background
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            self._set_headers()
            self.wfile.write(json.dumps({"success": True, "mode": mode}).encode('utf-8'))

        elif self.path == '/api/robot/stop':
            print("Stopping robot...")
            os.system('docker stop supermarket-bot-ros2 2>/dev/null; docker rm supermarket-bot-ros2 2>/dev/null')
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
