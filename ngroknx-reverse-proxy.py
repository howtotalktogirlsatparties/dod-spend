#!/usr/bin/env python3

import os
import subprocess
import time
import sys
import logging
import json
import signal
from typing import Optional
import atexit

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def check_dependencies():
    for cmd in ["nginx", "ngrok"]:
        if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            logging.error(f"{cmd} is not installed")
            sys.exit(1)

def start_local_server() -> Optional[subprocess.Popen]:
    logging.info(f"Starting local server on port {LOCAL_PORT}")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(LOCAL_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        time.sleep(1)
        if process.poll() is not None:
            logging.error("Local server failed to start")
            return None
        return process
    except Exception as e:
        logging.error(f"Failed to start local server: {e}")
        return None

def write_nginx_config():
    try:
        os.makedirs(NGINX_CONF_DIR, exist_ok=True)
        with open(NGINX_CONF_FILE, "w") as f:
            f.write(NGINX_CONFIG)
        logging.info(f"Nginx config written to {NGINX_CONF_FILE}")
    except Exception as e:
        logging.error(f"Failed to write Nginx config: {e}")
        sys.exit(1)

def start_nginx():
    logging.info("Testing Nginx configuration")
    try:
        result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        if result.returncode != 0:
            logging.error("Nginx config test failed:")
            logging.error(result.stderr)
            sys.exit(1)
        logging.info("Starting/reloading Nginx")
        subprocess.run(["nginx", "-s", "reload"], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to reload Nginx: {e}")
        sys.exit(1)

def start_ngrok() -> Optional[subprocess.Popen]:
    logging.info(f"Starting ngrok on port {NGROK_PORT}")
    try:
        process = subprocess.Popen(
            ["ngrok", "http", str(NGROK_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        time.sleep(3)
        for _ in range(5):
            ngrok_output = subprocess.run(
                ["curl", "-s", "http://localhost:4040/api/tunnels"],
                capture_output=True, text=True
            )
            if ngrok_output.returncode == 0:
                tunnels = json.loads(ngrok_output.stdout).get("tunnels", [])
                for tunnel in tunnels:
                    if tunnel["proto"] == "https":
                        logging.info(f"ngrok public URL: {tunnel['public_url']}")
                        return process
            time.sleep(1)
        logging.warning("Failed to get ngrok URL after retries")
        return process
    except Exception as e:
        logging.error(f"Failed to start ngrok: {e}")
        return None

def cleanup(processes: list[subprocess.Popen]):
    for process in processes:
        if process and process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    subprocess.run(["nginx", "-s", "stop"], capture_output=True)

if __name__ == "__main__":
    check_dependencies()
    processes = []
    
    server_process = start_local_server()
    if server_process:
        processes.append(server_process)
    else:
        sys.exit(1)
    
    write_nginx_config()
    start_nginx()
    
    ngrok_process = start_ngrok()
    if ngrok_process:
        processes.append(ngrok_process)
    
    atexit.register(cleanup, processes)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down")
        cleanup(processes)
