"""
Proceso worker del Parcial 3 (contenedor `worker`, misma imagen que la API):

  Kinesis ──> consumer.py ──┬──> live.py     contadores por event_time (camino rápido, segundos)  -> GET /analytics/live
                            └──> landing.py  JSON gzip en S3 cada ~60 s (append-only)              -> R4
  landing zone ──> app/star/etl.py (micro-lote cada N minutos o POST /admin/refresh-star)         -> estrella en Glue/Athena

Es el ÚNICO lector del stream: un shard admite 5 GetRecords/s compartidos entre todos los lectores,
así que la vista en vivo y la entrega a S3 comparten la misma lectura.
"""
