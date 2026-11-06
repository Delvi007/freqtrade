# SECURITY_POLICY — TITAN QUANT v7

## Acción urgente (hallazgo de la auditoría)

El backup del 05/11/2026 contenía en texto plano estas credenciales:

- La contraseña de IQ Option.
- El token de Telegram, y otro token antiguo en `registros_ejecucion/`.
- El client secret y los tokens OAuth de cTrader, con una cuenta LIVE vinculada.

**Considéralas comprometidas.** Haz lo siguiente:

1. Cambia la contraseña de IQ Option y activa la verificación en dos pasos (2FA).
2. Ejecuta `/revoke` en @BotFather.
3. Regenera el secret y revoca el acceso de la app en cTrader.
4. Guarda las credenciales nuevas desde **Configuración e integraciones**, nunca en archivos.

El paquete de la v7 **no incluye ninguna credencial**. El instalador copia las de tu instalación anterior para que no pierdas el servicio. Después, `python3 -m titan_quant.cli importar-secretos --borrar-originales` las cifra y borra los archivos en claro.

## Controles implementados

| Control | Implementación |
|---|---|
| Contraseñas | scrypt (N=2^14, r=8, p=1) con sal de 16 bytes; PBKDF2-SHA256 con 600 000 iteraciones si falta scrypt. Mínimo 10 caracteres de 3 tipos. |
| Sesiones | Token aleatorio de 256 bits en una cookie `HttpOnly; SameSite=Lax` (y `Secure` con `TITAN_HTTPS=1`). En la base solo se guarda su SHA-256. Caducan a las 12 h, o a los 14 días con «recordar». Se pueden cerrar en remoto. |
| CSRF | Token por sesión en la cabecera `X-CSRF-Token` en cada POST, más comprobación de `Origin`/`Referer`. OAuth de cTrader con `state`. |
| Fuerza bruta | 5 fallos bloquean la cuenta 15 min. Límites por IP: 10 intentos de login cada 5 min, 5 registros por hora y 240 peticiones de API por minuto. |
| Enumeración de cuentas | Mismo mensaje y tiempo parecido para un correo inexistente en registro, inicio de sesión y recuperación. |
| Tokens de correo | Aleatorios y guardados como hash. Son de un solo uso y caducan: 24 h el de verificación y 30 min el de recuperación. Al restablecer la contraseña se cierran todas las sesiones. |
| Credenciales de integraciones | Cifrado autenticado ligado a (usuario, proveedor, campo). La clave maestra está en `datos/.clave_maestra` con permiso 600, o en la variable `TITAN_CLAVE_MAESTRA`. La interfaz solo recibe máscaras. El borrado sobrescribe antes de eliminar. |
| Registros | Filtro que oculta tokens, claves y códigos. Los errores 500 devuelven solo un número de referencia. |
| Cabeceras | CSP, X-Frame-Options DENY, nosniff y Referrer-Policy no-referrer; HSTS con HTTPS. |
| Red | Escucha en `127.0.0.1` por defecto. Con `TITAN_HOST=0.0.0.0` sigue exigiendo sesión y avisa de que sin HTTPS el tráfico va en claro. |
| Activación sin correo | Solo para la cuenta PROPIETARIA y solo desde el propio dispositivo (127.0.0.1), con su contraseña. Desde la red siempre se exige confirmar el correo. |
| Roles | **Propietario**: acceso total y es el único que nombra administradores; no se puede suspender. **Administrador**: aprueba, rechaza y suspende usuarios normales, y ve el diagnóstico y los datos heredados. **Usuario**: solo sus propios datos. Todo queda en auditoría. |
| Permisos | Los datos heredados (planes, laboratorio, historial del bot) y el diagnóstico requieren rol de administrador. Cada usuario solo ve sus propios análisis, alertas, operaciones e integraciones. |
| Bot operador | Parada de emergencia, límites de riesgo y bloqueo ante datos obsoletos o desconexión. También controla duplicados (incluido un índice único), verifica las órdenes, registra cada decisión y exige confirmación del modo. El modo real está bloqueado. |
| Respaldos | Las bases se copian con la API de SQLite y permiso 600, con las credenciales cifradas. La clave maestra **no** se incluye: guárdala aparte. |

## Lo que queda pendiente

- HTTPS propio: para salir de localhost usa un proxy con TLS (por ejemplo Caddy) o un túnel.
- 2FA para las cuentas de TITAN.
- Rotación automática de la clave maestra.
