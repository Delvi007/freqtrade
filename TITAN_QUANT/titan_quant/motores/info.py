"""Motores de información y decisión: 6 MACROECONOMIC, 11 NEWS, 17 FUSION, 16 RESEARCH."""
import time

from .base import Motor, SinDatos, registrar, resultado
from .. import niveles


# --------------------------------------------------------------------------- 6
@registrar
class MotorMacro(Motor):
    numero, id, nombre = 6, "macro", "MACROECONOMIC INTELLIGENCE ENGINE"
    objetivo = "Detectar eventos macro (Fed, inflación, empleo, bancos centrales, geopolítica) y el pulso de tipos que afectan al activo."
    metodos = ("Escaneo de titulares por tipo de evento (módulo macro existente) filtrado por la clase del activo; "
               "variación de rendimientos a 13 semanas y 5 años como aproximación a expectativas de tipos. "
               "No hay calendario con consenso (no existe fuente gratuita verificada): se declara como dato faltante.")
    entradas = ("activo",)
    salidas = ("eventos", "eventos_alto_impacto_6h", "tasas")
    consumo = "bajo (red)"
    niveles = "Ventana de noticias macro: 24 / 48 / 72 / 96 h."

    def calcular(self, ctx):
        import macro
        clase = ctx["activo"].get("clase", "accion")
        horas = ctx["p"]["noticias_horas"]
        try:
            ev = macro.para_clase(clase, macro.escanear(horas))
        except Exception as e:
            raise SinDatos(f"Sin noticias macro ({type(e).__name__}).")
        try:
            tasas = macro.tasas()
        except Exception:
            tasas = []
        altos = [e for e in ev if e.get("alto") and e.get("edad_h", 99) <= 6]
        return {"salida": {"eventos": [{k: e.get(k) for k in ("nombre", "titulo", "fuente", "fecha", "edad_h", "alto", "mecanismo", "enlace")} for e in ev[:12]],
                           "eventos_alto_impacto_6h": len(altos), "tasas": tasas},
                "faltantes": ["calendario económico con consenso y hora exacta"] + ([] if tasas else ["rendimientos de bonos"]),
                "estado": "completado" if tasas else "simplificado"}


# --------------------------------------------------------------------------- 11
@registrar
class MotorNoticias(Motor):
    numero, id, nombre = 11, "news", "NEWS INTELLIGENCE ENGINE"
    objetivo = "Recoger y clasificar las noticias del activo y resumir su sesgo."
    metodos = ("Google News RSS por consulta del activo; clasificación por reglas de palabras completas (alcista/bajista/neutral, "
               "sensibilidad al dólar) y puntuación ponderada por frescura. Es transparente y revisable; NO entiende contexto, "
               "por eso pesa poco en la fusión y nunca se presenta como probabilidad.")
    entradas = ("activo",)
    salidas = ("noticias", "puntuacion", "relevantes")
    consumo = "bajo (red)"
    niveles = "Ventana: 24 / 48 / 72 / 96 h."

    def calcular(self, ctx):
        import agente
        try:
            lista = agente.noticias_activo(ctx["activo"], ctx["p"]["noticias_horas"])
        except Exception as e:
            raise SinDatos(f"No se pudieron leer noticias ({type(e).__name__}).")
        rel = [n for n in lista if n.get("impacto")]
        punt = agente.puntaje_noticias(rel)
        notas = [] if len(rel) >= agente.MIN_NOTICIAS else [f"Solo {len(rel)} noticias relevantes: no puntúan."]
        return {"salida": {"total": len(lista), "relevantes": len(rel), "puntuacion": punt,
                           "noticias": [{k: n.get(k) for k in ("titulo", "fuente", "fecha", "impacto", "motivo", "enlace")} for n in lista[:10]]},
                "notas": notas}


# --------------------------------------------------------------------------- 17
PESOS = {"technical": 0.30, "regime": 0.15, "ml": 0.20, "news": 0.10, "cross_asset": 0.10, "backtesting": 0.15}
UMBRAL = 0.35


def _clip(x, a=-1.0, b=1.0):
    return max(a, min(b, x))


