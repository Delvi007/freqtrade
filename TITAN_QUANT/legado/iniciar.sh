#!/bin/bash
# Arranca TITAN GOLD NEWS y lo reinicia si se cae. Detener: Ctrl+C
cd "$(dirname "$0")" || exit 1
[ -s .telegram_token ] || { echo "Falta .telegram_token (guarda ahí el token de tu bot, una sola línea)."; exit 1; }
chmod 600 .telegram_token .telegram_chat .estado_bot.json 2>/dev/null
while true; do
  python3 titan_bot.py; c=$?
  [ $c -ge 128 ] && break
  echo "El bot se detuvo (código $c). Reiniciando en 10 s... (Ctrl+C para salir)"; sleep 10
done
