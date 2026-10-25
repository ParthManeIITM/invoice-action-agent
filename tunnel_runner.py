#!/usr/bin/env python3
"""
Automated Tunnel & Server Runner for Invoice Action Agent.
Launches the local FastAPI A2A server and exposes it via a secure public HTTPS Cloudflare Tunnel.
"""

import os
import sys
import time
import re
import signal
import subprocess

PORT = 8000
CLOUDFLARED_BIN = "/Users/parthmane/.gemini/antigravity/scratch/cloudflared"

def main():
    print("=" * 70)
    print("🚀 Starting A2A 1.0 Invoice Action Agent & Cloudflare Tunnel...")
    print("=" * 70)

    # 1. Start Uvicorn Server
    server_cmd = [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(PORT)]
    server_proc = subprocess.Popen(
        server_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    time.sleep(2)

    # 2. Start Cloudflared Tunnel
    tunnel_cmd = [CLOUDFLARED_BIN, "tunnel", "--url", f"http://127.0.0.1:{PORT}"]
    tunnel_proc = subprocess.Popen(
        tunnel_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    public_url = None
    start_time = time.time()

    try:
        # Read tunnel output to detect public URL
        while time.time() - start_time < 30:
            line = tunnel_proc.stdout.readline()
            if not line:
                break
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if match:
                public_url = match.group(0)
                break

        if public_url:
            base_url = f"{public_url}/a2a/"
            print("\n" + "=" * 70)
            print("✅ SERVICE IS LIVE & PUBLIC!")
            print("=" * 70)
            print(f"📡 Public Base URL:     {base_url}")
            print(f"🔍 Agent Card URL:      {public_url}/.well-known/agent-card.json")
            print(f"💓 Health Check:        {public_url}/health")
            print("=" * 70)
            print("\n📋 SUBMISSION INSTRUCTIONS:")
            print("Copy and paste this URL into your grader's 'A2A interface base URL' box:")
            print(f"\n   👉   {base_url}   👈\n")
            print("Keep this terminal window running while the grader runs its checks.")
            print("Press Ctrl+C to stop the agent and close the tunnel.\n" + "=" * 70)

            # Keep running until interrupted
            while True:
                time.sleep(1)
        else:
            print("❌ Failed to obtain Cloudflare Tunnel URL within 30 seconds.")
            tunnel_proc.terminate()
            server_proc.terminate()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server and tunnel...")
    finally:
        tunnel_proc.terminate()
        server_proc.terminate()
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    main()
