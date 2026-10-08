import sys
from types import SimpleNamespace
from algorithm.faces import FaceRegistry

def test_replacing_and_deleting_face_never_retains_old_encoding(monkeypatch):
    recognition=SimpleNamespace(load_image_file=lambda x:'pixels',face_locations=lambda x:[(0,1,1,0)],face_encodings=lambda *a:[[.1,.2]])
    monkeypatch.setitem(sys.modules,'face_recognition',recognition)
    registry=FaceRegistry();acks=[]
    person={'personCode':'P1','version':1,'enabled':True,'hasFace':True,'name':'test','personType':'ELDER'}
    registry.synchronize([person],lambda c:b'photo',lambda *args:acks.append(args))
    assert 'P1' in registry.entries
    recognition.face_locations=lambda image:[]
    registry.synchronize([dict(person,version=2)],lambda c:b'invalid',lambda *args:acks.append(args))
    assert not registry.entries and acks[-1][2]=='FAILED'
    recognition.face_locations=lambda image:[(0,1,1,0)]
    registry.synchronize([dict(person,version=3)],lambda c:b'photo',lambda *args:acks.append(args))
    registry.synchronize([dict(person,version=4,enabled=False)],lambda c:b'photo',lambda *args:acks.append(args))
    assert not registry.entries and acks[-1][2]=='REMOVED'
