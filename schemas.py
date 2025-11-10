"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class AuthUser(BaseModel):
    """
    Users collection schema
    Collection name: "authuser"
    """
    email: EmailStr = Field(..., description="Email address")
    name: str = Field(..., description="Full name")
    password_hash: str = Field(..., description="Hashed password")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Meeting(BaseModel):
    """
    Meetings collection schema
    Collection name: "meeting"
    """
    title: str = Field(..., description="Meeting title")
    code: str = Field(..., description="Unique meeting code")
    host_id: str = Field(..., description="User id of host")
    participants: List[str] = Field(default_factory=list, description="User ids of participants")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

