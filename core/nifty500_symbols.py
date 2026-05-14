"""
nifty500_symbols.py — Representative Nifty 500 universe for yfinance (.NS suffix).

This list covers the major Nifty 50, Nifty Next 50, and prominent Midcap 150 members.
Update quarterly as the index composition changes (NSE announces rebalancing in March/June/Sep/Dec).
Source reference: https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500
"""

NIFTY500_SYMBOLS = [
    # ── Nifty 50 ──────────────────────────────────────────────────────────────
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "BAJFINANCE.NS", "WIPRO.NS", "NESTLEIND.NS", "ULTRACEMCO.NS", "POWERGRID.NS",
    "NTPC.NS", "SUNPHARMA.NS", "ONGC.NS", "TECHM.NS", "HCLTECH.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "M&M.NS",
    "BAJAJFINSV.NS", "INDUSINDBK.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS",
    "EICHERMOT.NS", "HEROMOTOCO.NS", "BPCL.NS", "COALINDIA.NS", "GRASIM.NS",
    "HINDALCO.NS", "BRITANNIA.NS", "DABUR.NS", "PIDILITIND.NS", "BERGEPAINT.NS",
    "TATACONSUM.NS", "GODREJCP.NS", "APOLLOHOSP.NS", "BAJAJ-AUTO.NS", "TATAMOTORS.NS",

    # ── Nifty Next 50 ─────────────────────────────────────────────────────────
    "DMART.NS", "HDFCLIFE.NS", "SBILIFE.NS", "ICICIPRULI.NS", "ADANIGREEN.NS",
    "IRCTC.NS", "LICI.NS", "ZOMATO.NS", "HAL.NS", "BEL.NS",
    "SIEMENS.NS", "HAVELLS.NS", "VOLTAS.NS", "DLF.NS", "OFSS.NS",
    "CHOLAFIN.NS", "MUTHOOTFIN.NS", "PFC.NS", "RECLTD.NS", "SBICARD.NS",
    "TRENT.NS", "LUPIN.NS", "TORNTPHARM.NS", "GODREJPROP.NS", "PIIND.NS",
    "MPHASIS.NS", "LTIM.NS", "BANDHANBNK.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS",
    "AMBUJACEM.NS", "BANKBARODA.NS", "CANBK.NS", "PNB.NS", "GAIL.NS",
    "IOC.NS", "CONCOR.NS", "NMDC.NS", "SAIL.NS", "BOSCHLTD.NS",
    "PAGEIND.NS", "MARICO.NS", "UBL.NS", "TVSMOTOR.NS", "IRFC.NS",
    "HINDPETRO.NS", "PETRONET.NS", "SHREECEM.NS", "VEDL.NS", "INDUSTOWER.NS",

    # ── Financials / NBFC / Insurance ─────────────────────────────────────────
    "BAJAJHLDNG.NS", "HDFCAMC.NS", "ICICIGI.NS", "STARHEALTH.NS", "MANAPPURAM.NS",
    "M&MFIN.NS", "LICHSGFIN.NS", "POONAWALLA.NS", "RBLBANK.NS", "YESBANK.NS",
    "IDBI.NS", "UNIONBANK.NS", "CENTRALBK.NS", "IOB.NS", "MASFIN.NS",
    "ISEC.NS",

    # ── Technology / IT ───────────────────────────────────────────────────────
    "LTTS.NS", "COFORGE.NS", "PERSISTENT.NS", "KPITTECH.NS", "TATACOMM.NS",
    "MPHASIS.NS", "HEXAWARE.NS", "BSOFT.NS", "ZENSAR.NS", "NIITLTD.NS",
    "HAPPSTMNDS.NS", "TANLA.NS",

    # ── Pharma / Healthcare ───────────────────────────────────────────────────
    "AUROPHARMA.NS", "ALKEM.NS", "IPCALAB.NS", "BIOCON.NS", "GRANULES.NS",
    "GLENMARK.NS", "LAURUSLABS.NS", "ABBOTINDIA.NS", "PFIZER.NS", "SANOFI.NS",
    "TORNTPHARM.NS", "WOCKPHARMA.NS", "SUNPHARMA.NS", "MAXHEALTH.NS",
    "FORTIS.NS", "LALPATHLAB.NS", "METROPOLIS.NS",

    # ── Automobiles ───────────────────────────────────────────────────────────
    "ASHOKLEY.NS", "ESCORTS.NS", "BALKRISIND.NS", "MRF.NS", "APOLLOTYRE.NS",
    "CEAT.NS", "MOTHERSON.NS", "EXIDEIND.NS", "AMARAJABAT.NS", "FORCE.NS",
    "TIINDIA.NS",

    # ── Capital Goods / Engineering ───────────────────────────────────────────
    "ABB.NS", "CUMMINSIND.NS", "BHEL.NS", "THERMAX.NS", "HONAUT.NS",
    "CGPOWER.NS", "POLYCAB.NS", "KEI.NS", "GRINDWELL.NS", "SCHAEFFLER.NS",
    "TIMKEN.NS", "ELGIEQUIP.NS", "KIRLOSENG.NS", "INOXWIND.NS",

    # ── Metals & Mining ───────────────────────────────────────────────────────
    "WELCORP.NS", "RATNAMANI.NS", "APL.NS", "APLAPOLLO.NS", "JINDALSAW.NS",
    "HINDCOPPER.NS", "MOIL.NS", "NATIONALUM.NS",

    # ── Cement ────────────────────────────────────────────────────────────────
    "JKCEMENT.NS", "RAMCOCEM.NS", "DALMIACEME.NS", "BIRLACEM.NS",
    "HEIDELBERG.NS", "NUVOCO.NS",

    # ── Energy / Power ────────────────────────────────────────────────────────
    "TATAPOWER.NS", "NHPC.NS", "SJVN.NS", "TORNTPOWER.NS", "CESC.NS",
    "JSWENERGY.NS", "ADANIPOWER.NS", "NLCINDIA.NS", "ADANITRANS.NS",
    "IEX.NS", "HUDCO.NS",

    # ── Oil & Gas ─────────────────────────────────────────────────────────────
    "GSPL.NS", "MGL.NS", "IGL.NS", "GUJGASLTD.NS", "AEGASIND.NS",
    "CASTROLIND.NS",

    # ── FMCG / Consumer ───────────────────────────────────────────────────────
    "COLPAL.NS", "EMAMILTD.NS", "BAJAJCON.NS", "RADICO.NS", "GILLETTE.NS",
    "JYOTHYLAB.NS", "ZYDUSWELL.NS", "KRBL.NS",

    # ── Retail / E-commerce ───────────────────────────────────────────────────
    "NYKAA.NS", "DMART.NS", "JUBLFOOD.NS", "DEVYANI.NS", "SAPPHIRE.NS",
    "TRENT.NS", "VMART.NS",

    # ── Real Estate ───────────────────────────────────────────────────────────
    "PRESTIGE.NS", "OBEROIRLTY.NS", "SOBHA.NS", "BRIGADE.NS", "PHOENIXLTD.NS",
    "GODREJPROP.NS", "MAHLIFE.NS",

    # ── Chemicals / Specialty ─────────────────────────────────────name──────────
    "DEEPAKNTR.NS", "COROMANDEL.NS", "AAVAS.NS", "CLEAN.NS", "NAVINFLUOR.NS",
    "FLUOROCHEM.NS", "FINPIPE.NS", "PCBL.NS", "NOCIL.NS", "TATACHEM.NS",
    "GNFC.NS", "FACT.NS", "CHAMBLFERT.NS",

    # ── Logistics / Transport ─────────────────────────────────────────────────
    "DELHIVERY.NS", "BLUEDART.NS", "MAHINDLOG.NS", "GATI.NS", "RITES.NS",
    "IRCON.NS", "NBCC.NS",

    # ── Aviation / Hotels ─────────────────────────────────────────────────────
    "INDIGO.NS", "INDHOTEL.NS", "LEMONTREE.NS", "CHALET.NS",

    # ── Media / Telecom ───────────────────────────────────────────────────────
    "ZEEL.NS", "SUNTV.NS", "PVR.NS", "PVRINOX.NS", "TATAELXSI.NS",

    # ── Jewellery ─────────────────────────────────────────────────────────────
    "KALYANKJIL.NS", "RAJESHEXPO.NS", "SENCO.NS",

    # ── Miscellaneous ─────────────────────────────────────────────────────────
    "CRISIL.NS", "MFSL.NS", "SUNDARMFIN.NS", "DIXON.NS",
]

# De-duplicate while preserving order
_seen = set()
NIFTY500_SYMBOLS = [s for s in NIFTY500_SYMBOLS if s not in _seen and not _seen.add(s)]
