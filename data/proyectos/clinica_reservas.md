# Reservas de una red de clínicas

## Objetivo y contexto
Una red de cuatro clínicas privadas gestiona sus horas médicas por teléfono y con planillas separadas por sede. Se quiere un sistema web y móvil que centralice la disponibilidad de los profesionales y permita a los pacientes reservar, reagendar y cancelar horas, y a las recepcionistas administrar las agendas de todas las sedes.

## Usuarios y volumen
Unos 2.000 pacientes reservan cada día, con 150 usuarios concurrentes en horario punta (lunes de 8:00 a 10:00). Se espera un crecimiento del 20 % anual y la apertura de dos sedes más en dos años.

## Requisitos funcionales
- Buscar horas disponibles por especialidad, profesional y sede
- Reservar, reagendar y cancelar citas
- Administrar agendas, bloqueos y sobrecupos
- Enviar recordatorios por correo y SMS
- Consultar el historial de reservas del paciente
- Panel de ocupación por sede para la gerencia

## Requisitos no funcionales
- Disponibilidad del 99,5 % en horario hábil
- Tiempo de respuesta menor a 2 segundos en la búsqueda de horas
- Acceso por roles: paciente, recepcionista, profesional y administrador
- Accesibilidad WCAG 2.1 AA en los flujos de reserva

## Restricciones
- Plazo de 6 meses hasta la primera versión en producción
- Presupuesto acotado: se prefiere pagar por uso antes que licencias
- Datos personales sensibles de salud: cumplimiento de la Ley 21.719
- La red ya usa Microsoft 365 para correo y directorio

## Equipo
4 personas con experiencia: dos desarrolladores full stack (Python y React), una desarrolladora con experiencia en PostgreSQL y un líder técnico con experiencia en despliegues en la nube.

## Integraciones
- Sistema clínico existente (ficha del paciente) mediante API REST
- Pasarela de SMS
- Servicio de correo de Microsoft 365

## Decisiones a evaluar
- Arquitectura: monolito modular vs microservicios
- Infraestructura: PaaS gestionado vs contenedores en Kubernetes
