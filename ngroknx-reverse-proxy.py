#!/usr/bin/env python3

import os
import subprocess
import time
import sys

LOCAL_PORT = 8000
NGINX_PORT = 8080
NGROK_PORT = NGINX_PORT
NGINX_CONF_DIR = "/usr/local/etc/nginx/servers"
NGINX_CONF_FILE = os.path.join(NGINX_CONF_DIR, "reverse_proxy.conf")

NGINX_CONFIG = f"""
server {{
    listen {NGINX_PORT};
    server_name localhost;

    location / {{
        proxy_pass http://127.0.0.1:{LOCAL_PORT};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""

def check_dependencies():
    for cmd in ["nginx", "ngrok"]:
        if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            print(f"Error: {cmd} is not installed.")
            sys.exit(1)

def start_local_server():
    print(f"Starting local server on port {LOCAL_PORT}...")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(LOCAL_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)
    return server_process

def write_nginx_config():
    os.makedirs(NGINX_CONF_DIR, exist_ok=True)
    with open(NGINX_CONF_FILE, "w") as f:
        f.write(NGINX_CONFIG)
    print(f"Nginx config written to {NGINX_CONF_FILE}")

def start_nginx():
    print("Testing Nginx configuration...")
    result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Nginx config test failed:")
        print(result.stderr)
        sys.exit(1)
    print("Starting/reloading Nginx...")
    subprocess.run(["nginx", "-s", "reload"], check=True)

def start_ngrok():
    print(f"Starting ngrok on port {NGROK_PORT}...")
    ngrok_process = subprocess.Popen(
        ["ngrok", "http", str(NGROK_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(3)
    ngrok_output = subprocess.run(
        ["curl", "-s", "http://localhost:4040/api/tunnels"],
        capture_output=True, text=True
    )
    if ngrok_output.returncode == 0:
        import json
        tunnels = json.loads(ngrok_output.stdout).get("tunnels", [])
        for tunnel in tunnels:
            if tunnel["proto"] == "https":
                print(f"ngrok public URL: {tunnel['public_url']}")
                return ngrok_process
    print("Failed to get ngrok URL.")
    return ngrok_process

if __name__ == "__main__":
    check_dependencies()
    server_process = start_local_server()
    write_nginx_config()
    start_nginx()
    ngrok_process = start_ngrok()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        server_process.terminate()
        ngrok_process.terminate()
        subprocess.run(["nginx", "-s", "stop"])
