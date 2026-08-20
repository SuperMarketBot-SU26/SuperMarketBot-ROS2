#!/usr/bin/env python3
import os
import subprocess
import json
import base64
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
                container_running = len(result.stdout.strip()) > 0
                
                status_str = "stopped"
                if container_running:
                    # Container is up, but is ROS 2 fully initialized?
                    # We check if rosbridge is up, since it's the last thing to launch
                    check_result = subprocess.run(
                        ['docker', 'exec', 'smb-ros2', 'bash', '-c', 'source /opt/ros/lyrical/setup.bash && ros2 node list'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    if b'rosbridge_websocket' in check_result.stdout:
                        status_str = "running"
                    else:
                        status_str = "starting"
                
                response = {"status": status_str}
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
                # Read payload to get mode
                content_length = int(self.headers.get('Content-Length', 0))
                mode = "slam"
                if content_length > 0:
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    mode = data.get("mode", "slam")

                ws_path = os.path.expanduser('~/ros2_ws')
                maps_dir = os.path.join(ws_path, 'maps')
                
                # Setup bash command based on mode
                bash_args = "./start_pi5_robot.sh"
                if mode == "amcl":
                    map_yaml = os.path.join(maps_dir, 'active_map.yaml')
                    if not os.path.exists(map_yaml):
                        response = {"error": "No map loaded on the Pi! Please upload a map first."}
                        self.wfile.write(json.dumps(response).encode('utf-8'))
                        return
                    # The path inside the docker container will be /ros2_ws/maps/active_map.yaml
                    bash_args += " --amcl --map /ros2_ws/maps/active_map.yaml"

                log_file = open(os.path.join(ws_path, 'smb_agent', 'robot_start.log'), 'w')
                
                # We name the container smb-ros2 so we can easily stop it and check status
                docker_cmd = f"docker run --rm -v {ws_path}:/ros2_ws --network host --privileged --name smb-ros2 supermarket-bot-ros2:latest bash -c 'cd /ros2_ws && source /opt/ros/lyrical/setup.bash && {bash_args}'"
                
                subprocess.Popen(docker_cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True)
                
                response = {"message": f"Robot OS starting in {mode.upper()} mode..."}
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                response = {"error": str(e)}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
        elif self.path == '/api/robot/upload_map':
            self._set_headers()
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                yaml_b64 = data.get("yaml_b64")
                pgm_b64 = data.get("pgm_b64")
                
                if not yaml_b64 or not pgm_b64:
                    raise ValueError("Missing yaml_b64 or pgm_b64 in payload")
                
                # Remove data URI prefix if present
                if "," in yaml_b64: yaml_b64 = yaml_b64.split(",")[1]
                if "," in pgm_b64: pgm_b64 = pgm_b64.split(",")[1]
                
                yaml_bytes = base64.b64decode(yaml_b64)
                pgm_bytes = base64.b64decode(pgm_b64)
                
                maps_dir = os.path.expanduser('~/ros2_ws/maps')
                os.makedirs(maps_dir, exist_ok=True)
                
                # HACK: overwrite the image name in the YAML to strictly match active_map.pgm
                yaml_str = yaml_bytes.decode('utf-8')
                new_yaml_lines = []
                for line in yaml_str.splitlines():
                    if line.startswith("image:"):
                        new_yaml_lines.append("image: active_map.pgm")
                    else:
                        new_yaml_lines.append(line)
                
                with open(os.path.join(maps_dir, 'active_map.yaml'), 'w') as f:
                    f.write("\n".join(new_yaml_lines))
                    
                with open(os.path.join(maps_dir, 'active_map.pgm'), 'wb') as f:
                    f.write(pgm_bytes)
                    
                response = {"message": "Map successfully uploaded and saved to Pi."}
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                response = {"error": f"Failed to upload map: {str(e)}"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
        elif self.path == '/api/robot/save_map':
            self._set_headers()
            try:
                # Execute the map saving script inside the running container
                # This saves directly to /ros2_ws/maps/active_map so it's ready for AMCL boot
                cmd = [
                    'docker', 'exec', 'smb-ros2', 'bash', '-c',
                    'source /opt/ros/lyrical/setup.bash && source /ros2_ws/install/setup.bash && python3 /ros2_ws/src/smb_robot_bringup/scripts/manage_map.py save -f /ros2_ws/maps/active_map'
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if result.returncode == 0:
                    response = {"message": "Map saved successfully as active_map!"}
                else:
                    response = {"error": f"Map save failed: {result.stderr.decode('utf-8')}"}
                
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
