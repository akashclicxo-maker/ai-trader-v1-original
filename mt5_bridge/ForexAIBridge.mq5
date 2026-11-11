//+------------------------------------------------------------------+
//|                                                ForexAIBridge.mq5 |
//|           100% Autonomous Quantitative Trading Terminal Bridge   |
//+------------------------------------------------------------------+
#property copyright "Quantitative Multi-Regime Forex Engine"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>

input long   InpMagicNumber = 202611; // Quantitative Engine Magic Number
input int    InpSlippagePts = 50;     // Max Slippage in Points

CTrade g_trade;
string CMD_FILE   = "forex_ai_cmd.txt";
string ACK_FILE   = "forex_ai_ack.txt";
string STATE_FILE = "forex_ai_mt5_state.json";

//+------------------------------------------------------------------+
//| Check if a broker symbol is enabled for full trading & has quotes|
//+------------------------------------------------------------------+
bool IsSymbolTradable(string sym)
{
   if(!SymbolInfoInteger(sym, SYMBOL_EXIST))
      return false;

   SymbolSelect(sym, true);
   long tradeMode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED || tradeMode == SYMBOL_TRADE_MODE_CLOSEONLY)
      return false;

   for(int w = 0; w < 7; w++)
   {
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(bid > 0.0 && ask > 0.0)
         return true;
      Sleep(50);
   }
   return (SymbolInfoDouble(sym, SYMBOL_BID) > 0.0);
}

//+------------------------------------------------------------------+
//| Resolve standard 6-char pair (e.g. EURUSD) to tradable symbol    |
//+------------------------------------------------------------------+
string ResolveBrokerSymbol(string basePair)
{
   if(StringFind(_Symbol, basePair, 0) == 0 && IsSymbolTradable(_Symbol))
      return _Symbol;

   if(StringLen(_Symbol) > 6)
   {
      string chartSuffix = StringSubstr(_Symbol, 6);
      string candidate   = basePair + chartSuffix;
      if(IsSymbolTradable(candidate))
         return candidate;
   }

   string suffixes[] = {"+", ".pc", ".p", ".r", ".a", "m", ".pro", ".ecn", ""};
   for(int s = 0; s < ArraySize(suffixes); s++)
   {
      string candidate = basePair + suffixes[s];
      if(IsSymbolTradable(candidate))
         return candidate;
   }

   int totalMW = SymbolsTotal(true);
   for(int i = 0; i < totalMW; i++)
   {
      string sym = SymbolName(i, true);
      if(StringFind(sym, basePair, 0) == 0 && IsSymbolTradable(sym))
         return sym;
   }

   int totalAll = SymbolsTotal(false);
   for(int i = 0; i < totalAll; i++)
   {
      string sym = SymbolName(i, false);
      if(StringFind(sym, basePair, 0) == 0 && StringLen(sym) <= 12)
      {
         if(IsSymbolTradable(sym))
            return sym;
      }
   }

   return _Symbol;
}

//+------------------------------------------------------------------+
//| Pip size helper                                                  |
//+------------------------------------------------------------------+
double GetPipSize(string sym)
{
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0)
      return 0.10;
   if(digits == 5 || digits == 3)
      return pt * 10.0;
   return pt;
}

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpSlippagePts);
   EventSetMillisecondTimer(500);
   ExportTerminalState();
   PrintFormat("[ForexQuantBridge v3.0] Initialized on chart %s. Autonomous SL/Trailing & FILE_COMMON active.", _Symbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
//| Timer event every 500ms                                          |
//+------------------------------------------------------------------+
void OnTimer()
{
   ProcessIncomingCommands();
   AutonomousPositionDefense();
   ExportTerminalState();
}

//+------------------------------------------------------------------+
//| Tick event                                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   ProcessIncomingCommands();
   AutonomousPositionDefense();
}

