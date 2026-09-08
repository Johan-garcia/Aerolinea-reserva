from pydantic import BaseModel, Field, ConfigDict
from app.schemas.common import TipoDocumentoEnum


class PasajeroBase(BaseModel):
    tipo_documento: TipoDocumentoEnum
    numero_documento: str
    nombres: str
    apellidos: str
    email: str = Field(..., description="Correo electrónico del pasajero")
    telefono: str


class PasajeroCreate(PasajeroBase):
    pass


class PasajeroResponse(PasajeroBase):
    id_pasajero: int

    model_config = ConfigDict(from_attributes=True)

