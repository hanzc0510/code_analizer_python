import sys
sys.path.insert(0, '.')
import uvicorn
import threading
import requests
import time

def run_server():
    uvicorn.run('web.main:app', host="127.0.0.1", port=8888, log_level="error")

thread = threading.Thread(target=run_server, daemon=True)
thread.start()

time.sleep(4)

print("Testing Chat API...")
resp = requests.post('http://127.0.0.1:8888/api/Dapper-main/chat', json={
    'project_name': 'Dapper-main',
    'message': 'query方法',
    'history': []
}, timeout=120)
print(f"Chat Status: {resp.status_code}")
if resp.status_code == 200:
    print("SUCCESS!")
    data = resp.json()
    print(f"  Answer length: {len(data['answer'])}")
    print(f"  Snippets: {len(data['context_used']['snippets'])}")
else:
    print(resp.text[:200])

print("\nTesting Code browse API...")
resp = requests.get('http://127.0.0.1:8888/api/Dapper-main/code/Dapper/SqlMapper.cs')
print(f"Code Status: {resp.status_code}")
if resp.status_code == 200:
    print(f"  Total lines: {resp.json()['total_lines']}")

print("\nAll tests passed! Server is running. Press Ctrl+C to stop.")
while True:
    time.sleep(1)