@registrar
class MotorFusion(Motor):
    numero, id, nombre = 17, "fusion", "FUSION ENGINE"
    objetivo = "Combinar los motores en un escenario completo o declarar que NO hay oportunidad válida."
    metodos = ("Votos normalizados en [-1, 1] con pesos fijos y públicos (técnico 0,30, ML 0,20 solo si está calibrado, "
               "régimen 0,15, backtest 0,15, noticias 0,10, intermarket 0,10). Puertas de seguridad: calidad de datos, "
               "régimen de alta volatilidad, evento macro de alto impacto reciente, ventaja fuera de muestra y R/B ≥ 1,5. "
               "Si falla una puerta se entrega vigilancia prospectiva (zonas y condiciones), nunca una entrada inventada.")
    entradas = ("resultados de todos los motores",)
    salidas = ("escenario", "hay_oportunidad", "vigilancia")
    dependencias = ("data", "technical", "regime", "ml", "news", "cross_asset", "backtesting", "risk", "montecarlo", "macro", "microstructure", "statistical")

    def calcular(self, ctx):
        dat, tec = resultado(ctx, "data"), resultado(ctx, "technical")
        if not dat or not tec:
            raise SinDatos("Sin datos de precio o lectura técnica no hay escenario posible.")
        reg, ml, nw = resultado(ctx, "regime"), resultado(ctx, "ml"), resultado(ctx, "news")
        cr, bt, rk = resultado(ctx, "cross_asset"), resultado(ctx, "backtesting"), resultado(ctx, "risk")
        mc, mac = resultado(ctx, "montecarlo"), resultado(ctx, "macro")
        votos, justif = {}, []
        votos["technical"] = _clip(tec["puntuacion"] / max(3, tec["puntuacion_max"]))
        justif.append(f"Técnico: tendencia {tec['tendencia']} ({tec['puntuacion']:+d}); {', '.join(tec['razones'][:3])}.")
        if reg:
            votos["regime"] = 0.6 if reg["regimen"] == "tendencia_alcista" else -0.6 if reg["regimen"] == "tendencia_bajista" else 0.0
            justif.append(f"Régimen: {reg['regimen'].replace('_', ' ')} (eficiencia {reg['eficiencia'] or 0:.2f}, percentil de volatilidad {reg['percentil_volatilidad']:.0%}).")
        if ml and ml.get("calibrada"):
            votos["ml"] = _clip((ml["probabilidad_alcista"] - 0.5) * 4)
            justif.append(f"ML: P(alza) {ml['probabilidad_alcista']:.0%}, Brier fuera de muestra {ml['brier_oos']:.3f} vs base {ml['brier_base']:.3f}.")
        elif ml:
            justif.append("ML: sin ventaja fuera de muestra; excluido de la decisión.")
        if nw and nw.get("relevantes", 0) >= 3:
            votos["news"] = _clip(nw["puntuacion"] / 2)
            justif.append(f"Noticias: puntuación {nw['puntuacion']:+d} con {nw['relevantes']} relevantes.")
        if cr:
            votos["cross_asset"] = _clip(cr["sesgo_cruzado"])
            justif.append(f"Intermarket: lectura {cr['lectura']} (sesgo {cr['sesgo_cruzado']:+.2f}).")
        ventaja_bt = None
        if bt:
            fo = bt["fuera_muestra"]
            ventaja_bt = fo.get("n", 0) >= 20 and (fo.get("expectativa_r") or 0) > 0
            ex = bt["total"].get("expectativa_r") or 0
            votos["backtesting"] = 0.0      # valida la regla; no aporta dirección propia
            justif.append(f"Backtest: expectativa total {ex:+.2f} R; fuera de muestra {fo.get('expectativa_r') or 0:+.2f} R en {fo.get('n', 0)} operaciones.")
        usados = {k: v for k, v in votos.items() if k != "backtesting"}
        peso = sum(PESOS[k] for k in usados)
        puntuacion = sum(PESOS[k] * v for k, v in usados.items()) / peso if peso else 0.0
        direccion = "alcista" if puntuacion >= UMBRAL else "bajista" if puntuacion <= -UMBRAL else None

        s = ctx["serie"]
        precio = s["c"][-1]
        atr = tec["atr"]
        hz = niveles.HORIZONTES[ctx["horizonte"]]
        puertas = []
        cal = dat["calidad"]
        if cal["calidad"] == "baja" or cal["obsoleto"]:
            puertas.append("datos de baja calidad u obsoletos: " + "; ".join(cal["motivos"]))
        if reg and reg["regimen"] == "alta_volatilidad":
            puertas.append("régimen de alta volatilidad (percentil ≥ 90 %)")
        if mac and mac.get("eventos_alto_impacto_6h"):
            puertas.append(f"{mac['eventos_alto_impacto_6h']} evento(s) macro de alto impacto en las últimas 6 h")
        if ventaja_bt is False:
            puertas.append("la regla no muestra ventaja fuera de muestra (≥ 20 operaciones con expectativa > 0)")
        if direccion is None:
            puertas.append(f"señal combinada insuficiente ({puntuacion:+.2f}; se exige ±{UMBRAL})")

        sg = 1 if direccion == "alcista" else -1
        esc = None
        if direccion:
            niv_ref = tec["soportes"] if sg > 0 else tec["resistencias"]
            ent_lo, ent_hi = sorted([precio - sg * 0.25 * atr, precio + sg * 0.10 * atr])
            if niv_ref and abs(niv_ref[0]["precio"] - precio) <= atr:
                ext = niv_ref[0]["precio"]
                ent_lo, ent_hi = sorted([ext, precio])
            entrada = (ent_lo + ent_hi) / 2
            stop = entrada - sg * 1.5 * atr
            objetivos = tec["resistencias"] if sg > 0 else tec["soportes"]
            tp1 = next((o["precio"] for o in objetivos if abs(o["precio"] - entrada) >= 1.5 * abs(entrada - stop)), entrada + sg * 2.25 * atr)
            tp2 = entrada + sg * max(3.0 * atr, abs(tp1 - entrada) * 1.5)
            rb = abs(tp1 - entrada) / abs(entrada - stop) if entrada != stop else 0
            if round(rb, 2) < 1.5:
                puertas.append(f"riesgo/beneficio {rb:.2f} < 1,5")
            if ml and ml.get("calibrada"):
                prob = ml["probabilidad_alcista"] if sg > 0 else 1 - ml["probabilidad_alcista"]
                metodo = "modelo logístico calibrado fuera de muestra (Brier < tasa base)"
            elif mc:
                prob = mc["prob_cierre_superior"] if sg > 0 else 1 - mc["prob_cierre_superior"]
                metodo = "frecuencia simulada por Monte Carlo (NO calibrada: orientativa)"
            else:
                prob, metodo = None, "sin estimación fiable"
            vig_ts = int(time.time() + hz["vigencia_h"] * 3600)
            nivel_conf = tec["resistencias"][0]["precio"] if sg > 0 and tec["resistencias"] else tec["soportes"][0]["precio"] if sg < 0 and tec["soportes"] else entrada
            esc = {"direccion": direccion, "precio_referencia": precio, "zona_entrada": [ent_lo, ent_hi], "entrada": entrada,
                   "stop_loss": stop, "take_profit": [tp1, tp2], "riesgo_beneficio": rb,
                   "probabilidad": prob, "metodo_probabilidad": metodo,
                   "confirmacion": [f"Cierre de vela {hz['intervalo']} {'por encima' if sg > 0 else 'por debajo'} de {nivel_conf:.5g}",
                                    "RSI fuera de extremos (no comprar sobre 72 ni vender bajo 28)"],
                   "invalidacion": [f"Cierre {'por debajo' if sg > 0 else 'por encima'} de {stop:.5g}",
                                    "Evento macro de alto impacto antes de la entrada"],
                   "vigencia_hasta_ts": vig_ts, "horizonte": hz["nombre"],
                   "tamano": {k: rk.get(k) for k in ("unidades", "riesgo_importe", "nocional")} if rk else None}
        vigilancia = {"soportes": tec["soportes"], "resistencias": tec["resistencias"],
                      "condiciones": [f"Ruptura con cierre sobre {tec['resistencias'][0]['precio']:.5g} → revisar escenario alcista" if tec["resistencias"] else None,
                                      f"Ruptura con cierre bajo {tec['soportes'][0]['precio']:.5g} → revisar escenario bajista" if tec["soportes"] else None,
                                      "Esperar a que pase el evento macro" if mac and mac.get("eventos_alto_impacto_6h") else None]}
        vigilancia["condiciones"] = [x for x in vigilancia["condiciones"] if x]
        incert = []
        for mid, r in ctx["res"].items():
            for x in r.get("faltantes", []):
                incert.append(f"{r['nombre']}: {x}")
            if r["estado"] in ("error", "aplazado"):
                incert.append(f"{r['nombre']}: {r['estado']}")
        oportunidad = bool(esc) and not puertas
        return {"salida": {"hay_oportunidad": oportunidad, "puntuacion": puntuacion, "votos": votos, "pesos": PESOS,
                           "direccion": direccion, "escenario": esc if oportunidad else None,
                           "escenario_descartado": esc if (esc and not oportunidad) else None,
                           "motivo_sin_oportunidad": puertas, "justificacion": justif, "vigilancia": vigilancia,
                           "incertidumbre": incert,
                           "mensaje": "Escenario válido" if oportunidad else "No hay oportunidad válida ahora. Se entregan zonas y condiciones de vigilancia."}}