//+------------------------------------------------------------------+
//| Native MQL5 Autonomous Break-Even & Dynamic Trailing Stop        |
//+------------------------------------------------------------------+
void AutonomousPositionDefense()
{
   int total = PositionsTotal();
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      string sym   = PositionGetString(POSITION_SYMBOL);
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double openP = PositionGetDouble(POSITION_PRICE_OPEN);
      double curP  = PositionGetDouble(POSITION_PRICE_CURRENT);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      if(openP <= 0.0 || tp <= 0.0) continue;

      int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double pip    = GetPipSize(sym);
      double tpDist = MathAbs(tp - openP);
      if(tpDist <= 0.0) continue;

      // 1R is approximately 50% of distance to TP2
      double oneR    = tpDist * 0.50;
      double cushion = 1.5 * pip;

      if(ptype == POSITION_TYPE_BUY)
      {
         double gain = curP - openP;
         // Dynamic Trailing at >= 1.5R
         if(gain >= oneR * 1.5)
         {
            double trailSL = NormalizeDouble(curP - (oneR * 0.75), digits);
            if(trailSL > sl + (2.0 * pip))
               g_trade.PositionModify(ticket, trailSL, tp);
         }
         // Break-Even + Cushion Lock at >= 1.0R
         else if(gain >= oneR)
         {
            double beSL = NormalizeDouble(openP + cushion, digits);
            if(sl < openP)
               g_trade.PositionModify(ticket, beSL, tp);
         }
      }
      else if(ptype == POSITION_TYPE_SELL)
      {
         double gain = openP - curP;
         // Dynamic Trailing at >= 1.5R
         if(gain >= oneR * 1.5)
         {
            double trailSL = NormalizeDouble(curP + (oneR * 0.75), digits);
            if(sl <= 0.0 || trailSL < sl - (2.0 * pip))
               g_trade.PositionModify(ticket, trailSL, tp);
         }
         // Break-Even + Cushion Lock at >= 1.0R
         else if(gain >= oneR)
         {
            double beSL = NormalizeDouble(openP - cushion, digits);
            if(sl <= 0.0 || sl > openP)
               g_trade.PositionModify(ticket, beSL, tp);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Process pipe-delimited commands from Python in FILE_COMMON       |
//+------------------------------------------------------------------+
void ProcessIncomingCommands()
{
   if(!FileIsExist(CMD_FILE, FILE_COMMON))
      return;

   int h = FileOpen(CMD_FILE, FILE_READ | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;

   string lines[];
   int count = 0;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) > 0)
      {
         ArrayResize(lines, count + 1);
         lines[count] = line;
         count++;
      }
   }
   FileClose(h);
   FileDelete(CMD_FILE, FILE_COMMON);

   for(int i = 0; i < count; i++)
      ExecuteCommandLine(lines[i]);
}

//+------------------------------------------------------------------+
//| Execute a single command line                                    |
//+------------------------------------------------------------------+
void ExecuteCommandLine(string line)
{
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 2)
      return;

   string action = parts[0];
   string cmdId  = parts[1];

   if(action == "OPEN" && n >= 7)
   {
      string rawPair = parts[2];
      string dir     = parts[3];
      double lots    = StringToDouble(parts[4]);
      double slPips  = StringToDouble(parts[5]);
      double tpPips  = StringToDouble(parts[6]);

      string sym = ResolveBrokerSymbol(rawPair);
      g_trade.SetTypeFillingBySymbol(sym);

      double minLot  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double maxLot  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
      double stepLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      if(minLot > 0 && lots < minLot) lots = minLot;
      if(maxLot > 0 && lots > maxLot) lots = maxLot;
      if(stepLot > 0) lots = MathFloor(lots / stepLot) * stepLot;
      if(lots <= 0.0) lots = 0.01;
      lots = NormalizeDouble(lots, 2);

      int    digits    = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double pt        = SymbolInfoDouble(sym, SYMBOL_POINT);
      double pip       = GetPipSize(sym);
      double ask       = SymbolInfoDouble(sym, SYMBOL_ASK);
      double bid       = SymbolInfoDouble(sym, SYMBOL_BID);
      long   stopsLvl  = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
      double minStopDist = MathMax((stopsLvl + 15) * pt, 5.0 * pip);

      double slDist = MathMax(slPips * pip, minStopDist);
      double tpDist = MathMax(tpPips * pip, minStopDist * 1.5);

      bool ok = false;
      if(dir == "BUY" && ask > 0.0)
      {
         double sl = (slPips > 0) ? NormalizeDouble(ask - slDist, digits) : 0.0;
         double tp = (tpPips > 0) ? NormalizeDouble(ask + tpDist, digits) : 0.0;
         ok = g_trade.Buy(lots, sym, ask, sl, tp, "QuantEngine-v3");
      }
      else if(dir == "SELL" && bid > 0.0)
      {
         double sl = (slPips > 0) ? NormalizeDouble(bid + slDist, digits) : 0.0;
         double tp = (tpPips > 0) ? NormalizeDouble(bid - tpDist, digits) : 0.0;
         ok = g_trade.Sell(lots, sym, bid, sl, tp, "QuantEngine-v3");
      }

      ulong dealTicket = g_trade.ResultOrder();
      PrintFormat("[ForexQuantBridge] %s %.2f %s (from %s) -> %s (Ticket=%I64u)",
                  dir, lots, sym, rawPair, g_trade.ResultRetcodeDescription(), dealTicket);
      WriteAck(cmdId, ok ? "EXECUTED" : "ERROR", dealTicket, g_trade.ResultRetcodeDescription());
   }
   else if(action == "FLATTEN")
   {
      int total = PositionsTotal();
      for(int i = total - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket > 0)
            g_trade.PositionClose(ticket);
      }
      WriteAck(cmdId, "FLATTENED", 0, "Closed all positions");
   }
   else if(action == "CLOSE" && n >= 3)
   {
      ulong ticket = (ulong)StringToInteger(parts[2]);
      bool ok = g_trade.PositionClose(ticket);
      WriteAck(cmdId, ok ? "CLOSED" : "ERROR", ticket, g_trade.ResultRetcodeDescription());
   }
   else if(action == "BREAKEVEN" && n >= 3)
   {
      ulong ticket = (ulong)StringToInteger(parts[2]);
      if(PositionSelectByTicket(ticket))
      {
         string sym       = PositionGetString(POSITION_SYMBOL);
         long   ptype     = PositionGetInteger(POSITION_TYPE);
         int    digits    = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         double pip       = GetPipSize(sym);
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double tp        = PositionGetDouble(POSITION_TP);
         double newSL     = (ptype == POSITION_TYPE_BUY) ? NormalizeDouble(openPrice + 1.0 * pip, digits)
                                                         : NormalizeDouble(openPrice - 1.0 * pip, digits);
         bool ok = g_trade.PositionModify(ticket, newSL, tp);
         WriteAck(cmdId, ok ? "BREAKEVEN_SET" : "ERROR", ticket, g_trade.ResultRetcodeDescription());
      }
   }
   else if(action == "MODIFY" && n >= 5)
   {
      ulong  ticket = (ulong)StringToInteger(parts[2]);
      double newSL  = StringToDouble(parts[3]);
      double newTP  = StringToDouble(parts[4]);
      if(PositionSelectByTicket(ticket))
      {
         string sym    = PositionGetString(POSITION_SYMBOL);
         int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         double curSL  = PositionGetDouble(POSITION_SL);
         double curTP  = PositionGetDouble(POSITION_TP);
         double slVal  = (newSL > 0.0) ? NormalizeDouble(newSL, digits) : curSL;
         double tpVal  = (newTP > 0.0) ? NormalizeDouble(newTP, digits) : curTP;
         bool ok = g_trade.PositionModify(ticket, slVal, tpVal);
         WriteAck(cmdId, ok ? "MODIFIED" : "ERROR", ticket, g_trade.ResultRetcodeDescription());
      }
   }
}

