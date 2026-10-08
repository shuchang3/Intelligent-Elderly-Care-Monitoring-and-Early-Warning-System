import face_recognition
import cv2
import os
import re
import threading
import base64
from io import BytesIO
from PIL import Image
from deepface import DeepFace
import sys

# 修复中文 Windows 控制台 GBK 编码无法输出 emoji 导致线程崩溃的问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ================== 全局配置（适配项目路径） ==================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
known_faces_dir = os.path.join(BASE_DIR, "known_faces")
tolerance = 0.55
camera_id = 0

# 全局变量
known_encodings = []
known_names = []
latest_frame_base64 = None  # 保存最新一帧画面（传给前端）
running = False
socketio = None  # 由app.py注入socketio实例

# ================== 加载人脸库 ==================
def load_known_faces():
    global known_encodings, known_names
    encodings = []
    names = []
    if not os.path.exists(known_faces_dir):
        os.makedirs(known_faces_dir)
        known_encodings, known_names = encodings, names
        return
    for filename in os.listdir(known_faces_dir):
        if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            continue
        raw_name = os.path.splitext(filename)[0]
        name = re.sub(r'(_\d+)$', '', raw_name)
        img_path = os.path.join(known_faces_dir, filename)
        image = face_recognition.load_image_file(img_path)
        encs = face_recognition.face_encodings(image)
        if encs:
            encodings.append(encs[0])
            names.append(name)
    known_encodings[:] = encodings
    known_names[:] = names
    print(f"✅ 人脸库加载完成，人数：{len(set(names))}")

# ================== 摄像头识别循环（子线程运行） ==================
def camera_loop():
    global latest_frame_base64, running
    cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ 无法打开摄像头")
        running = False
        return
    print("✅ 识别线程启动")

    # 防重复连续告警标记
    alert_stranger_flag = False
    alert_sad_flag = False

    while running:
        ret, frame = cap.read()
        if not ret:
            break
        small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
        rgb_small = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_small)
        face_encs = face_recognition.face_encodings(rgb_small, face_locations)

        detect_stranger = False
        detect_sad = False

        for (top, right, bottom, left), enc in zip(face_locations, face_encs):
            top *= 2
            right *= 2
            bottom *= 2
            left *= 2

            matches = face_recognition.compare_faces(known_encodings, enc, tolerance=tolerance)
            name = "陌生人"
            if True in matches:
                idx = matches.index(True)
                name = known_names[idx]
            emotion_text = "?"
            try:
                face_roi = frame[top:bottom, left:right]
                if face_roi.size > 0:
                    res = DeepFace.analyze(
                        img_path=face_roi,
                        actions=['emotion'],
                        enforce_detection=False,
                        silent=True,
                        detector_backend='mtcnn'
                    )
                    if res and isinstance(res, list) and len(res)>0:
                        emo_dict = res[0].get("emotion",{})
                        if emo_dict:
                            emotion_text = max(emo_dict, key=emo_dict.get)
            except:
                pass

            # 绘制框和文字
            cv2.rectangle(frame, (left, top), (right, bottom), (0,255,0), 2)
            label = f"{name} [{emotion_text}]"
            cv2.putText(frame, label, (left, top-8), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0,255,0), 2)

            # 告警判断
            if name == "陌生人":
                detect_stranger = True
            if emotion_text == "sad":
                detect_sad = True

        # 推送告警（防止一秒推多条，增加状态锁）
        if socketio:
            if detect_stranger and not alert_stranger_flag:
                alert_stranger_flag = True
                alert_data = {
                    "event_type":"stranger",
                    "camera_id":f"cam{camera_id:03d}",
                    "time":cv2.getTickCount(),
                    "screenshot":""
                }
                socketio.emit("new_alert", alert_data)
            if not detect_stranger:
                alert_stranger_flag = False

            if detect_sad and not alert_sad_flag:
                alert_sad_flag = True
                alert_data = {
                    "event_type":"emotion",
                    "camera_id":f"cam{camera_id:03d}",
                    "time":cv2.getTickCount(),
                    "screenshot":""
                }
                socketio.emit("new_alert", alert_data)
            if not detect_sad:
                alert_sad_flag = False

        # 将帧转为base64，供前端接口调用
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        buf = BytesIO()
        pil_img.save(buf, format="JPEG", quality=80)
        latest_frame_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    cap.release()
    running = False
    print("摄像头识别线程结束")

# ================== 对外启动/停止接口 ==================
def start_detect(sio):
    global running, socketio
    if running:
        return
    socketio = sio
    load_known_faces()
    running = True
    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()

def stop_detect():
    global running
    running = False

# 获取最新画面（给flask接口调用）
def get_latest_frame():
    return latest_frame_base64

# 新增人脸（对接人脸录入页面上传接口）
def add_new_face(name, image_np):
    """
    name:人员姓名
    image_np: cv2图像数组
    return:成功True/失败False
    """
    if not re.fullmatch(r"[\w-]{1,64}", name):
        raise ValueError("Use a stable person code without path separators")
    rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb)
    if len(locations) != 1 or len(face_recognition.face_encodings(rgb, locations)) != 1:
        return False
    success, encoded = cv2.imencode(".jpg", image_np)
    if not success:
        return False
    os.makedirs(known_faces_dir, exist_ok=True)
    encoded.tofile(os.path.join(known_faces_dir, name + ".jpg"))
    load_known_faces()
    return True



if __name__ == "__main__":
    # 单独测试用（直接运行算法文件可以启动摄像头预览）
    load_known_faces()
    cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
    while True:
        ret, frame = cap.read()
        if not ret: break
        cv2.imshow("test", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()