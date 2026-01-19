from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import pandas as pd


DELIM = ";"
DATETIME_COL = "DATE/TIME"
OUTPUT_COLUMNS = [
    "DATE/TIME",
    "EVENT",
    "EXT TEMPERATURE",
    "PIM",
    "PIMn",
    "ZCM",
    "ZCMn",
    "LIGHT",
    "STATE",
]


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
    # Example: file.txt -> file_Condor_60s.txt
    return in_path.with_name(f"{in_path.stem}_Condor_{epoch_s}s{in_path.suffix}")


def mode_series(x: pd.Series):
    m = x.mode()
    return m.iloc[0] if not m.empty else (x.iloc[0] if len(x) else pd.NA)


def main() -> None:
    # --- File picker ---
    root = tk.Tk()
    root.withdraw()
    in_file = filedialog.askopenfilename(
        title="Select MotionLogger/Condor TXT export",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    if not in_file:
        root.destroy()
        return

    target_epoch_seconds = simpledialog.askinteger(
        "Epoch Duration",
        "Enter the epoch duration in seconds to condense the file to:",
        minvalue=1,
        parent=root,
    )
    root.destroy()

    if target_epoch_seconds is None:
        return

    in_path = Path(in_file)
    out_path = build_output_path(in_path, target_epoch_seconds)

    # --- Read full file (keep header exactly) ---
    text = in_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    try:
        header_idx = find_data_header_line(lines)
    except Exception as e:
        messagebox.showerror("Parse error", f"{e}")
        return

    table_header_line = lines[header_idx]        # "DATE/TIME;EVENT;EXT TEMPERATURE;..."
    data_lines = lines[header_idx + 1 :]         # everything after the header line

    # Parse header columns exactly as written in the file (preserve output order)
    header_cols = table_header_line.split(DELIM)
    if not header_cols or header_cols[0] != DATETIME_COL:
        messagebox.showerror("Parse error", "Unexpected table header format.")
        return

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
    # IMPORTANT: We ignore original ZCMn/PIMn entirely and compute them from aggregated values later.
    # Default behavior:
    # - EVENT, PIM, ZCM -> SUM across the window
    # - EXT TEMPERATURE, LIGHT -> MEAN
    # - STATE -> MODE
    agg = {}
    for col in df.columns:
        cu = str(col).upper()
        if cu in {"ZCMN", "PIMN"}:
            continue  # ignore original ZCMn input entirely
        if cu == "STATE":
            agg[col] = mode_series
        elif cu in {"EXT TEMPERATURE", "LIGHT"}:
            agg[col] = "mean"
        else:
            agg[col] = "sum"

    rule = f"{target_epoch_seconds}S"
    df_res = df.resample(rule).agg(agg)

    # --- Compute NEW PIMn/ZCMn from aggregated values / epoch_length_seconds ---
    if "PIM" in df_res.columns:
        df_res["PIMn"] = df_res["PIM"] / float(target_epoch_seconds)
    else:
        df_res["PIMn"] = pd.NA

    if "ZCM" in df_res.columns:
        df_res["ZCMn"] = df_res["ZCM"] / float(target_epoch_seconds)
    else:
        df_res["ZCMn"] = pd.NA

    # --- Build output rows, preserving Condor header/order ---
    dt_str = df_res.index.strftime("%d/%m/%Y %H:%M:%S")

    rows_out = []
    for i, ts in enumerate(dt_str):
        parts = [ts]
        row = df_res.iloc[i]

        for col in OUTPUT_COLUMNS[1:]:
            cu = col.upper()

            # Pull value (blank if missing)
            v = row[col] if col in df_res.columns else pd.NA

            if cu in {"EVENT", "ZCM", "STATE"}:
                parts.append("" if pd.isna(v) else str(int(round(float(v)))))
            elif cu == "PIM":
                parts.append(fmt_float_trim(v, 6))
            elif cu == "PIMN":
                parts.append(fmt_float_trim(v, 15))
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

    # --- Write output in Condor format (header updated, 1 line per epoch) ---
    if df_res.empty:
        messagebox.showerror("No data", "No epochs were found after resampling.")
        return

    created_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    first_epoch = df_res.index.min().strftime("%d/%m/%Y %H:%M:%S")
    last_epoch = df_res.index.max().strftime("%d/%m/%Y %H:%M:%S")

    out_lines = []
    out_lines.extend(
        [
            "+-------------+ MotionLogger Conversion to Condor Report +-------------+",
            f"SUBJECT_NAME : {in_path.stem}",
            "SUBJECT_DESCRIPTION :",
            "DEVICE_ID : Micro MotionLogger",
            f"FILE_DATE_TIME : {created_at}",
            f"Collection_Start: {first_epoch}",
            f"Collection_End: {last_epoch}",
            f"Epoch_Duration:  {target_epoch_seconds}",
            "+----------------------------------------------------------------------+",
        ]
    )
    out_lines.append(DELIM.join(OUTPUT_COLUMNS))
    out_lines.extend(rows_out)

    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    messagebox.showinfo("Done", f"Saved Condor file:\n{out_path}")


if __name__ == "__main__":
    main()