# --------------------------------------------------------------------------- 16
@registrar
class MotorInvestigacion(Motor):
    numero, id, nombre = 16, "research", "RESEARCH ENGINE"
    objetivo = "Redactar el informe del análisis: qué dicen los datos, qué falta y qué vigilar."
    metodos = "Síntesis determinista de las salidas de los motores (sin texto inventado); profundidad según el nivel."
    entradas = ("resultados de todos los motores",)
    salidas = ("informe",)
    dependencias = ("fusion",)
    niveles = "resumen / estándar / detallada / exhaustiva."

    def calcular(self, ctx):
        fu = resultado(ctx, "fusion")
        if not fu:
            raise SinDatos("Sin fusión no hay informe.")
        a, prof = ctx["activo"], ctx["p"]["investigacion"]
        dat = resultado(ctx, "data") or {}
        lineas = [f"# {a['nombre']} ({a['simbolo']}) — {niveles.HORIZONTES[ctx['horizonte']]['nombre']}",
                  f"Datos: {dat.get('proveedor', '?')} · {dat.get('tipo', '?')} · {dat.get('velas', '?')} velas de {dat.get('intervalo', '?')} · calidad {((dat.get('calidad') or {}).get('calidad', '?'))}.",
                  "", "## Conclusión", fu["mensaje"] + (f" Dirección: {fu['direccion']}." if fu["direccion"] else "")]
        if fu["motivo_sin_oportunidad"]:
            lineas += ["", "## Por qué no hay entrada"] + [f"- {m}" for m in fu["motivo_sin_oportunidad"]]
        lineas += ["", "## Evidencia por motor"] + [f"- {j}" for j in fu["justificacion"]]
        if prof in ("estandar", "detallada", "exhaustiva"):
            st = resultado(ctx, "statistical")
            if st:
                lineas += ["", "## Estadística"] + [f"- {x}" for x in st["lectura"]]
            rk = resultado(ctx, "risk")
            if rk:
                lineas.append(f"- VaR 95 % a {rk['horizonte_velas']} velas: {rk['var95_pct']:.2f} % · ES 95 %: {rk['es95_pct']:.2f} %")
        if prof in ("detallada", "exhaustiva"):
            mc = resultado(ctx, "montecarlo")
            if mc:
                q = mc["precio_cuantiles"]
                lineas += ["", "## Rango simulado al horizonte", f"- P5 {q[5]:.5g} · P50 {q[50]:.5g} · P95 {q[95]:.5g} ({mc['simulaciones']} simulaciones)"]
            nw = resultado(ctx, "news")
            if nw and nw["noticias"]:
                lineas += ["", "## Titulares"] + [f"- {n['titulo']} ({n['fuente']})" for n in nw["noticias"][:5]]
        if prof == "exhaustiva":
            cr = resultado(ctx, "cross_asset")
            if cr:
                lineas += ["", "## Intermarket"] + [f"- {x['referencia']}: ρ={x['correlacion']:+.2f}" for x in cr["correlaciones"][:8] if x["correlacion"] is not None]
        if fu["incertidumbre"]:
            lineas += ["", "## Incertidumbre y datos faltantes"] + [f"- {x}" for x in fu["incertidumbre"][:15]]
        lineas += ["", "_Análisis informativo. El rendimiento pasado no garantiza resultados futuros._"]
        return {"salida": {"informe_md": "\n".join(lineas), "profundidad": prof}}
