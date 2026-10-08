"""Run stranger recognition on an image and save results to output/recognition/.

Outputs:
  - 标注结果.jpg      原图 + 人脸框 + 识别标签（绿=认识，红=陌生人）
  - 人脸N_<名字>.jpg  每张检测到的人脸裁剪图

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\recognize-to-folder.py <图片路径>
"""
import os
import re
import sys
from pathlib import Path

import face_recognition
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
KNOWN_DIR = ROOT / 'known_faces'
OUT_DIR = ROOT / 'output' / 'recognition'
TOLERANCE = 0.55

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_known_faces():
    encodings, names = [], []
    if KNOWN_DIR.exists():
        for f in sorted(KNOWN_DIR.iterdir()):
            if f.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
                continue
            name = re.sub(r'(_\d+)$', '', f.stem)
            encs = face_recognition.face_encodings(face_recognition.load_image_file(str(f)))
            if encs:
                encodings.append(encs[0])
                names.append(name)
    return encodings, names


def load_font(size=28):
    for p in (r'C:/Windows/Fonts/msyh.ttc', r'C:/Windows/Fonts/simhei.ttf'):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def main():
    if len(sys.argv) < 2:
        print('用法: python scripts/recognize-to-folder.py <图片路径>')
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pil = Image.open(image_path).convert('RGB')
    draw = ImageDraw.Draw(pil)
    font = load_font()

    results = []
    for i, (loc, enc) in enumerate(zip(locations, encodings)):
        top, right, bottom, left = loc
        if known_encs:
            distances = face_recognition.face_distance(known_encs, enc)
            best = int(distances.argmin())
            if distances[best] <= TOLERANCE:
                label, color = known_names[best], (46, 160, 67)
            else:
                label, color = '陌生人', (200, 40, 40)
            dist = round(float(distances[best]), 3)
        else:
            label, color, dist = '陌生人', (200, 40, 40), None

        results.append((i + 1, label, dist))

        # 裁剪人脸（含 30% 边距）单独保存
        h = bottom - top
        m = int(h * 0.3)
        t, b, l, r = max(0, top - m), min(image.shape[0], bottom + m), max(0, left - m), min(image.shape[1], right + m)
        crop = pil.crop((l, t, r, b))
        crop.save(OUT_DIR / f'人脸{i + 1}_{label}.jpg')

        # 在原图上画框 + 标签
        draw.rectangle([left, top, right, bottom], outline=color, width=4)
        text = label if dist is None else f'{label} ({dist})'
        draw.text((left, max(0, top - 36)), text, fill=color, font=font)

    annotated = OUT_DIR / '标注结果.jpg'
    pil.save(annotated)

    print(f'已保存到 {OUT_DIR}')
    for no, label, dist in results:
        print(f'  人脸{no}: {label}' + (f'（距离 {dist}）' if dist is not None else ''))


if __name__ == '__main__':
    main()
