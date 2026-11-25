# Reglas y Preferencias del Proyecto

- **Transparencia y Explicaciones**: Explica siempre detalladamente qué acciones vas a realizar y el porqué de cada una de ellas (causa técnica, razonamiento y propósito del cambio) antes o durante la ejecución.
- **Cero Decisiones Unilaterales / Pedir Permiso**: NUNCA tomes decisiones por tu cuenta que alteren o contradigan las instrucciones del usuario (por ejemplo, excluir o dejar fuera archivos que el usuario pidió incluir, o modificar el alcance de una orden). Si consideras que algo no debería incluirse o tienes dudas, PREGUNTA Y PIDE PERMISO antes de actuar.
- **Planes y Aprobación Previa Obligatoria**: ANTES de realizar cualquier cambio, corrección o modificación en el código o archivos del proyecto, es OBLIGATORIO presentar SIEMPRE un plan formal (mediante un artifact interactivo con `RequestFeedback: true`) y ESPERAR a que el usuario lo revise y lo apruebe explícitamente antes de empezar a implementar. NUNCA aplicar modificaciones en los archivos sin la aprobación previa del plan por parte del usuario.
- **Git Commits**: NUNCA realices `git commit` sin el permiso explícito del usuario. Siempre consulta o espera a que el usuario indique explícitamente commitear.
- **Diagnósticos de Home Assistant y Logs**: Para diagnosticar cualquier problema o fallo en Home Assistant, debes revisar el registro de logs del sistema (*Ajustes > Sistema > Registros*). Si no tienes acceso directo a dicho registro a través de los archivos del sistema, PÍDESELO DIRECTAMENTE AL USUARIO (captura o texto de los errores) en lugar de intentar adivinar a ciegas, optimizando así el consumo de tokens y el tiempo de resolución.
- **Despliegue en Home Assistant**: Cuando el usuario pida desplegar el componente en Home Assistant, no indagar ni dar rodeos. El destino es el recurso compartido Samba `\\10.0.0.20\config\custom_components\eco_thermostat` (IP de vmhaos: `10.0.0.20`). Se copian los archivos del componente, se limpia `__pycache__` en destino y se solicita/ejecuta el reinicio de Home Assistant Core (ver detalle en `deployment.md`).
- **Modificación de Dashboards de Home Assistant (Lovelace)**:
  - **Copias de seguridad obligatorias**: Antes de realizar cualquier cambio en un dashboard, crear SIEMPRE un archivo `.bak` de seguridad del archivo correspondiente en `\\vmhaos\config\.storage\lovelace.<id>`.
  - **Prohibido sintetizar o reescribir dashboards de memoria**: Las operaciones de guardado de Lovelace (`ha_config_set_dashboard` o WS `lovelace/config/save`) reemplazan la totalidad del dashboard. NUNCA generar ni pasar un diccionario resumido o reconstruido manualmente desde el LLM, ya que elimina las tarjetas personalizadas (auto-entities, webrtc, etc.) y configuraciones del resto de vistas.
  - **Procedimiento para cambios puntuales**:
    1. Cargar el JSON íntegro original del archivo de almacenamiento (`\\vmhaos\config\.storage\lovelace.<id>`).
    2. Modificar mediante script (Python) **única y exclusivamente** el campo o tarjeta solicitada, dejando intacto el 100% de las demás vistas y tarjetas.
    3. Enviar el JSON completo resultante vía WebSocket (`lovelace/config/save`) a Home Assistant.
    4. Verificar mediante `diff` contra el `.bak` que el único cambio existente es el solicitado.

