"""Atomically replace immutable face snapshots; stable person codes, never display-name paths."""
import hashlib
import io
import threading

class FaceRegistry:
    def __init__(self):
        self.lock=threading.RLock()
        self.entries={}

    def synchronize(self,people,download,ack,dlib_lock=None):
        import face_recognition
        # dlib is not thread-safe; hold the runtime-wide dlib lock across every
        # face_locations/face_encodings call so the infer thread cannot race us
        # into a native access violation. dlib_lock may be None for standalone use.
        active=set()
        for p in people:
            code=p['personCode'];version=int(p['version'])
            active.add(code)
            with self.lock:old=self.entries.get(code)
            if not p['enabled'] or not p['hasFace']:
                with self.lock:self.entries.pop(code,None)
                ack(code,version,'REMOVED' if not p['enabled'] else 'NONE',None)
                continue
            if old and old['version']==version:continue
            # Invalidate old data before processing an update; no stale recognition after deletion/change.
            with self.lock:self.entries.pop(code,None)
            try:
                image=face_recognition.load_image_file(io.BytesIO(download(code)))
                if dlib_lock is not None:
                    with dlib_lock:
                        locations=face_recognition.face_locations(image)
                        if len(locations)!=1:raise ValueError('照片必须包含且仅包含一张清晰人脸')
                        encodings=face_recognition.face_encodings(image,locations)
                else:
                    locations=face_recognition.face_locations(image)
                    if len(locations)!=1:raise ValueError('照片必须包含且仅包含一张清晰人脸')
                    encodings=face_recognition.face_encodings(image,locations)
                if len(encodings)!=1:raise ValueError('无法生成有效人脸编码')
                with self.lock:self.entries[code]={'version':version,'encoding':encodings[0],'name':p['name'],'type':p['personType']}
                ack(code,version,'ACTIVE',None)
            except Exception as exc:
                with self.lock:self.entries.pop(code,None)
                ack(code,version,'FAILED',str(exc)[:200])
        with self.lock:
            for code in set(self.entries)-active:self.entries.pop(code,None)

    def match(self,encoding,tolerance=.55):
        import face_recognition
        with self.lock:items=list(self.entries.items())
        if not items:return None
        distances=face_recognition.face_distance([x[1]['encoding'] for x in items],encoding)
        best=int(distances.argmin())
        if distances[best]>tolerance:return None
        code,entry=items[best]
        return {'personCode':code,'name':entry['name'],'personType':entry['type']}
