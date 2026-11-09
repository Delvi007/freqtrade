"""Orquestador del bot de binarias: une señal, autonomía, riesgo, adaptador y base de datos.

El orquestador NO conoce credenciales. Recibe un adaptador ya construido (AdaptadorPractica).
Reglas:
  * Una orden 'desconocida' bloquea nuevas órdenes automáticas hasta conciliarla (no se reintenta).
  * La parada de emergencia apaga el adaptador y el gestor de riesgo a la vez.
  * El resultado de cada operación alimenta el gestor de riesgo (pérdida diaria, racha, drawdown).
"""
from titan_quant.binaria_bot.autonomia import Autonomia, decidir_accion
from titan_quant.binaria_bot.riesgo import GestorRiesgo


class BotBinaria:
    def __init__(self, adaptador, gestor: GestorRiesgo, almacen, autonomia=Autonomia.OBSERVAR,
                 evidencia_ok=False):
        self.adaptador = adaptador
        self.gestor = gestor
        self.almacen = almacen
        self.autonomia = autonomia
        self.evidencia_ok = evidencia_ok
        self.bloqueo_conciliacion = False

    def parada_emergencia(self, motivo="parada de emergencia del operador"):
        self.adaptador.apagar_nuevas()
        self.gestor.apagar(motivo)

    def confirmar_conciliacion_manual(self):
        """Solo el operador, tras revisar en PRACTICE que la orden desconocida quedó resuelta."""
        self.bloqueo_conciliacion = False

    def reanudar(self):
        """Reactivación explícita. Requiere que no haya órdenes sin conciliar."""
        if self.bloqueo_conciliacion:
            return False, "hay una orden sin conciliar: concíliala antes de reanudar"
        self.adaptador.reactivar()
        self.gestor.reactivar()
        return True, ""

    def procesar_senal(self, ts, activo, direccion, monto, confirmado=False):
        """Devuelve un dict con la acción tomada. Nunca lanza excepciones por el broker."""
        ok, motivo = self.gestor.puede_operar(monto)
        if not ok:
            sid = self.almacen.registrar_senal(ts, activo, direccion, "bloqueada", motivo)
            return {"accion": "bloqueada", "motivo": motivo, "senal_id": sid}

        if self.bloqueo_conciliacion:
            sid = self.almacen.registrar_senal(ts, activo, direccion, "bloqueada",
                                               "orden previa sin conciliar")
            return {"accion": "bloqueada", "motivo": "orden previa sin conciliar", "senal_id": sid}

        accion = decidir_accion(self.autonomia, self.evidencia_ok, confirmado)
        sid = self.almacen.registrar_senal(ts, activo, direccion, accion)
        if accion != "enviar":
            return {"accion": accion, "motivo": "", "senal_id": sid}

        r = self.adaptador.enviar(activo, direccion, monto)
        if r.estado == "enviada":
            oid = self.almacen.registrar_orden(sid, ts, activo, direccion, monto, "enviada", r.orden_id)
            return {"accion": "enviada", "motivo": "", "senal_id": sid, "orden_id": oid,
                    "orden_broker": r.orden_id}
        if r.estado == "desconocida":
            # Estado no confirmado: NO reintentar. Bloquear hasta conciliar y detener automáticos.
            self.bloqueo_conciliacion = True
            self.gestor.apagar("orden desconocida: conciliar en PRACTICE antes de continuar")
            oid = self.almacen.registrar_orden(sid, ts, activo, direccion, monto, "desconocida",
                                               None, r.motivo)
            return {"accion": "desconocida", "motivo": r.motivo, "senal_id": sid, "orden_id": oid}
        oid = self.almacen.registrar_orden(sid, ts, activo, direccion, monto, "rechazada", None, r.motivo)
        return {"accion": "rechazada", "motivo": r.motivo, "senal_id": sid, "orden_id": oid}

    def liquidar_pendientes(self):
        """Consulta el resultado de órdenes enviadas. Devuelve la lista de órdenes cerradas."""
        cerradas = []
        for p in self.almacen.pendientes():
            if not p["orden_broker"]:
                continue
            res = self.adaptador.liquidar(p["orden_broker"])
            if res is None:
                continue
            estado, neto = res
            self.almacen.cerrar_orden(p["id"], estado, neto)
            cerradas.append((p["id"], estado, neto))
            self.gestor.registrar(neto)
        return cerradas
