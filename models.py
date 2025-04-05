# models.py
from pydantic import BaseModel

# Request for single city car search
class FetchRequest(BaseModel):
    country: str
    city: str
    make: str
    model: str

# Request for two-city price comparison
class ClientRequest(BaseModel):
    country: str
    city1: str
    city2: str
    make: str
    model: str
