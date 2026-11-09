"""Ejecuta el laboratorio walk-forward sobre un archivo de la sonda. Solo análisis offline.

Uso:
  python -m titan_quant.binaria_bot.laboratorio RUTA_JSON [--payout 0.86] [--k 4] [--informe RUTA_TXT]

No se conecta a ningún broker y no envía órdenes.
"""
import argparse
import sys

from titan_quant.binaria_bot.datos import cargar_crudas, agregar_m1
from titan_quant.binaria_bot.backtest import evaluar_walk_forward
from titan_quant.binaria_bot.autonomia import evidencia_suficiente


def construir_informe(ruta, payout, k):
    velas = agregar_m1(cargar_crudas(ruta))
    if not velas:
        return "Sin velas M1 completas: no hay nada que evaluar.", False
    resumenes = evaluar_walk_forward(velas, payout=payout, k=k)
    lineas = [
        f"Archivo: {ruta}",
        f"Velas M1 completas: {len(velas)} | payout: {payout} | equilibrio: {1/(1+payout):.4f} | tramos: {k}",
        "",
        "tramo  ops  ganadas  perdidas  empates  acierto   IC95 Wilson        EV/u    ventaja",
    ]
    for r in resumenes:
        acierto = f"{r.tasa_acierto:.4f}" if r.tasa_acierto is not None else "  -   "
        lineas.append(
            f"{r.indice:>5} {r.n:>4} {r.ganadas:>8} {r.perdidas:>9} {r.empates:>8}   {acierto}   "
            f"[{r.wilson_bajo:.4f}, {r.wilson_alto:.4f}]  {r.ev_unitario:+.4f}  "
            f"{'SI' if r.ventaja_significativa else 'no'}")
    ok, motivo = evidencia_suficiente(resumenes, min_tramos=k)
    lineas += ["", f"Evidencia para operar: {'SI' if ok else 'NO'} ({motivo})",
               "Nota: sin evidencia el bot se abstiene. Un resultado negativo no es un fallo del código."]
    return "\n".join(lineas), ok


def main(argv=None):
    p = argparse.ArgumentParser(description="Laboratorio walk-forward de binarias (offline)")
    p.add_argument("ruta")
    p.add_argument("--payout", type=float, default=0.86)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--informe", default=None)
    a = p.parse_args(argv)
    texto, _ = construir_informe(a.ruta, a.payout, a.k)
    print(texto)
    if a.informe:
        with open(a.informe, "w", encoding="utf-8") as f:
            f.write(texto + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
