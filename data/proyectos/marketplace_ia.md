# Marketplace con IA generativa

## Objetivo y contexto
Una startup quiere lanzar un marketplace para pequeños comercios en el que un LLM genere automáticamente las descripciones de los productos y recomiende productos a los compradores. Buscan financiamiento y necesitan mostrar el producto funcionando en una feria de inversionistas.

## Usuarios y volumen
Meta de 10.000 usuarios registrados en el primer año. La demanda no está validada: no hay usuarios piloto ni lista de espera. Se esperan picos durante campañas en redes sociales.

## Requisitos funcionales
- Registro de comercios y publicación de productos
- Generación automática de descripciones con IA
- Recomendaciones personalizadas de productos
- Carrito de compras y pagos en línea
- Moderación del contenido generado y publicado
- Seguimiento de despachos

## Requisitos no funcionales
- Protección de los datos personales y de pago
- Control del gasto en inferencia de IA
- Disponibilidad durante las campañas
- Tiempo de carga del catálogo menor a 3 segundos

## Restricciones
- Plazo de 3 meses hasta la feria de inversionistas
- Presupuesto mínimo: créditos gratuitos de la nube y de la API de IA
- Dependencia de APIs externas de IA con precios variables

## Equipo
2 desarrolladores junior recién egresados, sin experiencia en sistemas en producción, pagos ni modelos de IA. Sin diseñador ni QA.

## Integraciones
- Pasarela de pagos
- API de un proveedor de LLM
- Empresa de logística para los despachos

## Decisiones a evaluar
- Alcance: marketplace completo vs MVP de catálogo con IA y pagos de terceros
