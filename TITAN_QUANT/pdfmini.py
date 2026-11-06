# -*- coding: utf-8 -*-
"""Generador mínimo de PDF (solo biblioteca estándar): texto, tablas, cajas y gráficos."""
import unicodedata
import zlib

W, H, M = 595.0, 842.0, 40.0
_W = ([278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 +
      [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722,
       778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500,
       556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500,
       500, 500, 334, 260, 334, 584])
_REEMP = {"→": "->", "←": "<-", "≈": "~", "−": "-", "–": "-", "—": "-", "≥": ">=", "≤": "<=", "▲": "(+)",
          "▼": "(-)", "…": "...", "“": '"', "”": '"', "‘": "'", "’": "'", "×": "x", "✓": "+", "✗": "-", "⚠️": "!"}

def limpia(s):
    for k, v in _REEMP.items():
        s = s.replace(k, v)
    return "".join(ch for ch in s if ch.encode("cp1252", "ignore"))

def _ancho_car(ch):
    if 32 <= ord(ch) <= 126:
        return _W[ord(ch) - 32]
    base = unicodedata.normalize("NFD", ch)[0]
    return _W[ord(base) - 32] if 32 <= ord(base) <= 126 else 556

def ancho(s, size, bold=False):
    return sum(_ancho_car(c) for c in limpia(s)) * size / 1000 * (1.07 if bold else 1)

def _rgb(c):
    return f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}"

AZUL, GRIS, CLARO = (0.09, 0.16, 0.28), (0.35, 0.38, 0.42), (0.94, 0.95, 0.97)
VERDE, ROJO, NARANJA = (0.10, 0.50, 0.25), (0.75, 0.15, 0.15), (0.90, 0.50, 0.10)

