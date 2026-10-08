"""Geofence monitor for BeiDou RTK positioning data.

Monitors elderly location updates and triggers alerts when they leave
the configured safe zone. Supports two-level alert thresholds:
- WARNING: Left fence for 30-120 seconds
- CRITICAL: Left fence for >120 seconds
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

LOG = logging.getLogger(__name__)


class Point:
    """Geographic coordinate point."""
    def __init__(self, lng: float, lat: float):
        self.lng = lng
        self.lat = lat


class GeofenceMonitor:
    """Monitor elderly location and detect geofence violations."""
    
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.RLock()
        
        # Alert thresholds (seconds)
        self.WARNING_THRESHOLD = 30.0   # 30秒短暂离开
        self.CRITICAL_THRESHOLD = 120.0  # 2分钟长时间离开
        
        # Track fence exit times for each person
        # Format: {person_code: {'exit_time': timestamp, 'alert_level': None/'WARNING'/'CRITICAL'}}
        self.exit_tracker: Dict[str, dict] = {}
        
        # Current geofence configuration
        self.geofence: Optional[dict] = None
        
        # Monitoring thread
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the geofence monitoring thread."""
        self.thread = threading.Thread(target=self._monitor_loop, name='geofence-monitor', daemon=True)
        self.thread.start()
        LOG.info('Geofence monitor started')
    
    def stop(self):
        """Stop the geofence monitoring thread."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
        LOG.info('Geofence monitor stopped')
    
    def update_geofence(self, geofence_config: dict):
        """Update geofence configuration from backend."""
        with self.lock:
            self.geofence = geofence_config
            LOG.info(f'Geofence updated: {geofence_config.get("fenceName")}')
    
    def process_location_update(self, person_code: str, longitude: float, latitude: float, 
                                sample_time: str, device_id: str, accuracy: float = None):
        """Process a location update from BeiDou device.
        
        Args:
            person_code: Elderly person code
            longitude: Longitude coordinate
            latitude: Latitude coordinate
            sample_time: Sample timestamp (ISO format)
            device_id: BeiDou device ID
            accuracy: Positioning accuracy in meters
        """
        try:
            point = Point(longitude, latitude)
            inside = self._is_point_in_fence(point)
            
            now = time.monotonic()
            sample_dt = datetime.fromisoformat(sample_time)
            
            with self.lock:
                if inside:
                    # Person is inside fence - clear any exit tracking
                    if person_code in self.exit_tracker:
                        del self.exit_tracker[person_code]
                        LOG.info(f'{person_code} returned to safe zone')
                else:
                    # Person is outside fence
                    if person_code not in self.exit_tracker:
                        # First detection of exit
                        self.exit_tracker[person_code] = {
                            'exit_time': now,
                            'exit_datetime': sample_dt,
                            'alert_level': None,
                            'longitude': longitude,
                            'latitude': latitude
                        }
                        LOG.warning(f'{person_code} left safe zone at {sample_time}')
                    else:
                        # Update last known position outside fence
                        self.exit_tracker[person_code]['longitude'] = longitude
                        self.exit_tracker[person_code]['latitude'] = latitude
                        
                        # Check alert thresholds
                        elapsed = now - self.exit_tracker[person_code]['exit_time']
                        current_level = self.exit_tracker[person_code]['alert_level']
                        
                        if elapsed >= self.CRITICAL_THRESHOLD and current_level != 'CRITICAL':
                            # Trigger critical alert
                            self._trigger_alert(person_code, 'CRITICAL', sample_dt, longitude, latitude, device_id)
                            self.exit_tracker[person_code]['alert_level'] = 'CRITICAL'
                            
                        elif elapsed >= self.WARNING_THRESHOLD and current_level is None:
                            # Trigger warning alert
                            self._trigger_alert(person_code, 'WARNING', sample_dt, longitude, latitude, device_id)
                            self.exit_tracker[person_code]['alert_level'] = 'WARNING'
        
        except Exception as e:
            LOG.error(f'Error processing location update: {e}', exc_info=True)
    
    def _trigger_alert(self, person_code: str, level: str, sample_time: datetime,
                      longitude: float, latitude: float, device_id: str):
        """Trigger geofence exit alert to backend.
        
        Args:
            person_code: Elderly person code
            level: Alert level (WARNING/CRITICAL)
            sample_time: Time when exit was detected
            longitude: Last known longitude
            latitude: Last known latitude
            device_id: BeiDou device ID
        """
        event_no = str(uuid.uuid4())
        description = f"老人离开安全区 - {'长时间离开' if level == 'CRITICAL' else '短暂离开'}"
        
        # Create minimal JPEG image for alert (1x1 pixel)
        import io
        from PIL import Image
        img = Image.new('RGB', (1, 1), color='red')
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        snapshot_data = buf.getvalue()
        
        # Prepare event data
        event_data = {
            'eventNo': event_no,
            'eventType': 'GEOFENCE_EXIT',
            'cameraCode': 'GPS',  # Use GPS as virtual camera
            'personCode': person_code,
            'eventTime': sample_time.isoformat(timespec='seconds'),
            'description': description,
            'confidence': 1.0,
            'scoreType': level,  # Use scoreType to store alert level
            'location': f'{longitude:.6f},{latitude:.6f}'
        }
        
        # Enqueue event to outbox
        accepted = self.runtime.outbox.enqueue(
            '/api/v1/ai/events',
            event_data,
            snapshot_data,
            'snapshot'
        )
        
        if accepted:
            LOG.info(f'Geofence alert enqueued: {person_code} - {level}')
        else:
            LOG.warning(f'Failed to enqueue geofence alert: {person_code}')
    
    def _is_point_in_fence(self, point: Point) -> bool:
        """Check if a point is inside the configured geofence using ray casting algorithm.
        
        Args:
            point: Geographic point to check
            
        Returns:
            True if point is inside fence, False otherwise
        """
        with self.lock:
            if not self.geofence or not self.geofence.get('enabled'):
                return True  # No fence configured, consider always inside
            
            try:
                points_json = self.geofence.get('pointsJson', '[]')
                vertices = json.loads(points_json)
                
                if len(vertices) < 3:
                    return True
                
                # Ray casting algorithm
                n = len(vertices)
                inside = False
                
                j = n - 1
                for i in range(n):
                    xi, yi = vertices[i][0], vertices[i][1]  # lng, lat
                    xj, yj = vertices[j][0], vertices[j][1]
                    
                    if ((yi > point.lat) != (yj > point.lat)) and \
                       (point.lng < (xj - xi) * (point.lat - yi) / (yj - yi) + xi):
                        inside = not inside
                    
                    j = i
                
                return inside
            
            except Exception as e:
                LOG.error(f'Error checking point in fence: {e}')
                return True  # On error, assume inside to avoid false alarms
    
    def _monitor_loop(self):
        """Background monitoring loop for periodic checks."""
        while not self.stop_event.is_set():
            try:
                # Periodically sync geofence configuration from backend
                self._sync_geofence_config()
                
                # Check for stale exit trackers (person might have re-entered without update)
                self._cleanup_stale_trackers()
                
            except Exception as e:
                LOG.error(f'Error in monitor loop: {e}', exc_info=True)
            
            self.stop_event.wait(10)  # Check every 10 seconds
    
    def _sync_geofence_config(self):
        """Sync geofence configuration from backend."""
        try:
            response = self.runtime.request('GET', '/api/v1/ai/config')
            if response.status_code == 200:
                config = response.json()
                if config.get('code') == 200:
                    geofences = config['data'].get('geofences', [])
                    if geofences:
                        # Use first enabled geofence (single fence per requirement)
                        active_fence = next((g for g in geofences if g.get('enabled')), None)
                        if active_fence:
                            self.update_geofence(active_fence)
        except Exception as e:
            LOG.warning(f'Failed to sync geofence config: {e}')
    
    def _cleanup_stale_trackers(self):
        """Clean up stale exit trackers older than 1 hour."""
        now = time.monotonic()
        with self.lock:
            stale_codes = [
                code for code, tracker in self.exit_tracker.items()
                if now - tracker['exit_time'] > 3600  # 1 hour
            ]
            for code in stale_codes:
                del self.exit_tracker[code]
                LOG.info(f'Cleaned up stale exit tracker for {code}')
    
    def get_status(self) -> dict:
        """Get current geofence monitor status."""
        with self.lock:
            return {
                'geofenceConfigured': self.geofence is not None,
                'geofenceEnabled': self.geofence.get('enabled') if self.geofence else False,
                'activeExits': len(self.exit_tracker),
                'exits': {
                    code: {
                        'exitTime': tracker['exit_datetime'].isoformat(),
                        'elapsedSeconds': round(time.monotonic() - tracker['exit_time'], 1),
                        'alertLevel': tracker['alert_level'],
                        'lastPosition': {
                            'longitude': tracker['longitude'],
                            'latitude': tracker['latitude']
                        }
                    }
                    for code, tracker in self.exit_tracker.items()
                }
            }
