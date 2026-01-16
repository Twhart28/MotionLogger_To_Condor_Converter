from __future__ import annotations

from io import StringIO
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import pandas as pd


# =========================
# CONFIG (change this)
# =========================
TARGET_EPOCH_SECONDS = 60  # e.g., 60 for 1-min, 30 for 30s, etc.
OUT_SUFFIX = "_compressed"


DELIM = ";"
DATETIME_COL = "DATE/TIME"


def fmt_float_trim(x: float, max_decimals: int) -> str:
    """Format float with up to max_decimals, then trim trailing zeros/dot."""
    if pd.isna(x):
        return ""
    s = f"{float(x):.{max_decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in {"-0", ""} else s


def find_data_header_line(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if line.startswith("DATE/TIME" + DELIM):
            return i
    raise ValueError("Could not find the data table header line starting with 'DATE/TIME;'.")


def build_output_path(in_path: Path, epoch_s: int) -> Path:
    # Example: file.txt -> file_compressed_60s.txt
    return in_path.with_name(f"{in_path.stem}{OUT_SUFFIX}_{epoch_s}s{in_path.suffix}")


def mode_series(x: pd.Series):
    m = x.mode()
    return m.iloc[0] if not m.empty else (x.iloc[0] if len(x) else pd.NA)


def main() -> None:
    if not isinstance(TARGET_EPOCH_SECONDS, int) or TARGET_EPOCH_SECONDS <= 0:
        raise ValueError("TARGET_EPOCH_SECONDS must be a positive integer.")

    # --- File picker ---
    root = tk.Tk()
    root.withdraw()
    in_file = filedialog.askopenfilename(
        title="Select MotionLogger/Condor TXT export",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    root.destroy()

    if not in_file:
        return

    in_path = Path(in_file)
    out_path = build_output_path(in_path, TARGET_EPOCH_SECONDS)

    # --- Read full file (keep header exactly) ---
    text = in_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    try:
        header_idx = find_data_header_line(lines)
    except Exception as e:
        messagebox.showerror("Parse error", f"{e}")
        return

    preamble_lines = lines[:header_idx]          # everything before the data header line
    table_header_line = lines[header_idx]        # "DATE/TIME;EVENT;EXT TEMPERATURE;..."
    data_lines = lines[header_idx + 1 :]         # everything after the header line

    # Parse header columns exactly as written in the file (preserve output order)
    header_cols = table_header_line.split(DELIM)
    if not header_cols or header_cols[0] != DATETIME_COL:
        messagebox.showerror("Parse error", "Unexpected table header format.")
        return

    data_cols = header_cols[1:]  # columns after DATE/TIME (preserve this order)

    # --- Load data into pandas ---
    table_text = table_header_line + "\n" + "\n".join(data_lines)
    df = pd.read_csv(StringIO(table_text), sep=DELIM, engine="python", dtype=str)

    if DATETIME_COL not in df.columns:
        messagebox.showerror("Parse error", f"Missing '{DATETIME_COL}' column.")
        return

    # Parse datetime and set index
    df[DATETIME_COL] = pd.to_datetime(df[DATETIME_COL], dayfirst=True, errors="coerce")
    df = df.dropna(subset=[DATETIME_COL]).sort_values(DATETIME_COL).set_index(DATETIME_COL)

    # Coerce numerics where possible (STATE/EVENT often int, others floats)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="ignore")

    # --- Build aggregation rules ---
    # IMPORTANT: We ignore original ZCMn entirely and compute it from aggregated ZCM later.
    # Default behavior:
    # - EVENT, PIM, ZCM -> SUM across the window
    # - EXT TEMPERATURE, LIGHT -> MEAN
    # - STATE -> MODE
    agg = {}
    for col in df.columns:
        cu = str(col).upper()
        if cu == "ZCMN":
            continue  # ignore original ZCMn input entirely
        if cu == "STATE":
            agg[col] = mode_series
        elif cu in {"EXT TEMPERATURE", "LIGHT"}:
            agg[col] = "mean"
        else:
            agg[col] = "sum"

    rule = f"{TARGET_EPOCH_SECONDS}S"
    df_res = df.resample(rule).agg(agg)

    # --- Compute NEW ZCMn from aggregated ZCM / epoch_length_seconds ---
    # Only if ZCM exists in either the input or the header list (we'll write it if header expects it).
    if "ZCM" in df_res.columns:
        df_res["ZCMn"] = df_res["ZCM"] / float(TARGET_EPOCH_SECONDS)
    else:
        # If no ZCM exists, still create ZCMn column if needed (will output blank)
        df_res["ZCMn"] = pd.NA

    # --- Build output rows, preserving original header/order ---
    dt_str = df_res.index.strftime("%d/%m/%Y %H:%M:%S")

    rows_out = []
    for i, ts in enumerate(dt_str):
        parts = [ts]
        row = df_res.iloc[i]

        for col in data_cols:
            cu = col.upper()

            # Pull value (blank if missing)
            v = row[col] if col in df_res.columns else pd.NA

            if cu in {"EVENT", "ZCM", "STATE"}:
                parts.append("" if pd.isna(v) else str(int(round(float(v)))))
            elif cu == "PIM":
                parts.append(fmt_float_trim(v, 6))
            elif cu == "ZCMN":
                # NEW computed ZCMn: ZCM / epoch_seconds
                # Use up to 3 decimals (trimmed) so 20.000 -> "20"
                parts.append(fmt_float_trim(v, 3))
            elif cu == "EXT TEMPERATURE":
                parts.append(fmt_float_trim(v, 9))
            elif cu == "LIGHT":
                parts.append(fmt_float_trim(v, 6))
            else:
                parts.append(fmt_float_trim(v, 6))

        rows_out.append(DELIM.join(parts))

    # --- Write output in same format (header unchanged, 1 line per epoch) ---
    out_lines = []
    out_lines.extend(preamble_lines)
    out_lines.append(table_header_line)
    out_lines.extend(rows_out)

    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    messagebox.showinfo("Done", f"Saved compressed epoch file:\n{out_path}")


if __name__ == "__main__":
    main()