class Pdf:
    def __init__(self, pie=""):
        self.paginas, self.pie = [], pie
        self.nueva()

    def nueva(self):
        self.ops = []
        self.paginas.append(self.ops)
        self.y = H - M

    def hueco(self, alto):
        if self.y - alto < M + 10:
            self.nueva()

    def texto(self, x, y, s, size=9, bold=False, color=(0, 0, 0)):
        s = limpia(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        self.ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf {_rgb(color)} rg {x:.1f} {y:.1f} Td ({s}) Tj ET")

    def rect(self, x, y, w, h, fill=None, stroke=None, grosor=0.5):
        o = ""
        if fill:
            o += f"{_rgb(fill)} rg "
        if stroke:
            o += f"{_rgb(stroke)} RG {grosor} w "
        self.ops.append(f"{o}{x:.1f} {y:.1f} {w:.1f} {h:.1f} re {'B' if fill and stroke else 'f' if fill else 'S'}")

    def linea(self, x1, y1, x2, y2, color=(0, 0, 0), grosor=0.6, dash=None):
        d = f"[{dash[0]} {dash[1]}] 0 d " if dash else "[] 0 d "
        self.ops.append(f"{_rgb(color)} RG {grosor} w {d}{x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S [] 0 d")

    def polilinea(self, pts, color, grosor=1.2):
        o = f"{_rgb(color)} RG {grosor} w {pts[0][0]:.1f} {pts[0][1]:.1f} m "
        o += " ".join(f"{x:.1f} {y:.1f} l" for x, y in pts[1:])
        self.ops.append(o + " S")

    def envolver(self, s, size, ancho_max, bold=False):
        out = []
        for parrafo in str(s).split("\n"):
            linea = ""
            for pal in parrafo.split(" "):
                prueba = (linea + " " + pal).strip()
                if linea and ancho(prueba, size, bold) > ancho_max:
                    out.append(linea)
                    linea = pal
                else:
                    linea = prueba
            out.append(linea)
        return out

    def parrafo(self, s, size=9, bold=False, color=(0, 0, 0), x=M, ancho_max=W - 2 * M, despues=4):
        for ln in self.envolver(s, size, ancho_max, bold):
            self.hueco(size * 1.4)
            self.y -= size * 1.35
            self.texto(x, self.y, ln, size, bold, color)
        self.y -= despues

    def seccion(self, titulo):
        self.hueco(60)
        self.y -= 6
        self.rect(M, self.y - 14, W - 2 * M, 16, fill=AZUL)
        self.texto(M + 6, self.y - 10, titulo, 9.5, True, (1, 1, 1))
        self.y -= 22

    def tabla(self, filas, anchos, cabecera=True, size=8.2):
        """filas: listas de celdas; cada celda es str o (str, color, negrita)."""
        def spec(c):
            return (c, (0, 0, 0), False) if isinstance(c, str) else (c[0], c[1] if len(c) > 1 else (0, 0, 0), c[2] if len(c) > 2 else False)
        for i, fila in enumerate(filas):
            enc = cabecera and i == 0
            celdas = [spec(c) for c in fila]
            lineas = [self.envolver(t, size, a - 8, enc or neg) for (t, _, neg), a in zip(celdas, anchos)]
            alto = max(len(l) for l in lineas) * size * 1.25 + 6
            self.hueco(alto + 4)
            top = self.y
            if enc:
                self.rect(M, top - alto, sum(anchos), alto, fill=GRIS)
            elif i % 2 == 0:
                self.rect(M, top - alto, sum(anchos), alto, fill=CLARO)
            x = M
            for (t, col, neg), ls, a in zip(celdas, lineas, anchos):
                yy = top - 3 - size
                for ln in ls:
                    self.texto(x + 4, yy, ln, size, enc or neg, (1, 1, 1) if enc else col)
                    yy -= size * 1.25
                x += a
            self.linea(M, top - alto, M + sum(anchos), top - alto, (0.8, 0.8, 0.82), 0.4)
            self.y = top - alto
        self.y -= 6

    def grafico_lineas(self, serie, niveles, titulo, alto=150, etiqueta_ini="hace 48 h", etiqueta_fin="ahora"):
        self.hueco(alto + 30)
        self.texto(M, self.y - 9, titulo, 8.5, True, GRIS)
        x0, y1, w = M + 38, self.y - 16, W - 2 * M - 46
        y0 = y1 - alto
        vals = list(serie) + [n[0] for n in niveles]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.06 or 1
        lo, hi = lo - pad, hi + pad
        ys = lambda v: y0 + (v - lo) / (hi - lo) * alto
        self.rect(x0, y0, w, alto, stroke=(0.8, 0.8, 0.82))
        for v, nom, col in niveles:
            self.linea(x0, ys(v), x0 + w, ys(v), col, 0.8, (4, 3))
            self.texto(x0 + 3, ys(v) + 2, f"{nom} {v:,.2f}", 7, True, col)
        paso = w / (len(serie) - 1)
        pts = [(x0 + i * paso, ys(v)) for i, v in enumerate(serie)]
        self.polilinea(pts, (0.12, 0.35, 0.75), 1.3)
        self.rect(pts[-1][0] - 2, pts[-1][1] - 2, 4, 4, fill=NARANJA)
        self.texto(x0 - 36, y1 - 7, f"{hi:,.1f}", 6.5, False, GRIS)
        self.texto(x0 - 36, y0, f"{lo:,.1f}", 6.5, False, GRIS)
        self.texto(x0, y0 - 9, etiqueta_ini, 6.5, False, GRIS)
        self.texto(x0 + w - ancho(etiqueta_fin, 6.5), y0 - 9, etiqueta_fin, 6.5, False, GRIS)
        self.y = y0 - 16

    def grafico_barras(self, datos, titulo, alto=90):
        """datos: lista de (etiqueta, valor, color)."""
        self.hueco(alto + 30)
        self.texto(M, self.y - 9, titulo, 8.5, True, GRIS)
        x0, y1, w = M, self.y - 14, W - 2 * M
        y0 = y1 - alto
        mx = max(v for _, v, _ in datos) or 1
        bw = w / len(datos)
        self.linea(x0, y0, x0 + w, y0, (0.6, 0.6, 0.62), 0.6)
        for i, (et, v, col) in enumerate(datos):
            h = v / mx * (alto - 8)
            self.rect(x0 + i * bw + 1.2, y0, bw - 2.4, h, fill=col)
            if i % 3 == 0 or col != (0.55, 0.62, 0.72):
                self.texto(x0 + i * bw, y0 - 8, et, 6, False, GRIS)
        self.y = y0 - 14

    def construir(self):
        n = len(self.paginas)
        for i, ops in enumerate(self.paginas):
            s = limpia(f"{self.pie}   pag. {i + 1}/{n}")
            ops.append(f"BT /F1 7 Tf {_rgb(GRIS)} rg {M:.1f} 22 Td ({s.replace('(', '').replace(')', '')}) Tj ET")
        cuerpos = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        for i, ops in enumerate(self.paginas):
            datos = zlib.compress("\n".join(ops).encode("cp1252", "replace"))
            cid, pid = 5 + 2 * i, 6 + 2 * i
            cuerpos.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(datos) + datos + b"\nendstream")
            cuerpos.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.0f} {H:.0f}] /Resources << /Font << /F1 3 0 R "
                            f"/F2 4 0 R >> >> /Contents {cid} 0 R >>").encode())
            kids.append(f"{pid} 0 R")
        cuerpos[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>".encode()
        out, offs = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, c in enumerate(cuerpos, 1):
            offs.append(len(out))
            out += f"{i} 0 obj\n".encode() + c + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(cuerpos) + 1}\n0000000000 65535 f \n".encode()
        for o in offs:
            out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(cuerpos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
