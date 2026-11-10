#!/usr/bin/env bash
# =====================================================================================
#  TITAN QUANT v7 — instalador para Termux (Android).  También funciona en Ubuntu/proot.
#  Uso:  bash instalar_termux.sh [CARPETA_PROYECTO_ANTERIOR]
#  - NO modifica tu proyecto anterior: copia sus datos.
#  - Si ya existe ~/TITAN_QUANT (tu carpeta del index.html), la renombra con fecha: nada se pierde.
# =====================================================================================
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
DESTINO="${TITAN_DESTINO:-$HOME/TITAN_QUANT}"
FECHA="$(date +%Y%m%d_%H%M%S)"
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33m%s\033[0m\n' "$*"; }

echo "=== TITAN QUANT v7.2 · instalación ==="
[ -d "$AQUI/TITAN_QUANT/titan_quant" ] || { echo "No encuentro la carpeta TITAN_QUANT junto a este instalador."; exit 1; }

# 0) Si ya hay una instalación v7, ACTUALIZAR en lugar de instalar (conserva cuentas y datos)
if [ -d "$DESTINO/titan_quant" ] && [ -f "$AQUI/actualizar_termux.sh" ]; then
  echo "Ya existe TITAN QUANT v7 en $DESTINO: se ACTUALIZA conservando tus cuentas y datos."
  exec bash "$AQUI/actualizar_termux.sh"
fi

# 1) Python
if ! command -v python3 >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then pkg install -y python; else echo "Instala Python 3 (apt install python3) y repite."; exit 1; fi
fi
PY="$(command -v python3)"
"$PY" - <<'EOF'
import sys, sqlite3, hashlib
assert sys.version_info >= (3, 9), "Se necesita Python 3.9 o superior"
print("Python", sys.version.split()[0], "· SQLite", sqlite3.sqlite_version, "· scrypt", hasattr(hashlib, "scrypt"))
EOF
if ! "$PY" -c "from zoneinfo import ZoneInfo; ZoneInfo('America/Santo_Domingo')" 2>/dev/null; then
  aviso "Instalando datos de zonas horarias (tzdata)…"
  "$PY" -m pip install --quiet tzdata || aviso "No se pudo instalar tzdata: instala 'pkg install tzdata' o 'pip install tzdata'."
fi

if ! "$PY" -c "import websocket, requests" 2>/dev/null; then
  aviso "Instalando dependencias del conector IQ Option (websocket-client, requests)…"
  "$PY" -m pip install --quiet "websocket-client>=1.6,<2" "requests>=2.31,<3" \
    || aviso "No se pudieron instalar: ejecuta 'python3 -m pip install -r TITAN_QUANT/requirements.txt'. Sin ellas el conector IQ Option no funciona."
fi

# 2) Buscar la instalación anterior (para copiar SUS DATOS, sin tocarla)
ANTERIOR="${1:-}"
if [ -z "$ANTERIOR" ]; then
  for c in "${PREFIX:-/nonexistent}/var/lib/proot-distro/installed-rootfs/ubuntu/root/TITAN_GOLD_NEWS" "$HOME/TITAN_GOLD_NEWS" "/root/TITAN_GOLD_NEWS"; do
    [ -f "$c/titan_bot.py" ] && { ANTERIOR="$c"; break; }
  done
fi
CTRADER_ANT=""
for c in "$(dirname "${ANTERIOR:-/x}")/TITAN_CTRADER_CONNECTOR" "${PREFIX:-/nonexistent}/var/lib/proot-distro/installed-rootfs/ubuntu/root/TITAN_CTRADER_CONNECTOR"; do
  [ -f "$c/ctrader_app.json" ] && { CTRADER_ANT="$c"; break; }
done

# 3) Apartar la carpeta existente (tu index.html anterior queda a salvo)
if [ -e "$DESTINO" ]; then
  mv "$DESTINO" "${DESTINO}_respaldo_$FECHA"
  aviso "Tu carpeta anterior se movió a ${DESTINO}_respaldo_$FECHA"
fi
cp -r "$AQUI/TITAN_QUANT" "$DESTINO"
mkdir -p "$DESTINO/datos/respaldos"; chmod 700 "$DESTINO/datos" "$DESTINO/datos/respaldos"

# 4) Migrar datos de la versión anterior (copia, con respaldo comprimido)
if [ -n "$ANTERIOR" ]; then
  verde "Instalación anterior encontrada: $ANTERIOR"
  ( cd "$ANTERIOR" && tar -czf "$DESTINO/datos/respaldos/migracion_$FECHA.tar.gz" --ignore-failed-read \
      $(ls titan_activos.db titan_planes.db titan_lab.db .estado_bot.json noticias_recopiladas.json noticias_en_vivo.json analisis_macro_v2.md informe_oro.md 2>/dev/null) ) || true
  chmod 600 "$DESTINO/datos/respaldos/migracion_$FECHA.tar.gz" 2>/dev/null || true
  for f in titan_activos.db titan_planes.db titan_lab.db .estado_bot.json noticias_recopiladas.json noticias_en_vivo.json analisis_macro_v2.md informe_oro.md .telegram_token .telegram_chat .iqoption.env; do
    [ -f "$ANTERIOR/$f" ] && cp -p "$ANTERIOR/$f" "$DESTINO/$f"
  done
  chmod 600 "$DESTINO"/.telegram_* "$DESTINO"/.iqoption.env "$DESTINO"/*.db 2>/dev/null || true
  if [ -n "$CTRADER_ANT" ]; then
    for f in ctrader_app.json oauth_tokens.json oauth_code.json ctrader_accounts.json; do
      [ -f "$CTRADER_ANT/$f" ] && cp -p "$CTRADER_ANT/$f" "$DESTINO/conectores/ctrader/$f" && chmod 600 "$DESTINO/conectores/ctrader/$f"
    done
  fi
else
  aviso "No encontré una instalación anterior: TITAN empezará con bases de datos nuevas."
fi

# 5) Bases de datos, pruebas y permisos
cd "$DESTINO"
chmod +x titan.sh
"$PY" -m titan_quant.cli migrar
echo
echo "Ejecutando la batería de pruebas (sin internet, sobre una copia; 1-3 minutos)…"
if "$PY" -m titan_quant.cli probar; then verde "Pruebas superadas."; else aviso "Hay pruebas con fallos: revisa la salida antes de usar TITAN."; fi

cat <<EOF

=====================================================================
 TITAN QUANT instalado en: $DESTINO

 1) Arrancar:            cd $DESTINO && bash titan.sh iniciar
 2) Abrir en Chrome:     http://127.0.0.1:8765
 3) Pulsa CREAR CUENTA DE ADMINISTRADOR. Desde este teléfono queda
    activada al instante (sin correo) y tienes acceso total.
    Para que lleguen correos a otros usuarios: Administración → Configurar correo
    (Gmail con contraseña de aplicación, o Brevo; Hotmail no sirve para enviar).
 4) Cifrar tus credenciales antiguas en la bóveda y borrar los archivos en claro:
                         python3 -m titan_quant.cli importar-secretos --borrar-originales
    (Antes CAMBIA tu contraseña de IQ Option y revoca el token de Telegram y de cTrader:
     viajaron sin cifrar dentro del backup.)
 5) Bot de Telegram:     bash titan.sh bot      · Detener todo: bash titan.sh detener
=====================================================================
EOF
