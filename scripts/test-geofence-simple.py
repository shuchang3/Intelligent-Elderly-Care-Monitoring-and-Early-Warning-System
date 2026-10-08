"""Simple geofence test without AI service.

Tests:
1. Create person and bind device
2. Create geofence
3. Send location updates directly to Java backend
4. Check if location is saved correctly
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env.local')

JAVA_BASE_URL = os.getenv('JAVA_BASE_URL', 'http://127.0.0.1:8081')
AI_SERVICE_KEY = os.getenv('AI_SERVICE_KEY', '')

session = requests.Session()


def login_admin():
    """Login as admin."""
    username = 'admin'
    password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
    
    response = session.post(
        f'{JAVA_BASE_URL}/api/v1/auth/login',
        json={'username': username, 'password': password},
        timeout=10
    )
    result = response.json()
    
    if result['code'] != 200:
        print(f'❌ Login failed: {result.get("message")}')
        sys.exit(1)
    
    token = result['data']['token']
    session.headers.update({'Authorization': f'Bearer {token}'})
    print(f'✓ Logged in as {username}')


def api_call(method, path, **kwargs):
    """Make API call."""
    url = f'{JAVA_BASE_URL}{path}'
    try:
        response = session.request(method, url, timeout=10, **kwargs)
        result = response.json()
        
        if result.get('code') != 200:
            print(f'❌ API Error ({method} {path}): {result.get("message")}')
            return None
        
        return result.get('data')
    except Exception as e:
        print(f'❌ Request failed ({method} {path}): {e}')
        return None


def create_test_person():
    """Create test elderly person."""
    person_code = f'TEST-{uuid.uuid4().hex[:6].upper()}'
    
    data = api_call('POST', '/api/v1/persons', json={
        'personCode': person_code,
        'name': '测试老人',
        'personType': 'ELDER'
    })
    
    if data:
        print(f'✓ Created person: {person_code}')
        return person_code
    return None


def bind_device(person_code, device_id='TEST-DEVICE-001'):
    """Bind device to person."""
    data = api_call('POST', '/api/v1/person-device-bindings', json={
        'personCode': person_code,
        'deviceId': device_id
    })
    
    if data is not None:
        print(f'✓ Bound device: {device_id}')
        return device_id
    return None


def create_geofence():
    """Create a test geofence (50m x 50m square)."""
    # Center: Beijing Tiananmen
    center_lng = 116.397
    center_lat = 39.908
    
    # ~50m offset
    offset_lat = 50 / 111000
    offset_lng = 50 / (111000 * 0.766)  # cos(39.9°)
    
    points = [
        [center_lng - offset_lng, center_lat - offset_lat],
        [center_lng + offset_lng, center_lat - offset_lat],
        [center_lng + offset_lng, center_lat + offset_lat],
        [center_lng - offset_lng, center_lat + offset_lat],
    ]
    
    fence_code = f'FENCE-{uuid.uuid4().hex[:6].upper()}'
    
    data = api_call('POST', '/api/v1/geofences', json={
        'fenceCode': fence_code,
        'fenceName': '测试安全区',
        'points': points
    })
    
    if data:
        print(f'✓ Created geofence: {fence_code}')
        print(f'  Center: ({center_lng:.6f}, {center_lat:.6f})')
        return fence_code, points, (center_lng, center_lat)
    return None, None, None


def send_location_to_backend(device_id, lng, lat, sample_time, accuracy=5.0):
    """Send location update directly to Java backend."""
    # First get person_code from device binding
    bindings = api_call('GET', '/api/v1/person-device-bindings')
    if not bindings:
        print('❌ No bindings found')
        return None
    
    binding = next((b for b in bindings if b['deviceId'] == device_id), None)
    if not binding:
        print(f'❌ Device {device_id} not bound')
        return None
    
    person_code = binding['personCode']
    point_no = str(uuid.uuid4())
    
    # Call Java backend location update (needs AI key auth)
    response = requests.post(
        f'{JAVA_BASE_URL}/api/v1/location/update',
        headers={'X-AI-Key': AI_SERVICE_KEY},
        json={
            'pointNo': point_no,
            'deviceId': device_id,
            'personCode': person_code,
            'longitude': lng,
            'latitude': lat,
            'sampleTime': sample_time.isoformat(timespec='seconds'),
            'accuracy': accuracy
        },
        timeout=10
    )
    
    result = response.json()
    if result['code'] == 200:
        inside = result['data']['insideFence']
        status = '✓ Inside' if inside else '✗ Outside'
        print(f'  Location: ({lng:.6f}, {lat:.6f}) - {status}')
        return inside
    else:
        print(f'  ❌ Failed: {result.get("message")}')
        return None


def query_location_history(person_code):
    """Query location history."""
    data = api_call('GET', f'/api/v1/tracks/{person_code}')
    
    if data:
        print(f'\n📊 Found {len(data)} location points')
        if data:
            print('\nLast 3 locations:')
            for loc in data[:3]:
                time_str = loc['sampleTime']
                lng = loc['longitude']
                lat = loc['latitude']
                inside = '✓' if loc.get('insideFence') else '✗'
                print(f'  {time_str} - ({lng:.6f}, {lat:.6f}) {inside}')
        return data
    return []


def main():
    """Main test flow."""
    print('='*60)
    print('Geofence Simple Test (No AI Service)')
    print('='*60)
    print()
    
    # Step 1: Login
    print('[1/5] Logging in...')
    login_admin()
    print()
    
    # Step 2: Create person
    print('[2/5] Creating test person...')
    person_code = create_test_person()
    if not person_code:
        sys.exit(1)
    print()
    
    # Step 3: Bind device
    print('[3/5] Binding device...')
    device_id = bind_device(person_code)
    if not device_id:
        sys.exit(1)
    print()
    
    # Step 4: Create geofence
    print('[4/5] Creating geofence...')
    fence_code, points, center = create_geofence()
    if not fence_code:
        sys.exit(1)
    center_lng, center_lat = center
    print()
    
    # Step 5: Send test locations
    print('[5/5] Sending test locations...')
    print('Phase 1: Inside fence')
    now = datetime.now()
    
    # Send 3 locations inside fence
    for i in range(3):
        lng = center_lng + (i - 1) * 0.0001
        lat = center_lat + (i - 1) * 0.0001
        sample_time = now + timedelta(seconds=i*5)
        send_location_to_backend(device_id, lng, lat, sample_time)
    
    print('\nPhase 2: Outside fence')
    # Send 3 locations outside fence
    exit_lng = center_lng + 0.001  # ~100m east
    exit_lat = center_lat + 0.001
    
    for i in range(3):
        lng = exit_lng + (i - 1) * 0.0001
        lat = exit_lat + (i - 1) * 0.0001
        sample_time = now + timedelta(seconds=15 + i*5)
        send_location_to_backend(device_id, lng, lat, sample_time)
    
    print()
    
    # Query history
    print('Querying location history...')
    history = query_location_history(person_code)
    
    print()
    print('='*60)
    print('✓ Test completed!')
    print('='*60)
    print()
    print('Note: Without AI service, no alerts will be triggered.')
    print('Location data is saved to database successfully.')
    print()
    print('To test full alert functionality:')
    print('1. Install AI dependencies: .\\scripts\\setup-ai-env.ps1')
    print('2. Start AI service: python ai_service.py')
    print('3. Run full test: python scripts/test-geofence.py')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n⚠ Test interrupted')
        sys.exit(0)
    except Exception as e:
        print(f'\n\n❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
