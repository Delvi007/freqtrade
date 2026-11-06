"""Funciones matemáticas puras (sin dependencias) usadas por los motores. Todas evitan mirar al futuro:
cada valor en la posición i solo usa datos hasta i."""
import math


def media(v):
    return sum(v) / len(v) if v else None


def desv(v, ddof=1):
    n = len(v)
    if n <= ddof:
        return None
    m = sum(v) / n
    return math.sqrt(sum((x - m) ** 2 for x in v) / (n - ddof))


def cuantil(v, q):
    if not v:
        return None
    s = sorted(v)
    pos = (len(s) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def retornos(c):
    return [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1]]


def log_retornos(c):
    return [math.log(c[i] / c[i - 1]) for i in range(1, len(c)) if c[i - 1] > 0 and c[i] > 0]


def ema(v, n):
    if not v:
        return []
    k, e, out = 2 / (n + 1), v[0], []
    for x in v:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def sma(v, n):
    out, s = [], 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        out.append(s / min(i + 1, n))
    return out


def rsi_serie(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    ga = sum(max(c[i] - c[i - 1], 0) for i in range(1, n + 1)) / n
    pe = sum(max(c[i - 1] - c[i], 0) for i in range(1, n + 1)) / n
    out[n] = 100.0 if pe == 0 else 100 - 100 / (1 + ga / pe)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ga = (ga * (n - 1) + max(d, 0)) / n
        pe = (pe * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if pe == 0 else 100 - 100 / (1 + ga / pe)
    return out


def true_range(h, l, c):
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def atr_serie(h, l, c, n=14):
    tr = true_range(h, l, c)
    out, a = [], None
    for i, x in enumerate(tr):
        a = x if a is None else (a * (n - 1) + x) / n if i >= n else (a * i + x) / (i + 1)
        out.append(a)
    return out


def macd(c, r=12, l=26, s=9):
    m = [a - b for a, b in zip(ema(c, r), ema(c, l))]
    sig = ema(m, s)
    return m, sig, [a - b for a, b in zip(m, sig)]


def bollinger(c, n=20, k=2.0):
    if len(c) < n:
        return None
    w = c[-n:]
    m, d = media(w), desv(w, 0)
    return {"media": m, "sup": m + k * d, "inf": m - k * d, "ancho_pct": (2 * k * d / m * 100) if m else None,
            "pos": (c[-1] - (m - k * d)) / (2 * k * d) if d else 0.5}


def adx(h, l, c, n=14):
    if len(c) < 2 * n + 1:
        return None
    pdm, mdm = [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    tr = true_range(h, l, c)

    def wilder(v):
        s, out = sum(v[1:n + 1]), []
        out.append(s)
        for x in v[n + 1:]:
            s = s - s / n + x
            out.append(s)
        return out
    trs, ps, ms = wilder(tr), wilder(pdm), wilder(mdm)
    dx = []
    for t, p, m in zip(trs, ps, ms):
        pdi, mdi = (100 * p / t if t else 0), (100 * m / t if t else 0)
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0)
    a = sum(dx[:n]) / n
    for x in dx[n:]:
        a = (a * (n - 1) + x) / n
    pdi, mdi = 100 * ps[-1] / trs[-1] if trs[-1] else 0, 100 * ms[-1] / trs[-1] if trs[-1] else 0
    return {"adx": a, "di_mas": pdi, "di_menos": mdi}


def eficiencia(c, n=20):
    """Ratio de eficiencia de Kaufman: 1 = tendencia limpia, 0 = ruido."""
    if len(c) <= n:
        return None
    mov = abs(c[-1] - c[-1 - n])
    ruido = sum(abs(c[i] - c[i - 1]) for i in range(len(c) - n, len(c)))
    return mov / ruido if ruido else 0.0


def correlacion(a, b):
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def asimetria(v):
    n, s = len(v), desv(v, 0)
    if n < 3 or not s:
        return None
    m = sum(v) / n
    return sum(((x - m) / s) ** 3 for x in v) / n


def curtosis_exceso(v):
    n, s = len(v), desv(v, 0)
    if n < 4 or not s:
        return None
    m = sum(v) / n
    return sum(((x - m) / s) ** 4 for x in v) / n - 3


def autocorrelacion(v, lag=1):
    if len(v) <= lag + 2:
        return None
    return correlacion(v[:-lag], v[lag:])


def hurst(v):
    """Exponente de Hurst por R/S en varias escalas (0.5 ≈ aleatorio, >0.5 persistente, <0.5 reversión)."""
    n = len(v)
    if n < 64:
        return None
    escalas, rs = [], []
    k = 8
    while k <= n // 2:
        vals = []
        for i in range(0, n - k + 1, k):
            seg = v[i:i + k]
            m = sum(seg) / k
            acc, mx, mn = 0.0, -1e18, 1e18
            for x in seg:
                acc += x - m
                mx, mn = max(mx, acc), min(mn, acc)
            s = desv(seg, 0)
            if s:
                vals.append((mx - mn) / s)
        if vals:
            escalas.append(math.log(k))
            rs.append(math.log(sum(vals) / len(vals)))
        k *= 2
    if len(escalas) < 3:
        return None
    mx, my = media(escalas), media(rs)
    num = sum((x - mx) * (y - my) for x, y in zip(escalas, rs))
    den = sum((x - mx) ** 2 for x in escalas)
    return num / den if den else None


def ratio_varianza(r, q=4):
    """Lo-MacKinlay simplificado: VR(q) = Var(r_q)/(q·Var(r)). 1 = paseo aleatorio."""
    if len(r) < q * 10:
        return None
    v1 = desv(r)
    rq = [sum(r[i:i + q]) for i in range(0, len(r) - q + 1)]
    vq = desv(rq)
    return (vq ** 2) / (q * v1 ** 2) if v1 else None


def jarque_bera(v):
    s, k = asimetria(v), curtosis_exceso(v)
    if s is None or k is None:
        return None
    return len(v) / 6 * (s ** 2 + k ** 2 / 4)


def wilson(exitos, n, z=1.96):
    if n == 0:
        return (None, None)
    p = exitos / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - m), min(1.0, c + m))


