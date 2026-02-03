from datetime import datetime, timedelta , timezone
from jose import jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
import os

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict):
    expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    payload = dict(data)
    if "userId" not in payload:
        if "sub" in payload:
            payload["userId"] = payload.get("sub")
        elif "id" in payload:
            payload["userId"] = payload.get("id")

    if "role" not in payload:
        if "type" in payload:
            payload["role"] = payload.get("type")

    exp_ts = int(expire.timestamp())
    payload["exp"] = exp_ts

    algorithm = os.getenv("HASH_ALGORITHM", "HS256")
    token = jwt.encode(payload, os.getenv("SECRET_KEY"), algorithm=algorithm)
    return token


def decode_token(token: str):
    algorithm = os.getenv("HASH_ALGORITHM", "HS256")
    return jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=[algorithm])