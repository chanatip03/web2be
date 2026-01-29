from datetime import datetime, timedelta
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
    expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
    data.update({"exp": expire})
    token = jwt.encode(data, os.getenv("SECRET_KEY"), algorithm="HS256")
    return token


def decode_token(token: str):
    return jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=[os.getenv("ALGORITHM")])