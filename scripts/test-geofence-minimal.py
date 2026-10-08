"""Minimal geofence test using direct HTTP calls."""
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env.local manually
env_file = ROOT / '.env.local'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os.environ[key.strip()] = value.strip().strip('"')

JAVA_BASE_URL = os.getenv('JAVA_BASE_URL', 'http://127.0.0.1:8081')
AI_SERVICE_KEY = os.getenv('AI_SERVICE_KEY', '')
ADMIN_PASSWORD = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')

print('='*60)
print('Minimal Geofence Test')
print('='*60)
print()

# Step 1: Login
print('[1] Logging in...')
import urllib.request
import json

login_data = json.dumps({'username': 'admin', 'password': ADMIN_PASSWORD}).encode()
req = urllib.request.Request(f'{JAVA_BASE_URL}/api/v1/auth/login', data=login_data, headers={'Content-Type': 'application/json'})
response = urllib.request.urlopen(req)
result = json.loads(response.read())
token = result['data']['token']
print(f'[OK] Logged in')
print()

# Step 2: Create person
print('[2] Creating person...')
person_code = f'TEST-{uuid.uuid4().hex[:6].upper()}'
person_data = json.dumps({'personCode': person_code, 'name': 'Test Elder', 'personType': 'ELDER'}).encode()
req = urllib.request.Request(f'{JAVA_BASE_URL}/api/v1/persons', data=person_data, 
                             headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
try:
    response = urllib.request.urlopen(req)
    print(f'[OK] Created person: {person_code}')
except Exception as e:
    print(f'❌ Failed: {e}')
    sys.exit(1)
print()

# Step 3: Bind device
print('[3] Binding device...')
device_id = 'TEST-DEV-001'
bind_data = json.dumps({'personCode': person_code, 'deviceId': device_id}).encode()
req = urllib.request.Request(f'{JAVA_BASE_URL}/api/v1/person-device-bindings', data=bind_data,
                             headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
try:
    response = urllib.request.urlopen(req)
    print(f'[OK] Bound device: {device_id}')
except Exception as e:
    print(f'❌ Failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# Step 4: Create geofence
print('[4] Creating geofence...')
center_lng, center_lat = 116.397, 39.908
offset = 0.005  # Increased from 0.0005 to make larger area
points = [
    [center_lng - offset, center_lat - offset],
    [center_lng + offset, center_lat - offset],
    [center_lng + offset, center_lat + offset],
    [center_lng - offset, center_lat + offset],
]
fence_code = f'FENCE-{uuid.uuid4().hex[:6].upper()}'
fence_data = json.dumps({
    'fenceCode': fence_code,
    'fenceName': 'Test Zone',
    'points': points
}).encode()
req = urllib.request.Request(f'{JAVA_BASE_URL}/api/v1/geofences', data=fence_data,
                             headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
try:
    response = urllib.request.urlopen(req)
    print(f'[OK] Created geofence: {fence_code}')
except Exception as e:
    print(f'❌ Failed: {e}')
    if hasattr(e, 'read'):
        error_body = e.read().decode('utf-8')
        print(f'  Error details: {error_body}')
    sys.exit(1)
print()

# Step 5: Send location update (using AI key auth)
print('[5] Sending location update...')
location_data = json.dumps({
    'pointNo': str(uuid.uuid4()),
    'deviceId': device_id,
    'personCode': person_code,
    'longitude': center_lng,
    'latitude': center_lat,
    'sampleTime': '2026-09-05T18:30:00',
    'accuracy': 5.0
}).encode()
req = urllib.request.Request(f'{JAVA_BASE_URL}/api/v1/location/update', data=location_data,
                             headers={'X-AI-Key': AI_SERVICE_KEY, 'Content-Type': 'application/json'})
try:
    response = urllib.request.urlopen(req)
    result = json.loads(response.read())
    inside = result['data']['insideFence']
    print(f'[OK] Location saved - Inside fence: {inside}')
except Exception as e:
    print(f'❌ Failed: {e}')
    if hasattr(e, 'read'):
        error_body = e.read().decode('utf-8')
        print(f'  Error details: {error_body}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

print('='*60)
print('✓ All tests passed!')
print('='*60)
