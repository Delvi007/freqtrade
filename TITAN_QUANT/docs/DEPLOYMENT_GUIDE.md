# DEPLOYMENT_GUIDE — Instalación en Termux

## Requisitos

- Android con Termux (de F-Droid o GitHub).
- Unos 200 MB libres.
- Python 3.9 o superior (`pkg install python`). Solo usa la biblioteca estándar.
- Opcional: `pip install cryptography` para cifrar con AES-GCM e `iqoptionapi` para el adaptador demo de IQ Option (no oficial).

## Instalación (un solo bloque en Termux)

```bash
termux-setup-storage
cd ~ && cp ~/storage/downloads/TITAN_QUANT_v7_2.tar.gz . && tar -xzf TITAN_QUANT_v7_2.tar.gz && bash TITAN_QUANT_v7_2/instalar_termux.sh
```

El instalador hace lo siguiente:

1. Comprueba Python y tzdata.
2. Busca tu instalación anterior. Mira en `…/proot-distro/installed-rootfs/ubuntu/root/TITAN_GOLD_NEWS` y en `~/TITAN_GOLD_NEWS`; también puedes darle la ruta como argumento.
3. Mueve tu `~/TITAN_QUANT` actual a `~/TITAN_QUANT_respaldo_FECHA`.
4. Instala la v7 en `~/TITAN_QUANT`.
5. **Copia** tus bases y archivos de estado. La instalación anterior no se modifica, y además guarda un tar.gz en `datos/respaldos/`.
6. Migra las bases.
7. Ejecuta la batería de pruebas.

## Uso diario

```bash
cd ~/TITAN_QUANT
bash titan.sh iniciar      # servidor web → abre http://127.0.0.1:8765 en Chrome
bash titan.sh bot          # bot de Telegram (opcional)
bash titan.sh estado       # servicios, bases y motores
bash titan.sh registro     # registro del servidor y enlaces de correo pendientes
bash titan.sh respaldar    # copia de las bases a datos/respaldos/
bash titan.sh detener
```

## Actualizar una instalación v7 (conserva cuentas y datos)

```bash
cd ~ && cp ~/storage/downloads/TITAN_QUANT_v7_2.tar.gz . && tar -xzf TITAN_QUANT_v7_2.tar.gz && bash TITAN_QUANT_v7_2/actualizar_termux.sh
```

## Primer acceso y administrador

1. Abre http://127.0.0.1:8765 **en el mismo teléfono** y pulsa **CREAR CUENTA DE ADMINISTRADOR**. Queda activada al instante, sin correo.
   - Si ya te habías registrado y el correo no llegó, solo **inicia sesión** desde el teléfono: tu cuenta se activa al entrar.
   - También puedes activarla por terminal: `python3 -m titan_quant.cli verificar-correo TU_CORREO`.
2. Entra en **Administración** (solo la ven los administradores).

## Correo para las solicitudes y las aceptaciones

Hotmail/Outlook.com personal **no** sirve para ENVIAR: Microsoft desactivó el SMTP con contraseña. Sí sirve para RECIBIR. Para enviar, usa una de estas dos opciones.

**Opción 1: Gmail (recomendada)**

1. Crea o usa una cuenta de Gmail.
2. Cuenta de Google → Seguridad → activa la **Verificación en 2 pasos**.
3. Busca «Contraseñas de aplicaciones» y crea una para «TITAN». Te dará 16 letras.
4. En TITAN: Configuración e integraciones → Correo (SMTP) → proveedor `gmail`, usuario = tu dirección de Gmail, clave = las 16 letras → **Guardar** → **Probar conexión**.
5. En Administración → **Enviar correo de prueba**. Revisa también la carpeta de spam.

**Opción 2: Brevo (gratis)**

Crea una cuenta en brevo.com → SMTP & API → copia el usuario (login SMTP) y la clave SMTP, y verifica en Brevo el correo que usarás como remitente. En TITAN elige el proveedor `brevo` y pon ese correo en «Remitente».

## cTrader: conectar y elegir cuenta (DEMO o REAL)

1. En https://openapi.ctrader.com → tu aplicación → añade como Redirect URI: `http://127.0.0.1:8765/api/tq/integraciones/ctrader/callback`.
2. En TITAN: Configuración e integraciones → cTrader → Client ID, Client Secret y esa Redirect URI → **Guardar** → **Autorizar con cTrader**. Acepta el permiso de **trading** (las autorizaciones antiguas eran solo de lectura).
   - Alternativa: `python3 -m titan_quant.cli importar-secretos` importa lo que tengas en `TITAN_CTRADER_CONNECTOR` (también dentro de proot); si el token era de solo lectura, vuelve a autorizar.
3. Bot operador → pestaña **DEMO** → broker cTrader → elige tu cuenta demo y el símbolo (p. ej. XAUUSD) → Guardar → Iniciar. Revisa en la app de cTrader que la operación aparece y cuadra.
4. Solo después: pestaña **REAL LIVE** → elige la cuenta live → habilita con la frase y tu contraseña → inicia con tu contraseña.

Cada pestaña es una cuenta independiente con su base (`datos/cuentas/*.db`). Solo se comparte el conocimiento (`datos/conocimiento.db`).

## Seguridad tras la instalación

Cambia tus credenciales antiguas en cada servicio, guarda las nuevas en Integraciones y ejecuta `python3 -m titan_quant.cli importar-secretos --borrar-originales`.

## Opciones

- `TITAN_PUERTO=8765`
- `TITAN_HOST=127.0.0.1`: usa `0.0.0.0` solo en una red de confianza; el tráfico va sin cifrar.
- `TITAN_HTTPS=1`: si hay un proxy TLS delante.
- `TITAN_URL_PUBLICA=https://…`: la URL que aparece en los enlaces de los correos.
- `TITAN_CLAVE_MAESTRA=<64 hex>`: clave maestra fuera del disco.

## Solución de problemas

- **No arranca:** revisa `bash titan.sh registro`. Si el puerto está ocupado, usa `TITAN_PUERTO=8766 bash titan.sh iniciar`.
- **Android cierra Termux:** desactiva la optimización de batería para Termux. `titan.sh` activa `termux-wake-lock`.
- **Volver a la versión anterior:** tu proyecto anterior sigue intacto y tu carpeta web está en `~/TITAN_QUANT_respaldo_*`.