//+------------------------------------------------------------------+
//| Write execution ack                                              |
//+------------------------------------------------------------------+
void WriteAck(string cmdId, string status, ulong ticket, string message)
{
   int h = FileOpen(ACK_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   string payload = StringFormat(
      "{\"cmd_id\":\"%s\",\"status\":\"%s\",\"ticket\":%I64u,\"message\":\"%s\",\"time\":%I64d}",
      cmdId, status, ticket, message, (long)TimeCurrent()
   );
   FileWriteString(h, payload);
   FileClose(h);
}

//+------------------------------------------------------------------+
//| Export live MT5 account & open positions to JSON in FILE_COMMON  |
//+------------------------------------------------------------------+
void ExportTerminalState()
{
   int h = FileOpen(STATE_FILE, FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;

   long   login      = AccountInfoInteger(ACCOUNT_LOGIN);
   string server     = AccountInfoString(ACCOUNT_SERVER);
   string company    = AccountInfoString(ACCOUNT_COMPANY);
   string currency   = AccountInfoString(ACCOUNT_CURRENCY);
   double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
   double profit     = AccountInfoDouble(ACCOUNT_PROFIT);
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   bool   algoOk     = (bool)(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED));

   string json = "{";
   json += StringFormat("\"connected\":true,\"updated_unix\":%I64d,", (long)TimeLocal());
   json += StringFormat("\"login\":%I64d,\"server\":\"%s\",\"company\":\"%s\",\"currency\":\"%s\",", login, server, company, currency);
   json += StringFormat("\"balance\":%.2f,\"equity\":%.2f,\"floating_pnl\":%.2f,\"free_margin\":%.2f,", balance, equity, profit, freeMargin);
   json += StringFormat("\"algo_trading_enabled\":%s,", algoOk ? "true" : "false");
   json += "\"open_positions\":[";

   int total = PositionsTotal();
   bool first = true;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      string sym   = PositionGetString(POSITION_SYMBOL);
      long   ptype = PositionGetInteger(POSITION_TYPE);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      double openP = PositionGetDouble(POSITION_PRICE_OPEN);
      double curP  = PositionGetDouble(POSITION_PRICE_CURRENT);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double pnl   = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      string dir   = (ptype == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      bool   beSet = (ptype == POSITION_TYPE_BUY) ? (sl >= openP && sl > 0) : (sl <= openP && sl > 0);

      if(!first) json += ",";
      first = false;
      json += StringFormat(
         "{\"ticket_id\":\"MT5-%I64u\",\"raw_ticket\":%I64u,\"pair\":\"%s\",\"direction\":\"%s\",\"lots\":%.2f,\"remaining_lots\":%.2f,\"entry_price\":%.5f,\"current_price\":%.5f,\"stop_loss\":%.5f,\"tp1_1r\":%.5f,\"tp2_primary\":%.5f,\"breakeven_active\":%s,\"unrealized_pnl_usd\":%.2f}",
         ticket, ticket, sym, dir, vol, vol, openP, curP, sl, tp, tp,
         beSet ? "true" : "false",
         pnl
      );
   }
   json += "]}";
   FileWriteString(h, json);
   FileClose(h);
}
//+------------------------------------------------------------------+
