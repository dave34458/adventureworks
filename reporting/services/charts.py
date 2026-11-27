"""Chart geometry builders used by live report generation."""
from ..utils import money, money_exact, percent, ring


def compact_money(value):
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.0f}K"
    return f"{sign}${value:.0f}"


def build_donut(tab, mix):
    label = "cost" if tab == "cost" else "revenue"
    return ring([
        {
            "cls": row["cls"],
            "pct": row["pct"],
            "t": f"{row['name']} \u00b7 {money(row['money'])} \u00b7 "
                 f"{percent(row['pct'])} of {label} \u00b7 {percent(row['margin'])} margin",
        }
        for row in mix
    ])


def build_combo(profit_rows, margin_rows):
    profits = [float(row.get("profit") or 0) for row in profit_rows]
    cur_vals = [row.get("margin") for row in margin_rows]
    prev_vals = [row.get("prev_margin") for row in margin_rows]
    labels = [str(row.get("label") or "") for row in profit_rows]
    full = [str(row.get("full") or "") for row in profit_rows]
    prev_full = [str(row.get("prev_full") or "") for row in margin_rows]

    vmax = max(profits + [0.0])
    vmin = min(profits + [0.0])
    span = max(vmax - vmin, 1)
    m_values = [float(v) for v in cur_vals + prev_vals if v is not None] + [0.0]
    m_high = max(m_values)
    m_low = min(m_values)
    m_max = 60 if m_high <= 60 else (int(m_high / 10) + 1) * 10
    m_min = 0 if m_low >= 0 else (int(m_low / 10) - 1) * 10
    m_span = max(m_max - m_min, 1)
    px_w, px_h, pad_l, pad_r, pad_t, pad_b = 960, 280, 100, 96, 10, 44
    plot_w, plot_h = px_w - pad_l - pad_r, px_h - pad_t - pad_b
    barw = round(min(40, plot_w / max(len(profits) - 1, 1) * 0.65), 1)
    inner_left = pad_l + barw / 2
    inner_right = px_w - pad_r - barw / 2

    def x_at(index):
        return round(inner_left + index * (inner_right - inner_left)
                     / max(len(profits) - 1, 1), 1)

    zero_y = round(pad_t + (vmax / span) * plot_h, 1)

    def y_money(value):
        return round(zero_y - value / span * plot_h, 1)

    def y_pct(value):
        return round(pad_t + (m_max - value) / m_span * plot_h, 1)

    bars = []
    for index, profit in enumerate(profits):
        height = round(abs(profit) / span * plot_h, 1)
        y = y_money(profit) if profit >= 0 else zero_y
        bars.append({
            "x": round(x_at(index) - barw / 2, 1), "y": y, "h": height, "w": barw,
            "t": f"{full[index]} \u00b7 {money_exact(profit)} gross profit",
        })

    dots = []
    for index, value in enumerate(cur_vals):
        if value is not None:
            dots.append({
                "cls": "dotc", "x": x_at(index), "y": y_pct(value),
                "t": f"{full[index]} \u00b7 {float(value):.2f}% margin",
            })
    for index, value in enumerate(prev_vals):
        if value is not None:
            dots.append({
                "cls": "dotp", "x": x_at(index), "y": y_pct(value),
                "t": f"{prev_full[index] or full[index]} \u00b7 {float(value):.2f}% margin",
            })

    tick_values = ((vmin, 0, vmax) if vmin < 0 < vmax
                   else (vmin, vmin / 2, 0) if vmin < 0
                   else (0, vmax / 2, vmax))
    margin_ticks = ((m_min, 0, m_max) if m_min < 0
                    else (0, 20, 40, 60) if m_max == 60
                    else (0, m_max / 2, m_max))
    return {
        "bars": bars,
        "cur_pts": " ".join(f"{x_at(index)},{y_pct(value)}"
                            for index, value in enumerate(cur_vals)
                            if value is not None),
        "prev_pts": " ".join(f"{x_at(index)},{y_pct(value)}"
                             for index, value in enumerate(prev_vals)
                             if value is not None),
        "dots": dots,
        "xticks": [{
            "x": x_at(index), "lab": label,
            "year_lab": (f"{prev_full[index][-4:]} vs {full[index][-4:]}"
                         if prev_full[index] else full[index][-4:]),
        } for index, label in enumerate(labels)],
        "lticks": [{"y": y_money(value), "lab": compact_money(value)} for value in tick_values],
        "rticks": [{"y": y_pct(value), "lab": f"{value:g}%"}
                    for value in margin_ticks],
        "axis_x1": pad_l,
        "axis_x2": px_w - pad_r,
        "left_tick_x": pad_l - 24,
        "right_tick_x": px_w - pad_r + 8,
    }