def max_drawdown(curva):
    pico, mdd = -1e18, 0.0
    for x in curva:
        pico = max(pico, x)
        mdd = max(mdd, pico - x)
    return mdd


def sigmoide(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def logistica_entrenar(X, y, epocas=300, lr=0.1, l2=0.01):
    """Regresión logística con descenso de gradiente por lotes y regularización L2 (datos ya estandarizados)."""
    d = len(X[0])
    w, b = [0.0] * d, 0.0
    n = len(X)
    for _ in range(epocas):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            p = sigmoide(sum(a * c for a, c in zip(w, xi)) + b)
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return w, b


def logistica_prob(w, b, x):
    return sigmoide(sum(a * c for a, c in zip(w, x)) + b)


def bayes_entrenar(X, y):
    clases = {}
    for xi, yi in zip(X, y):
        clases.setdefault(yi, []).append(xi)
    modelo = {}
    for k, filas in clases.items():
        cols = list(zip(*filas))
        modelo[k] = {"prior": len(filas) / len(X), "m": [media(c) for c in cols],
                     "v": [max((desv(c, 0) or 0) ** 2, 1e-9) for c in cols]}
    return modelo


def bayes_prob(modelo, x, clase=1):
    logp = {}
    for k, m in modelo.items():
        s = math.log(m["prior"])
        for xi, mu, var in zip(x, m["m"], m["v"]):
            s += -0.5 * math.log(2 * math.pi * var) - (xi - mu) ** 2 / (2 * var)
        logp[k] = s
    if clase not in logp:
        return 0.0
    mx = max(logp.values())
    tot = sum(math.exp(v - mx) for v in logp.values())
    return math.exp(logp[clase] - mx) / tot


def estandarizar(X, ref=None):
    ref = ref or X
    cols = list(zip(*ref))
    ms = [media(c) for c in cols]
    ss = [desv(c) or 1.0 for c in cols]
    return [[(x - m) / s for x, m, s in zip(f, ms, ss)] for f in X], (ms, ss)


def aplicar_estandar(x, ms_ss):
    ms, ss = ms_ss
    return [(a - m) / s for a, m, s in zip(x, ms, ss)]


def brier(probs, y):
    return sum((p - t) ** 2 for p, t in zip(probs, y)) / len(y) if y else None


def auc(probs, y):
    pos = [p for p, t in zip(probs, y) if t == 1]
    neg = [p for p, t in zip(probs, y) if t == 0]
    if not pos or not neg:
        return None
    gana = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return gana / (len(pos) * len(neg))
