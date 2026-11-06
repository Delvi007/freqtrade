# TITAN QUANT v7

TITAN QUANT es una plataforma de inteligencia cuantitativa con 23 motores, cuentas de usuario, credenciales cifradas, un bot operador en simulación, alertas y un historial que no borra nada.

- **Instalar en Termux:** consulta `docs/DEPLOYMENT_GUIDE.md`.
- **Qué está hecho y qué no:** consulta `docs/IMPLEMENTATION_STATUS.md`.
- **Pruebas:** consulta `docs/TEST_REPORT.md`, o ejecuta `python3 -m titan_quant.cli probar`.

```bash
bash titan.sh iniciar     # http://127.0.0.1:8765
bash titan.sh bot         # bot de Telegram
bash titan.sh detener
```

## Estructura

| Ruta | Contenido |
|---|---|
| `titan_quant/` | Núcleo nuevo: `motores/` (los 23), `seguridad/`, `trader/`, `servidor.py`, `cli.py`, `pruebas/` |
| `web/` | Interfaz: el `index.html` existente más `tq_auth.js`, `tq_app.js` y `tq.css` |
| Raíz (`*.py`) | Módulos existentes, que se siguen usando: agente, plan_web, lab_engine, titan_bot… |
| `conectores/ctrader/` | Scripts OAuth originales de cTrader |
| `legado/` | Módulos antiguos que no se usan, conservados |
| `docs/` | Documentación de la sección 21 y el diff de los cambios en los módulos existentes |
| `datos/` | Se crea al instalar: `titan_quant.db`, la clave maestra, el registro y los respaldos (permiso 700) |

TITAN es una herramienta de análisis, no un asesor financiero. El modo real del bot está bloqueado.
