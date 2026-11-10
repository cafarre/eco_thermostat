# Procedimiento de Despliegue de Eco Thermostat en Home Assistant

Cuando el usuario solicite desplegar o actualizar el componente `eco_thermostat` en Home Assistant, NO buscar ni indagar en otros métodos. Seguir estrictamente este procedimiento directo:

## 1. Rutas de Despliegue
- **Origen (Workspace local):** `d:\GitRepos\home-assistant\eco_thermostat`
- **Destino (Samba Share HA OS):** `\\10.0.0.20\config\custom_components\eco_thermostat` (o `\\vmhaos\config\custom_components\eco_thermostat`)

## 2. Archivos a Sincronizar
Copiar desde el origen hacia el destino los archivos y carpetas del componente:
- `config_flow.py`
- `climate.py`
- `const.py`
- `manifest.json`
- `number.py`
- `sensor.py`
- `services.yaml`
- `strings.json`
- `__init__.py`
- `translations/` (incluyendo `translations/es.json`)

## 3. Limpieza de Caché de Bytecode
Tras copiar los archivos, es OBLIGATORIO eliminar la caché de bytecode en destino para asegurar que Python compile el nuevo código:
```powershell
if (Test-Path "\\vmhaos\config\custom_components\eco_thermostat\__pycache__") {
    Remove-Item "\\vmhaos\config\custom_components\eco_thermostat\__pycache__\*" -Force -Recurse
}
```

## 4. Reinicio de Home Assistant
Los cambios en módulos de un `custom_component` no se recargan en caliente; requieren reiniciar Home Assistant Core:
- Invocar el servicio de reinicio mediante la herramienta MCP `ha_call_service`:
  ```json
  {
    "domain": "homeassistant",
    "service": "restart"
  }
  ```
- O consultar al usuario para que lo reinicie desde la interfaz si prefiere hacerlo manualmente.
