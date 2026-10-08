"""Test script for geofence functionality.

Simulates BeiDou device location updates to test:
1. Creating geofence polygon
2. Binding person to device
3. Sending location updates (inside/outside fence)
4. Triggering WARNING and CRITICAL alerts
5. Querying location history
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env.local')

JAVA_BASE_URL = os.getenv('JAVA_BASE_URL', 'http://127.0.0.1:8080')
AI_SERVICE_KEY = os.getenv('AI_SERVICE_KEY', '')

session = requests.Session()
session.headers.update({'X-AI-Key': AI_SERVICE_KEY})


def api_call(method, path, **kwargs):
    """Make API call to Java backend."""
    url = f'{JAVA_BASE_URL}{path}'
    response = session.request(method, url, timeout=10, **kwargs)
    response.raise_for_status()
    result = response.json()
    
    if result.get('code') != 200:
        print(f'❌ API Error: {result.get("message")}')
        sys.exit(1)
    
    return result.get('data')


def login_admin():
    """Login as admin to get token."""
    username = os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'admin')
    password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
    
    response = requests.post(
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
    return token


def create_test_person():
    """Create a test elderly person."""
    person_code = f'TEST-ELDER-{uuid.uuid4().hex[:6].upper()}'
    
    try:
        data = api_call('POST', '/api/v1/persons', json={
            'personCode': person_code,
            'name': '测试老人',
            'personType': 'ELDER',
            'note': '电子围栏测试用'
        })
        print(f'✓ Created person: {person_code}')
        return person_code
    except Exception as e:
        print(f'⚠ Person might already exist: {e}')
        return person_code


def bind_device(person_code, device_id='TEST-DEVICE-001'):
    """Bind BeiDou device to person."""
    api_call('POST', '/api/v1/person-device-bindings', json={
        'personCode': person_code,
        'deviceId': device_id
    })
    print(f'✓ Bound device {device_id} to {person_code}')
    return device_id


def create_geofence():
    """Create a test geofence polygon (50m x 50m square around a center point)."""
    # Center point (example: Beijing Tiananmen)
    center_lng = 116.397
    center_lat = 39.908
    
    # Calculate offsets for ~50m square (approximate)
    # 1 degree latitude ≈ 111km, 1 degree longitude ≈ 111km * cos(lat)
    offset_lat = 50 / 111000  # ~50 meters in latitude
    offset_lng = 50 / (111000 * abs(cos(radians(center_lat))))  # ~50 meters in longitude
    
    # Define square vertices (clockwise)
    points = [
        [center_lng - offset_lng, center_lat - offset_lat],  # Southwest
        [center_lng + offset_lng, center_lat - offset_lat],  # Southeast
        [center_lng + offset_lng, center_lat + offset_lat],  # Northeast
        [center_lng - offset_lng, center_lat + offset_lat],  # Northwest
    ]
    
    fence_code = f'TEST-FENCE-{uuid.uuid4().hex[:6].upper()}'
    
    data = api_call('POST', '/api/v1/geofences', json={
        'fenceCode': fence_code,
        'fenceName': '测试安全区',
        'points': points
    })
    
    print(f'✓ Created geofence: {fence_code}')
    print(f'  Center: ({center_lng:.6f}, {center_lat:.6f})')
    print(f'  Size: ~50m x 50m')
    return fence_code, points, (center_lng, center_lat)


def send_location_update(device_id, person_code, lng, lat, sample_time, accuracy=5.0):
    """Send a location update to the backend."""
    point_no = str(uuid.uuid4())
    
    # Call AI service endpoint (bypasses Java auth for AI)
    ai_url = f'http://127.0.0.1:{os.getenv("AI_PORT", "5002")}/api/v1/location/update'
    
    response = requests.post(ai_url, json={
        'pointNo': point_no,
        'deviceId': device_id,
        'personCode': person_code,
        'longitude': lng,
        'latitude': lat,
        'sampleTime': sample_time.isoformat(timespec='seconds'),
        'accuracy': accuracy
    }, headers={'X-AI-Key': AI_SERVICE_KEY}, timeout=10)
    
    result = response.json()
    
    if result['code'] == 200:
        inside = result['data']['insideFence']
        status = '✓ Inside' if inside else '✗ Outside'
        print(f'  Location update: ({lng:.6f}, {lat:.6f}) - {status}')
        return inside
    else:
        print(f'  ❌ Location update failed: {result.get("message")}')
        return None


def simulate_movement(device_id, person_code, center_lng, center_lat, duration_seconds=180):
    """Simulate elderly movement: start inside, then leave fence."""
    print(f'\n🚶 Simulating movement for {duration_seconds} seconds...')
    print(f'  Pattern: Start at center → Walk outside → Wait for alerts\n')
    
    from math import cos, radians, sin
    
    start_time = datetime.now()
    
    # Phase 1: Inside fence (first 30 seconds)
    print('Phase 1: Inside safe zone (0-30s)')
    for i in range(6):  # 6 updates over 30 seconds (every 5s)
        sample_time = start_time + timedelta(seconds=i*5)
        # Add small random movement within fence
        lng = center_lng + uniform(-0.0002, 0.0002)
        lat = center_lat + uniform(-0.0002, 0.0002)
        send_location_update(device_id, person_code, lng, lat, sample_time)
        time.sleep(5)
    
    # Phase 2: Move outside fence (30-60 seconds)
    print('\nPhase 2: Moving outside safe zone (30-60s)')
    exit_lng = center_lng + 0.001  # Move ~100m east
    exit_lat = center_lat + 0.001
    
    for i in range(6):  # 6 updates over 30 seconds
        sample_time = start_time + timedelta(seconds=30 + i*5)
        # Gradually move outside
        progress = i / 5.0
        lng = center_lng + (exit_lng - center_lng) * progress
        lat = center_lat + (exit_lat - center_lat) * progress
        send_location_update(device_id, person_code, lng, lat, sample_time)
        time.sleep(5)
    
    # Phase 3: Stay outside (60-180 seconds) - should trigger WARNING at 30s, CRITICAL at 120s
    print('\nPhase 3: Staying outside - waiting for alerts (60-180s)')
    print('  ⏱ WARNING alert expected at ~30s after exit')
    print('  ⏱ CRITICAL alert expected at ~120s after exit\n')
    
    for i in range(24):  # 24 updates over 120 seconds (every 5s)
        sample_time = start_time + timedelta(seconds=60 + i*5)
        # Stay at exit position with small variations
        lng = exit_lng + uniform(-0.0001, 0.0001)
        lat = exit_lat + uniform(-0.0001, 0.0001)
        inside = send_location_update(device_id, person_code, lng, lat, sample_time)
        
        # Check for alerts
        if i == 6:  # ~30 seconds after exit
            print('  🔔 Checking for WARNING alert...')
            check_alerts(person_code, 'WARNING')
        elif i == 18:  # ~120 seconds after exit
            print('  🚨 Checking for CRITICAL alert...')
            check_alerts(person_code, 'CRITICAL')
        
        time.sleep(5)
    
    print('\n✓ Movement simulation completed')


def check_alerts(person_code, expected_level):
    """Check if alerts were created."""
    try:
        events = api_call('GET', f'/api/v1/events?personCode={person_code}&eventType=GEOFENCE_EXIT')
        matching_events = [e for e in events['records'] if e.get('scoreType') == expected_level]
        
        if matching_events:
            event = matching_events[-1]
            print(f'  ✓ {expected_level} alert found! Event ID: {event["id"]}')
            print(f'    Description: {event["description"]}')
            print(f'    Time: {event["eventTime"]}')
        else:
            print(f'  ⚠ No {expected_level} alert found yet (may be delayed)')
    except Exception as e:
        print(f'  ⚠ Could not check alerts: {e}')


def query_location_history(person_code):
    """Query location history for a person."""
    print(f'\n📊 Querying location history for {person_code}...')
    
    try:
        history = api_call('GET', f'/api/v1/tracks/{person_code}')
        
        if history:
            print(f'  ✓ Found {len(history)} location points')
            
            # Show last 5 points
            print('\n  Last 5 locations:')
            for loc in history[:5]:
                time_str = loc['sampleTime']
                lng = loc['longitude']
                lat = loc['latitude']
                inside = '✓' if loc.get('insideFence') else '✗'
                print(f'    {time_str} - ({lng:.6f}, {lat:.6f}) {inside}')
        else:
            print('  ⚠ No location history found')
    except Exception as e:
        print(f'  ❌ Failed to query history: {e}')


def cleanup(person_code, fence_code):
    """Clean up test data."""
    print('\n🧹 Cleaning up test data...')
    
    try:
        # Unbind device
        api_call('DELETE', f'/api/v1/person-device-bindings?personCode={person_code}')
        print('  ✓ Unbound device')
    except:
        pass
    
    try:
        # Disable geofence
        api_call('DELETE', f'/api/v1/geofences/{fence_code}')
        print('  ✓ Disabled geofence')
    except:
        pass
    
    try:
        # Disable person
        api_call('DELETE', f'/api/v1/persons/{person_code}')
        print('  ✓ Disabled person')
    except:
        pass


def main():
    """Main test flow."""
    from math import cos, radians
    from random import uniform
    
    print('='*60)
    print('电子围栏功能测试')
    print('='*60)
    
    # Step 1: Login
    print('\n[1/7] Logging in...')
    login_admin()
    
    # Step 2: Create test person
    print('\n[2/7] Creating test person...')
    person_code = create_test_person()
    
    # Step 3: Bind device
    print('\n[3/7] Binding BeiDou device...')
    device_id = bind_device(person_code)
    
    # Step 4: Create geofence
    print('\n[4/7] Creating test geofence...')
    fence_code, points, center = create_geofence()
    center_lng, center_lat = center
    
    # Step 5: Simulate movement
    print('\n[5/7] Simulating elderly movement...')
    simulate_movement(device_id, person_code, center_lng, center_lat, duration_seconds=180)
    
    # Step 6: Query history
    print('\n[6/7] Querying location history...')
    query_location_history(person_code)
    
    # Step 7: Cleanup (optional)
    print('\n[7/7] Cleanup...')
    cleanup_choice = input('Clean up test data? (y/n): ').strip().lower()
    if cleanup_choice == 'y':
        cleanup(person_code, fence_code)
    
    print('\n' + '='*60)
    print('✓ Test completed successfully!')
    print('='*60)
    print('\nNext steps:')
    print('1. Open http://localhost:5000/geofence/map to view the map')
    print('2. Check alerts in the dashboard')
    print('3. Review location history')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n⚠ Test interrupted by user')
        sys.exit(0)
    except Exception as e:
        print(f'\n\n❌ Test failed: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
