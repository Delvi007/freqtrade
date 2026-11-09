// TITAN · Líneas de STOP LOSS y TAKE PROFIT bien visibles (indicador para cTrader Automate)
//
// Dibuja sobre el gráfico, con el grosor elegido (3 px por defecto), el stop loss, el take profit y la entrada de
// TODAS las posiciones abiertas y órdenes pendientes de la cuenta en el símbolo del gráfico (las del bot TITAN y las
// manuales). Se actualiza solo cuando se abre, modifica (trailing) o cierra una posición. Solo lee: no envía ni
// modifica órdenes (AccessRights.None).
//
// Instalación: cTrader → Automate → Indicadores → Nuevo → pegar este código → Build (Ctrl+B).
// Uso en todos los mercados: añadirlo a un gráfico y guardar la plantilla del gráfico; aplicar esa plantilla a los demás.
using System.Linq;
using cAlgo.API;

namespace cAlgo.Indicators
{
    [Indicator(IsOverlay = true, AccessRights = AccessRights.None)]
    public class TitanLineasSLTP : Indicator
    {
        [Parameter("Grosor de línea (px)", DefaultValue = 3, MinValue = 1, MaxValue = 6)]
        public int Grosor { get; set; }

        [Parameter("Color stop loss", DefaultValue = "Red")]
        public string ColorStop { get; set; }

        [Parameter("Color take profit", DefaultValue = "LimeGreen")]
        public string ColorObjetivo { get; set; }

        [Parameter("Color entrada", DefaultValue = "DodgerBlue")]
        public string ColorEntrada { get; set; }

        [Parameter("Mostrar entrada", DefaultValue = true)]
        public bool MostrarEntrada { get; set; }

        [Parameter("Mostrar etiquetas", DefaultValue = true)]
        public bool MostrarEtiquetas { get; set; }

        private const string Prefijo = "TITAN_SLTP_";

        protected override void Initialize()
        {
            Positions.Opened += _ => Dibujar();
            Positions.Closed += _ => Dibujar();
            Positions.Modified += _ => Dibujar();
            PendingOrders.Created += _ => Dibujar();
            PendingOrders.Modified += _ => Dibujar();
            PendingOrders.Cancelled += _ => Dibujar();
            PendingOrders.Filled += _ => Dibujar();
            Dibujar();
        }

        public override void Calculate(int index)
        {
            if (IsLastBar)
                Dibujar();          // mantiene las etiquetas junto a la última vela
        }

        private void Dibujar()
        {
            foreach (var nombre in Chart.Objects.Where(o => o.Name.StartsWith(Prefijo)).Select(o => o.Name).ToList())
                Chart.RemoveObject(nombre);

            foreach (var p in Positions.Where(p => p.SymbolName == SymbolName))
                Lineas("P" + p.Id, p.TradeType, p.EntryPrice, p.StopLoss, p.TakeProfit, "#" + p.Id);

            foreach (var o in PendingOrders.Where(o => o.SymbolName == SymbolName))
                Lineas("O" + o.Id, o.TradeType, o.TargetPrice, o.StopLoss, o.TakeProfit, "orden #" + o.Id);
        }

        private void Lineas(string id, TradeType tipo, double entrada, double? stop, double? objetivo, string etiqueta)
        {
            var lado = tipo == TradeType.Buy ? "COMPRA" : "VENTA";
            if (stop.HasValue)
                Linea(id + "_SL", stop.Value, ColorStop, LineStyle.Solid, "SL " + lado + " " + etiqueta + "  " + Formato(stop.Value));
            if (objetivo.HasValue)
                Linea(id + "_TP", objetivo.Value, ColorObjetivo, LineStyle.Solid, "TP " + lado + " " + etiqueta + "  " + Formato(objetivo.Value));
            if (MostrarEntrada)
                Linea(id + "_EN", entrada, ColorEntrada, LineStyle.DotsRare, "Entrada " + lado + " " + etiqueta + "  " + Formato(entrada));
        }

        private void Linea(string nombre, double precio, string color, LineStyle estilo, string texto)
        {
            var c = Color.FromName(color);
            var linea = Chart.DrawHorizontalLine(Prefijo + nombre, precio, c, Grosor, estilo);
            linea.IsInteractive = false;           // no se puede arrastrar por error
            if (MostrarEtiquetas)
            {
                var t = Chart.DrawText(Prefijo + nombre + "_T", texto, Bars.Count - 1, precio, c);
                t.VerticalAlignment = VerticalAlignment.Top;
                t.HorizontalAlignment = HorizontalAlignment.Left;
                t.FontSize = 11;
                t.IsInteractive = false;
            }
        }

        private string Formato(double precio)
        {
            return precio.ToString("F" + Symbol.Digits);
        }
    }
}
