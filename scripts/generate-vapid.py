"""Create optional local Web Push keys; never overwrite a private key."""
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

root=Path(__file__).resolve().parent.parent/'runtime'
root.mkdir(exist_ok=True)
private=root/'vapid-private.pem'
if private.exists():raise SystemExit('密钥已存在，拒绝覆盖。')
key=ec.generate_private_key(ec.SECP256R1())
with private.open('xb') as f:
    f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
print('VAPID_PUBLIC_KEY='+base64.urlsafe_b64encode(public).rstrip(b'=').decode())
print('VAPID_PRIVATE_KEY='+private.as_posix())
print('将配置加入 .env.local，并填写 VAPID_SUBJECT=mailto:管理员的真实邮箱。不要提交私钥。')
