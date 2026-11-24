"""
Parcial 3: eventos de negocio publicados en Amazon Kinesis (contrato en
parcial3-harness-estudiantes/contract/EVENTS.md).

  * search_performed      -> muy frecuente; perder uno es aceptable, frenar la búsqueda no.
  * reservation_created   -> transacción de negocio; se publica DESPUÉS del commit y se reintenta.
  * reservation_cancelled -> igual que la creación.
"""
from .schema import reservation_event, search_event
from .publisher import publisher

__all__ = ["publisher", "search_event", "reservation_event"]
