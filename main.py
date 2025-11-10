import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from database import db, create_document, get_documents
from schemas import AuthUser, Meeting

# Settings
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

app = FastAPI(title="MeetNgo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth utils
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

class Token(BaseModel):
    access_token: str
    token_type: str

class RegisterPayload(BaseModel):
    name: str
    email: EmailStr
    password: str

class LoginPayload(BaseModel):
    email: EmailStr
    password: str

class MeetingCreate(BaseModel):
    title: str

class JoinMeetingPayload(BaseModel):
    code: str

# Helper functions

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject: str = payload.get("sub")
        if subject is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    email = payload.get("email")
    user = None
    if email:
        res = get_documents("authuser", {"email": email})
        if res:
            user = res[0]
    if not user:
        raise credentials_exception
    return user

@app.get("/")
def read_root():
    return {"message": "MeetNgo API is running"}

# Auth routes
@app.post("/auth/register", response_model=Token)
def register(payload: RegisterPayload):
    # Check if user exists
    existing = get_documents("authuser", {"email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = get_password_hash(payload.password)
    user = AuthUser(email=payload.email, name=payload.name, password_hash=hashed)
    create_document("authuser", user)

    access_token = create_access_token({"sub": user.email, "email": user.email, "name": user.name})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/login", response_model=Token)
def login(payload: LoginPayload):
    res = get_documents("authuser", {"email": payload.email})
    if not res:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    user = res[0]
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token = create_access_token({"sub": user.get("email"), "email": user.get("email"), "name": user.get("name")})
    return {"access_token": access_token, "token_type": "bearer"}

# Meetings
from random import choices
import string

def generate_meeting_code():
    return "".join(choices(string.ascii_uppercase + string.digits, k=8))

@app.post("/meetings")
def create_meeting(payload: MeetingCreate, current_user: dict = Depends(get_current_user)):
    code = generate_meeting_code()
    meeting = Meeting(title=payload.title, code=code, host_id=current_user.get("_id") and str(current_user.get("_id")), participants=[current_user.get("email")])
    create_document("meeting", meeting)
    return {"code": code, "title": payload.title}

@app.post("/meetings/join")
def join_meeting(payload: JoinMeetingPayload, current_user: dict = Depends(get_current_user)):
    res = get_documents("meeting", {"code": payload.code})
    if not res:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = res[0]
    participants = set(meeting.get("participants", []))
    participants.add(current_user.get("email"))
    # Persist participant add
    db["meeting"].update_one({"_id": meeting["_id"]}, {"$set": {"participants": list(participants), "updated_at": datetime.utcnow()}})
    return {"joined": True}

# Simple WebRTC signaling via websockets (demo)
from fastapi import WebSocket, WebSocketDisconnect

rooms = {}

@app.websocket("/ws/{code}")
async def signaling_ws(websocket: WebSocket, code: str):
    await websocket.accept()
    if code not in rooms:
        rooms[code] = set()
    rooms[code].add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Broadcast to others in the same room
            for ws in list(rooms.get(code, [])):
                if ws is not websocket:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        pass
    except WebSocketDisconnect:
        pass
    finally:
        rooms.get(code, set()).discard(websocket)
        if not rooms.get(code):
            rooms.pop(code, None)

# Test endpoint remains
@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
