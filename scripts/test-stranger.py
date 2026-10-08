"""Standalone stranger-recognition test: compare a single image against known_faces/.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\test-stranger.py <image_path>

Only reads the local face library and the given image; no camera, no Java backend.
"""
import os
import re
import sys
from pathlib import Path

import face_recognition

# 修复中文 Windows 控制台 GBK 编码无法输出中文的问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
KNOWN_DIR = ROOT / 'known_faces'
TOLERANCE = 0.55


def load_known_faces():
    encodings, names = [], []
    if not KNOWN_DIR.exists():
        return encodings, names
    for f in sorted(KNOWN_DIR.iterdir()):
        if f.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
            continue
        name = re.sub(r'(_\d+)$', '', f.stem)
        encs = face_recognition.face_encodings(face_recognition.load_image_file(str(f)))
        if encs:
            encodings.append(encs[0])
            names.append(name)
    return encodings, names


def main():
    if len(sys.argv) < 2:
        print('用法: python scripts/test-stranger.py <图片路径>')
        sys.exit(1)
    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f'文件不存在: {image_path}')
        sys.exit(1)

    known_encs, known_names = load_known_faces()
    print(f'人脸库已加载 {len(known_names)} 人: {known_names or "（空）"}')

    image = face_recognition.load_image_file(image_path)
    locations = face_recognition.face_locations(image)
    if not locations:
        print('结果: 未检测到人脸')
        return

    encodings = face_recognition.face_encodings(image, locations)
    for i, (loc, enc) in enumerate(zip(locations, encodings)):
        top, right, bottom, left = loc
        if not known_encs:
            result = '陌生人（人脸库为空）'
        else:
            distances = face_recognition.face_distance(known_encs, enc)
            best = int(distances.argmin())
            if distances[best] <= TOLERANCE:
                result = f'识别为: {known_names[best]}（认识，距离 {distances[best]:.3f}）'
            else:
                result = f'陌生人（最接近 {known_names[best]}，距离 {distances[best]:.3f} > 阈值 {TOLERANCE}）'
        print(f'人脸{i + 1} @({left},{top})-({right},{bottom}): {result}')


if __name__ == '__main__':
    main()
