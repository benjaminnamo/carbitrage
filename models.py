# models.py
from pydantic import BaseModel

class FetchRequest(BaseModel):
    country: str
    city: str
    make: str
    model: str

class ClientRequest(BaseModel):
    country: str
    city1: str
    city2: str
    make: str
    model: str
