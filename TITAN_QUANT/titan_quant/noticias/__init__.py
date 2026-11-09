"""TITAN QUANT · NEWS INTELLIGENCE — centro de inteligencia informativa financiera.

Módulos:
    catalogo.py     catálogo inicial de fuentes (URL verificada el 09/11/2026), acceso/gratuidad y calificación TITAN
    almacen.py      base propia datos/noticias/noticias.db (fuentes, pruebas, noticias, grupos, calendario, uso por motor)
    recolector.py   recopilación RSS/Atom/JSON con frecuencia por fuente, caché condicional, reintentos y robots.txt
    analisis.py     entidades, activos, países, categoría, sentimiento, tono monetario, rumores, urgencia y puntuaciones
    calendario.py   calendario económico (fuente secundaria pública) y alertas configurables
    integracion.py  entrega a cada motor SOLO la información relevante y registra qué noticia usó cada análisis

Principios: el contenido externo es DATO no confiable (nunca instrucciones); no se copian artículos completos
(solo titular, resumen breve y enlace); una fuente no figura como «conectada» hasta superar la prueba de recepción;
una noticia nunca es por sí sola una señal de compra o venta.
"""
