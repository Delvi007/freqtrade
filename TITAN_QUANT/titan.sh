#!/usr/bin/env bash
# TITAN QUANT — control de servicios.   bash titan.sh {iniciar|detener|estado|bot|bot-detener|registro|probar|respaldar}
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || command -v python)"
mkdir -p datos && chmod 700 datos
SRV_PID=datos/servidor.pid
BOT_PID=datos/bot.pid

vivo() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

case "${1:-estado}" in
  iniciar)
    if vivo $SRV_PID; then echo "El servidor ya está activo (PID $(cat $SRV_PID))."; else
      command -v termux-wake-lock >/dev/null && termux-wake-lock || true
      nohup "$PY" -m titan_quant.cli servidor >> datos/servidor.log 2>&1 &
      echo $! > $SRV_PID; sleep 2
      if vivo $SRV_PID; then echo "TITAN QUANT activo → abre en el navegador: http://127.0.0.1:${TITAN_PUERTO:-8765}"
      else echo "No arrancó. Revisa: bash titan.sh registro"; fi
    fi ;;
  detener)
    for f in $SRV_PID $BOT_PID; do vivo $f && kill "$(cat $f)" && echo "Detenido PID $(cat $f)"; rm -f $f; done
    command -v termux-wake-unlock >/dev/null && termux-wake-unlock; true ;;
  estado)
    vivo $SRV_PID && echo "Servidor: ACTIVO (PID $(cat $SRV_PID)) · http://127.0.0.1:${TITAN_PUERTO:-8765}" || echo "Servidor: detenido"
    vivo $BOT_PID && echo "Bot de Telegram: ACTIVO (PID $(cat $BOT_PID))" || echo "Bot de Telegram: detenido"
    "$PY" -m titan_quant.cli estado ;;
  bot)
    if vivo $BOT_PID; then echo "El bot de Telegram ya está activo."; exit 0; fi
    nohup bash -c 'while true; do '"$PY"' titan_bot.py; c=$?; [ $c -ge 128 ] && break; echo "bot reiniciado ($c)"; sleep 10; done' >> datos/bot.log 2>&1 &
    echo $! > $BOT_PID; echo "Bot de Telegram iniciado (registro: datos/bot.log)" ;;
  bot-detener)
    vivo $BOT_PID && kill "$(cat $BOT_PID)"; pkill -f "titan_bot.py" 2>/dev/null; rm -f $BOT_PID; echo "Bot de Telegram detenido." ;;
  registro)
    tail -n 60 datos/servidor.log 2>/dev/null; echo "---- enlaces de correo pendientes (si no hay SMTP):"; ls -1t datos/correo_saliente 2>/dev/null | head -3 | while read f; do echo "== $f"; cat "datos/correo_saliente/$f"; done ;;
  probar)    "$PY" -m titan_quant.cli probar ;;
  respaldar) "$PY" -m titan_quant.cli respaldar ;;
  *) echo "Uso: bash titan.sh {iniciar|detener|estado|bot|bot-detener|registro|probar|respaldar}"; exit 2 ;;
esac
