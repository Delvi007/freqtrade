# API_INTEGRATIONS — TITAN QUANT v7

## Proveedores externos (Configuración e integraciones)

| Proveedor | Uso | Campos | Prueba de conexión |
|---|---|---|---|
| Yahoo Finance | Velas y cotizaciones (fuente principal; no oficial y con posible retraso de 15 min) | — | Descarga EURUSD=X |
| Google News RSS | Noticias por activo y eventos macro | — | Lee el RSS |
| Finnhub · Alpha Vantage | Datos con clave (opcionales; aún no los usan los motores) | API key | Pide una cotización |
| Claude API | Clave de IA (opcional) | API key | `GET /v1/models` |
| Correo SMTP | Verificación y recuperación de contraseña | servidor, puerto, usuario, clave, remitente, seguridad | Inicio de sesión SMTP |
| Telegram | Alertas y bot | token, chat_id | `getMe` |
| IQ Option | Adaptador demo | correo, clave | Conexión en PRACTICE |
| cTrader | Lectura de cuentas | client_id, client_secret, redirect_uri y tokens (por OAuth) | `/connect/tradingaccounts` |
| Personalizado | Guardar cualquier clave cifrada | nombre, url, clave | — |

## API HTTP de TITAN (todo bajo `/api/`, JSON)

**Rutas públicas:** `GET /api/health`, `GET /api/auth/estado`, `GET /api/auth/verificar?token=` y `POST /api/auth/{registro,login,olvide,restablecer,reenviar}`.

**Con sesión.** En todo POST hace falta la cabecera `X-CSRF-Token`:

- **Cuenta:** `GET /api/auth/{yo,sesiones}`, `GET /api/cuenta/{eventos,preferencias}` y `POST /api/auth/{logout,logout_todas,sesiones/cerrar,cambiar_clave}`, más `POST /api/cuenta/{perfil,preferencias}`.
- **Motores:** `GET /api/tq/{motores,hardware,niveles,analisis?id=}`, `POST /api/tq/analizar {simbolo, horizonte}` y `POST /api/tq/nivel {nivel, politica}`.
- **Integraciones:** `GET /api/tq/integraciones` y `POST /api/tq/integraciones/{guardar,probar,activar,eliminar,ctrader/autorizar}`, más `GET /api/tq/integraciones/ctrader/callback`.
- **Alertas:** `GET /api/tq/alertas[?categoria&estado&importancia&buscar&ver&desde_id]`, `GET /api/tq/alertas/{contadores,categorias}` y `POST /api/tq/alertas/{leer,noleer,ocultar,restaurar,silenciar}`.
- **Historial:** `GET /api/tq/historial?tipo=&ver=` y `POST /api/tq/historial/{ocultar,archivar,restaurar,eliminar_permanente}`.
- **Bot operador:** `GET /api/tq/operador`, `GET /api/tq/operador/{operaciones,decisiones}` y `POST /api/tq/operador/{ajustes,estado,ciclo,real}`.
- **Solo el propietario:** `GET /api/tq/{sistema,diagnostico}` y las rutas heredadas `/api/{history,stats,alerts,plans}`, `/api/lab/*` y `POST /api/plan*`.
- **Cualquier usuario con sesión (heredadas):** `/api/{assets,quotes,chart,mtf}` y `POST /api/{analyze,report}`.
