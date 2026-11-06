#!/usr/bin/env bash
# =====================================================================================
#  TITAN QUANT — ACTUALIZADOR (para una instalación v7 que ya funciona en ~/TITAN_QUANT)
#  Conserva: datos/ (cuentas, credenciales cifradas, clave maestra, alertas, historial),
#            las bases titan_*.db, .estado_bot.json y los archivos de credenciales.
#  Solo reemplaza el código. Antes hace un respaldo del código y de las bases.
# =====================================================================================
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
DESTINO="${TITAN_DESTINO:-$HOME/TITAN_QUANT}"
FECHA="$(date +%Y%m%d_%H%M%S)"
PY="$(command -v python3 || command -v python)"

[ -d "$AQUI/TITAN_QUANT/titan_quant" ] || { echo "No encuentro la carpeta TITAN_QUANT junto a este actualizador."; exit 1; }
if [ ! -d "$DESTINO/titan_quant" ]; then
  echo "No hay una instalación v7 en $DESTINO. Usa: bash $AQUI/instalar_termux.sh"; exit 1
fi
echo "=== Actualizando TITAN QUANT en $DESTINO ==="

# 1) Detener el servidor y el bot si están activos
( cd "$DESTINO" && bash titan.sh detener >/dev/null 2>&1 ) || true
BOT_ACTIVO=0; pgrep -f "titan_bot.py" >/dev/null 2>&1 && BOT_ACTIVO=1 || true

# 2) Respaldo de las bases y del código actual
( cd "$DESTINO" && "$PY" -m titan_quant.cli respaldar ) || echo "Aviso: no se pudo respaldar con la CLI; continúo con la copia del código."
mkdir -p "$DESTINO/datos/respaldos"
( cd "$DESTINO" && tar -czf "datos/respaldos/codigo_antes_de_actualizar_$FECHA.tar.gz" \
    --exclude=./datos --exclude='./*.db' --exclude='./*.db-wal' --exclude='./*.db-shm' --exclude=./.telegram_token \
    --exclude=./.telegram_chat --exclude=./.iqoption.env --exclude='*/__pycache__' . ) || true
chmod 600 "$DESTINO/datos/respaldos/codigo_antes_de_actualizar_$FECHA.tar.gz" 2>/dev/null || true

# 3) Copiar el código nuevo encima (el paquete no trae datos ni credenciales: no pisa nada tuyo)
cp -r "$AQUI/TITAN_QUANT/." "$DESTINO/"
find "$DESTINO" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
chmod +x "$DESTINO/titan.sh"

# 4) Migrar bases, probar y arrancar
cd "$DESTINO"
"$PY" -m titan_quant.cli migrar
echo "Ejecutando pruebas (sobre una copia; no tocan tus datos)…"
"$PY" -m titan_quant.cli probar || echo "ATENCIÓN: hay pruebas con fallos. Tu código anterior está en datos/respaldos/codigo_antes_de_actualizar_$FECHA.tar.gz"
bash titan.sh iniciar
[ "$BOT_ACTIVO" = "1" ] && bash titan.sh bot || true

cat <<EOF

=====================================================================
 Actualización a v7.2 terminada. Abre en Chrome:  http://127.0.0.1:8765
 - Tus operaciones anteriores se copiaron a su cuenta (datos/cuentas/).
   Los bots quedan DETENIDOS: revisa cada pestaña antes de iniciar.
 - cTrader: Integraciones → cTrader → Autorizar con cTrader (permiso de
   TRADING). Luego Bot operador → DEMO → elige cuenta y símbolo.
 - Importar el conector anterior:  python3 -m titan_quant.cli importar-secretos
=====================================================================
EOF
