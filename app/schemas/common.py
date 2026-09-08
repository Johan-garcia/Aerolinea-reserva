from enum import Enum


class ClaseAsientoEnum(str, Enum):
    ECONOMICA = "Económica"
    EJECUTIVA = "Ejecutiva"


class TipoReglaTarifaEnum(str, Enum):
    PROMOCIONAL = "Promocional"
    FLEXIBLE = "Flexible"


class EstadoReservaEnum(str, Enum):
    PENDIENTE = "Pendiente"
    CONFIRMADA = "Confirmada"
    CANCELADA = "Cancelada"


class MetodoPagoEnum(str, Enum):
    TARJETA = "Tarjeta"
    PSE = "PSE"
    TRANSFERENCIA = "Transferencia"


class EstadoPagoEnum(str, Enum):
    APROBADO = "Aprobado"
    RECHAZADO = "Rechazado"
    PENDIENTE = "Pendiente"


class TipoDocumentoEnum(str, Enum):
    CC = "CC"
    CE = "CE"
    PASAPORTE = "PAS"
    TI = "TI"

