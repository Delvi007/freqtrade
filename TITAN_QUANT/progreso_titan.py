from datetime import datetime

def progreso(porcentaje, mensaje, estado="EN PROCESO"):
    porcentaje = max(0, min(100, int(porcentaje)))
    ancho = 24
    llenos = int(ancho * porcentaje / 100)
    barra = "█" * llenos + "░" * (ancho - llenos)
    hora = datetime.now().astimezone().strftime("%H:%M:%S")
    print(
        f"\r[{hora}] [{barra}] {porcentaje:3d}% | "
        f"{estado} | {mensaje}",
        flush=True
    )
    if porcentaje in (0, 100) or estado in ("OK", "ERROR", "AVISO"):
        print(flush=True)

def titulo(texto):
    print("\n" + "=" * 68, flush=True)
    print(" TITAN GOLD NEWS :: " + texto, flush=True)
    print("=" * 68, flush=True)
