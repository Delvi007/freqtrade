"""Diagnóstico de hardware y planificación adaptativa (motores 18 y 19).

Lee /proc y /sys (Linux, Android/Termux). Si un dato no es accesible se devuelve None y se dice:
nunca se inventa. No hay GPU utilizable desde Python estándar: se informa como "no detectada".
"""
import os
import shutil
import socket
import time

from . import config, niveles


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def memoria():
    t = _leer("/proc/meminfo")
    if not t:
        return {"total_mb": None, "disponible_mb": None}
    d = {}
    for ln in t.splitlines():
        p = ln.split()
        if len(p) >= 2 and p[1].isdigit():
            d[p[0].rstrip(":")] = int(p[1]) // 1024
    return {"total_mb": d.get("MemTotal"), "disponible_mb": d.get("MemAvailable", d.get("MemFree"))}


def cpu_uso(muestra_s=0.25):
    def leer():
        t = _leer("/proc/stat")
        if not t:
            return None
        v = [int(x) for x in t.splitlines()[0].split()[1:]]
        return sum(v), v[3] + (v[4] if len(v) > 4 else 0)
    a = leer()
    if not a:
        return None
    time.sleep(muestra_s)
    b = leer()
    tot, idle = b[0] - a[0], b[1] - a[1]
    return round(100 * (1 - idle / tot), 1) if tot > 0 else None


def temperaturas():
    out = []
    base = "/sys/class/thermal"
    try:
        zonas = sorted(os.listdir(base))
    except OSError:
        return out
    for z in zonas:
        if not z.startswith("thermal_zone"):
            continue
        v = _leer(os.path.join(base, z, "temp"))
        tipo = (_leer(os.path.join(base, z, "type")) or z).strip()
        try:
            c = int(v.strip()) / 1000
            if -20 < c < 150:
                out.append({"sensor": tipo, "c": round(c, 1)})
        except (ValueError, AttributeError):
            continue
    return out[:12]


def latencia(host="query1.finance.yahoo.com", puerto=443, espera=3):
    t = time.monotonic()
    try:
        with socket.create_connection((host, puerto), timeout=espera):
            return round((time.monotonic() - t) * 1000)
    except OSError:
        return None


def diagnostico(red=True):
    nucleos = os.cpu_count() or 1
    carga = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    mem = memoria()
    try:
        disco = shutil.disk_usage(str(config.DATOS if config.DATOS.exists() else config.RAIZ))
        disco_d = {"total_gb": round(disco.total / 1e9, 1), "libre_gb": round(disco.free / 1e9, 1)}
    except OSError:
        disco_d = {"total_gb": None, "libre_gb": None}
    procesos = None
    try:
        procesos = sum(1 for p in os.listdir("/proc") if p.isdigit())
    except OSError:
        pass
    temps = temperaturas()
    return {
        "ts": int(time.time()),
        "cpu": {"nucleos": nucleos, "uso_pct": cpu_uso(), "carga_1_5_15": [round(x, 2) if x is not None else None for x in carga]},
        "memoria": mem,
        "disco": disco_d,
        "gpu": {"detectada": False, "nota": "Python estándar no accede a GPU/VRAM; ningún motor usa GPU."},
        "temperatura": {"sensores": temps, "max_c": max((t["c"] for t in temps), default=None),
                        "nota": None if temps else "Sin sensores accesibles (habitual en Android sin root)."},
        "red": {"latencia_ms": latencia() if red else None},
        "procesos": procesos,
        "plataforma": {"termux": "com.termux" in (os.environ.get("PREFIX", "") + str(config.RAIZ)), "python": os.sys.version.split()[0]},
    }


def recomendar_nivel(d=None):
    d = d or diagnostico(red=False)
    mem = d["memoria"]["disponible_mb"] or 0
    nuc = d["cpu"]["nucleos"] or 1
    carga = (d["cpu"]["carga_1_5_15"] or [0])[0] or 0
    if mem >= 3000 and nuc >= 8 and carga < nuc * 0.5:
        rec = "super"
    elif mem >= 1500 and nuc >= 4 and carga < nuc * 0.7:
        rec = "avanzado"
    elif mem >= 600:
        rec = "intermedio"
    else:
        rec = "basico"
    return {"recomendado": rec, "motivo": f"{mem} MB libres, {nuc} núcleos, carga {carga}"}


def plan_ejecucion(nivel, politica, d=None):
    """Ajusta la carga REAL de esta ejecución sin cambiar el nivel elegido. Devuelve parámetros + ajustes aplicados."""
    p = niveles.parametros(nivel)
    niveles.validar_politica(politica)
    d = d or diagnostico(red=False)
    ajustes = []
    nuc = d["cpu"]["nucleos"] or 1
    mem = d["memoria"]["disponible_mb"]
    carga = (d["cpu"]["carga_1_5_15"] or [None])[0]
    if politica == "equilibrado":
        c = max(1, min(p["concurrencia"], nuc // 2 or 1))
        if c < p["concurrencia"]:
            ajustes.append(f"concurrencia {p['concurrencia']}→{c} (política equilibrada)")
            p["concurrencia"] = c
    if politica in ("automatico", "equilibrado", "maximo") and mem is not None and mem < 400:
        ajustes.append(f"memoria baja ({mem} MB): Monte Carlo {p['montecarlo_sim']}→{min(p['montecarlo_sim'], 300)}, backtest {p['backtest_barras']}→{min(p['backtest_barras'], 300)}")
        p["montecarlo_sim"] = min(p["montecarlo_sim"], 300)
        p["backtest_barras"] = min(p["backtest_barras"], 300)
        p["concurrencia"] = 1
    if politica == "automatico" and carga is not None and carga > nuc * 0.9:
        ajustes.append(f"carga alta ({carga}): concurrencia→1 y simulaciones a la mitad")
        p["concurrencia"] = 1
        p["montecarlo_sim"] = max(200, p["montecarlo_sim"] // 2)
    p["concurrencia"] = max(1, min(p["concurrencia"], nuc))
    return p, ajustes
