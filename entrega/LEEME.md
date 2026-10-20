# Entrega del Parcial 2

- `report.md`: corrida del harness oficial contra el despliegue en AWS (20-oct-2026, semilla 24306): **68/70**.
- Configuración usada: `parcial2-harness/config.yaml` (sin credenciales). La IP pública cambia cada vez que se reinicia el Learner Lab; se actualiza antes de la ventana de calificación.

## R11: los 2 puntos que faltan no vienen de este despliegue

`test_instance_classes` encuentra `m4.xlarge` en el historial de EMR de los últimos 45 días. Ese tipo no pertenece a este proyecto: viene de dos clusters creados desde la consola para otro trabajo del curso, ya terminados:

| Cluster | Nombre | Creado (UTC) | Horas normalizadas |
|---|---|---|---|
| j-06162343PF8P2WX5Y14Y | Mi clúster | 2026-10-01 14:46 | 24 |
| j-05150151KF1W3FKEIETS | Mi clúster | 2026-10-17 22:13 | 72 |

El cluster de este proyecto es `j-058656532KZ94Z8T1Y58` (`airline-curate-20261020-2135`): 1 master + 2 core **m4.large**, step `curate-reservations` COMPLETED, 12 horas normalizadas, terminado solo. Un cluster EMR terminado no se puede borrar, así que el harness lo seguirá viendo hasta que salga de la ventana de 45 días (15-nov y 1-dic de 2026). Las demás pruebas de R11 pasan: sin NAT, sin Multi-AZ, 6 servicios facturables.
