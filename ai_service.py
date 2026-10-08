"""Standalone AI process. Runs AlgorithmRuntime and serves its frames/health over HTTP.

Web never loads models or touches the camera. This process owns all capture,
inference, emotion and video-encoding threads; AI reports to Java directly over
the X-AI-Key channel (outbox), so the web process is not on that path either.

Endpoints:
  GET /frame?cameraCode=...  -> AlgorithmRuntime.frame(code) dict
  GET /health                -> AlgorithmRuntime.health() dict

Bound to 127.0.0.1 (localhost only). No extra auth: it was previously an
in-process call, so there is no new trust boundary.
"""
import atexit
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env.local')

app = Flask(__name__)
runtime = None


def get_runtime():
    global runtime
    if runtime is None:
        from algorithm.runtime import AlgorithmRuntime
        base_url = os.getenv('JAVA_BASE_URL', 'http://127.0.0.1:8080')
        key = os.getenv('AI_SERVICE_KEY', '')
        runtime = AlgorithmRuntime(base_url, key, ROOT / 'runtime')
        runtime.start()
        atexit.register(runtime.stop)
    return runtime


@app.get('/frame')
def frame():
    code = request.args.get('cameraCode', 'CAM001')
    return jsonify(get_runtime().frame(code))


@app.get('/health')
def health():
    return jsonify(get_runtime().health())


@app.post('/api/v1/location/update')
def location_update():
    """Receive location update from BeiDou device."""
    from flask import request
    data = request.get_json()
    if not data:
        return jsonify({'code': 400, 'message': '缺少请求体'}), 400
    
    try:
        person_code = data.get('personCode')
        longitude = data.get('longitude')
        latitude = data.get('latitude')
        sample_time = data.get('sampleTime')
        device_id = data.get('deviceId')
        accuracy = data.get('accuracy')
        
        if not all([person_code, longitude, latitude, sample_time, device_id]):
            return jsonify({'code': 400, 'message': '缺少必要字段'}), 400
        
        runtime = get_runtime()
        runtime.geofence_monitor.process_location_update(
            person_code=person_code,
            longitude=float(longitude),
            latitude=float(latitude),
            sample_time=sample_time,
            device_id=device_id,
            accuracy=float(accuracy) if accuracy else None
        )
        
        return jsonify({'code': 200, 'message': 'success', 'data': {'received': True}})
    
    except Exception as e:
        return jsonify({'code': 500, 'message': f'处理失败: {str(e)}'}), 500


def main():
    if len(os.getenv('AI_SERVICE_KEY', '')) < 32:
        print('AI_SERVICE_KEY至少32字符；请先运行 scripts/setup-local.ps1', file=sys.stderr)
        sys.exit(1)
    get_runtime()
    from waitress import serve
    port = int(os.getenv('AI_PORT', '5002'))
    serve(app, host=os.getenv('AI_HOST', '127.0.0.1'), port=port, threads=4)


if __name__ == '__main__':
    main()
