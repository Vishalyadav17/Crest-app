INDEX_NIFTY50   = "^NSEI"
INDEX_BANKNIFTY = "^NSEBANK"
INDEX_NIFTY500  = "^CRSLDX"          # was "^CNX500" — wrong on Yahoo
INDEX_MIDCAP    = "^CNXMID"           # NIFTY MIDCAP 100
INDEX_SMALLCAP  = "^CNXSC"            # NIFTYSMLCAP100 — confirmed working

SECTOR_TICKERS = {
    "FMCG":          "^CNXFMCG",
    "IT":            "^CNXIT",
    "AUTO":          "^CNXAUTO",
    "METAL":         "^CNXMETAL",
    "PHARMA":        "^CNXPHARMA",
    "ENERGY":        "^CNXENERGY",
    "INFRA":         "^CNXINFRA",
    "MEDIA":         "^CNXMEDIA",
    "REALTY":        "^CNXREALTY",
    "BANK":          "^NSEBANK",
    "PSU_BANK":      "^CNXPSUBANK",
    "FIN_SERVICES":  "NIFTY_FIN_SERVICE.NS",      # confirmed 247 rows of history
    "SERVICES":      "^CNXSERVICE",               # NIFTY Services Sector — 491 rows confirmed
    # OIL_GAS / CONSR_DURBL / HEALTHCARE: Yahoo Finance has no historical series for
    # these; fetched from NSE allIndices API instead (see sector_heatmap.py).
    # No EMA/momentum computed for those 3 — just daily % change + 52W proximity.
    #
    # BSE sector indices (BSE-CG.BO, UTILS.BO, CAPINS.BO, TELCOM.BO): Yahoo Finance
    # returns only current-day price for these, no OHLC history. EMA gate not possible.
    # Their constituent stocks are mostly already in Nifty 500 (Pass 2 universe).
}

# Sectors with no Yahoo Finance history — fetched live from NSE allIndices API.
# Provides: last, previousClose, percentChange, yearHigh, yearLow.
NSE_ONLY_SECTORS: dict[str, str] = {
    "OIL_GAS":     "NIFTY OIL & GAS",
    "CONSR_DURBL": "NIFTY CONSUMER DURABLES",
    "HEALTHCARE":  "NIFTY HEALTHCARE INDEX",
    # SERVICES has full EMA history (^CNXSERVICE) — listed in SECTOR_TICKERS, not here
}


# Maps niftyindices.com index_id → sector name used in sectors.json / SECTOR_TICKERS
# Only confirmed-working slugs (tested against niftyindices.com).
# Broad market indices provide scan universe; sectoral ones feed Pass 1 gate.
INDEX_CONSTITUENTS_MAP: dict[str, str] = {
    # Broad market
    "nifty50":              "N50",
    "nifty500":             "N500",
    "niftynext50":          "NEXT50",
    "niftymidcap100":       "MIDCAP100",
    "niftymidcap150":       "MIDCAP150",
    "niftysmallcap100":     "SMALLCAP100",
    "niftysmallcap250":     "SMALLCAP250",
    "niftylargemidcap250":  "LGMID250",
    "niftymidsmallcap400":  "MIDSMALL400",
    # Sectoral
    "niftyfmcg":            "FMCG",
    "niftyit":              "IT",
    "niftyauto":            "AUTO",
    "niftymetal":           "METAL",
    "niftypharma":          "PHARMA",
    "niftyenergy":          "ENERGY",
    "niftyinfra":           "INFRA",           # was niftyinfrastructure — broken
    "niftymedia":           "MEDIA",
    "niftyrealty":          "REALTY",
    "niftybank":            "BANK",
    "niftypsubank":         "PSU_BANK",
    "niftyoilgas":          "OIL_GAS",
    "niftyconsumerdurables":"CONSR_DURBL",     # was niftyconsumersdurables — broken
    "niftyhealthcare":      "HEALTHCARE",
    "niftycpse":            "CPSE",
    "niftymnc":             "MNC",
    "niftyconsumption":     "CONSUMPTION",
    "niftycommodities":     "COMMODITIES",
    "niftyservice":         "SERVICES",           # NIFTY Services Sector — slug confirmed
}

ALPHA_INDICES = {
    "N50":  INDEX_NIFTY50,
    "N500": INDEX_NIFTY500,
}

NSE_SUFFIX = ".NS"

def nse(sym: str) -> str:
    """Append .NS suffix if not already present and not an index."""
    if sym.startswith("^") or sym.endswith(".NS"):
        return sym
    return sym + NSE_SUFFIX
