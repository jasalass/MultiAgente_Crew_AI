# Migración de ERP a la nube

## Objetivo y contexto
Una empresa de distribución opera desde hace 12 años un ERP monolítico on-premise (Java EE con Oracle) para ventas, inventario, facturación y contabilidad. Los servidores llegan al fin de su soporte en 14 meses. La gerencia quiere migrar a la nube sin detener la operación y aprovechar la migración para modernizar, pero el equipo duda entre trasladar el sistema tal como está o refactorizarlo.

## Usuarios y volumen
500 empleados en 12 sucursales, con 180 usuarios concurrentes en horario de oficina. Procesos nocturnos de cierre que tardan 3 horas. 10 años de datos históricos (unos 2 TB).

## Requisitos funcionales
- Mantener la facturación electrónica sin interrupciones
- Migrar los datos históricos con trazabilidad completa
- Integrar el inventario en tiempo real con las sucursales
- Auditar los cambios en registros contables
- Conservar los informes regulatorios actuales

## Requisitos no funcionales
- Tiempo de recuperación ante desastres menor a 1 hora
- Integridad transaccional en ventas y contabilidad
- Ventanas de corte solo en fines de semana
- Trazabilidad de cada paso de la migración

## Restricciones
- Fin del soporte de los servidores en 14 meses
- Licencias Oracle vigentes por 2 años más
- Migración gradual: no se acepta un corte total ("big bang")
- Presupuesto aprobado solo para el primer año de nube

## Equipo
6 desarrolladores que conocen a fondo el ERP (Java EE y PL/SQL), con experiencia limitada en la nube y en contenedores. Un arquitecto externo a tiempo parcial.

## Integraciones
- Bancos (conciliación y pagos)
- Servicio de facturación electrónica del SII
- Directorio corporativo (Active Directory)
- Portal B2B de clientes mayoristas

## Decisiones a evaluar
- Migración: lift & shift vs refactorizar a microservicios
- Base de datos: mantener Oracle vs migrar a PostgreSQL gestionado
