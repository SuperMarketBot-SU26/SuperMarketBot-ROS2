#!/usr/bin/env python3
import os
import subprocess
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class RobotAgentHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS, POST')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-type")
        self.end_headers()
        
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/robot/status':
            self._set_headers()
            try:
                # Check if the named Docker container 'smb-ros2' is running
                result = subprocess.run(['docker', 'ps', '-q', '-f', 'name=smb-ros2'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                is_running = len(result.stdout.strip()) > 0
                
                response = {"status": "running" if is_running else "stopped"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                response = {"error": str(e)}
                self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/robot/start':
            self._set_headers()
            try:
                # Run the Docker container in the background without -it (no TTY in systemd)
                ws_path = os.path.expanduser('~/ros2_ws')
                log_file = open(os.path.join(ws_path, 'smb_agent', 'robot_start.log'), 'w')
                
                # We name the container smb-ros2 so we can easily stop it and check status
                docker_cmd = f"docker run --rm -v {ws_path}:/ros2_ws --network host --privileged --name smb-ros2 supermarket-bot-ros2:latest bash -c 'cd /ros2_ws && source /opt/ros/lyrical/setup.bash && ./start_pi5_robot.sh'"
                
                subprocess.Popen(docker_cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
                
                response = {"message": "Robot OS starting..."}
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                response = {"error": str(e)}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
        elif self.path == '/api/robot/stop':
            self._set_headers()
            try:
                # Forcefully remove the Docker container if it's running
                subprocess.run(['docker', 'rm', '-f', 'smb-ros2'], check=False)
                
                # Also run the stop script natively just in case there are lingering processes
                ws_path = os.path.expanduser('~/ros2_ws')
                script_path = os.path.join(ws_path, 'stop_pi5_robot.sh')
                subprocess.run(['bash', script_path], check=False)
                
                response = {"message": "Robot OS stopped successfully"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                response = {"error": str(e)}
                self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run(server_class=HTTPServer, handler_class=RobotAgentHandler, port=5000):
    server_address = ('0.0.0.0', port)
    httpd = server_class(server_address, handler_class)
    print(f'Starting Robot HTTP Agent on port {port}...')
    httpd.serve_forever()

if __name__ == "__main__":
    run()
