def choose_mode(metrics, τ):
    ESS, CI, DI, TC, RC, SP, IR = metrics
    if IR:
        return "G"
    if (
        ESS >= τ.get("ess_hi", 0.65)
        and CI >= τ.get("ci_hi", 0.70)
        and DI >= 2
        and TC >= τ.get("tc_dom", 0.60)
    ):
        return "A"
    if ESS >= τ.get("ess_hi", 0.65) and CI < τ.get("ci_lo", 0.40) and DI >= 2:
        return "B"
    if TC < τ.get("tc_amb", 0.40):
        return "D"
    if ESS >= τ.get("ess_mid", 0.45) and DI > τ.get("di_broad", 2) and CI >= τ.get("ci_mid", 0.55):
        return "E"
    if SP >= τ.get("sp_hi", 0.65) and ESS >= τ.get("ess_mid", 0.45):
        return "F"
    if ESS < τ.get("ess_lo", 0.30):
        return "C"
    return "H"
