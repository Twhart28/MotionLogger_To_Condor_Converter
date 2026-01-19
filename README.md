# MotionLogger to Condor Converter

## Overview
This tool converts MotionLogger text exports into a Condor-compatible format while letting you
condense the data to a user-selected epoch length. It preserves the header information needed
by Condor, aggregates the time series data into the new epoch duration, and writes a new
`*_Condor_<epoch>s.txt` file in the same folder as the input file.

Key behaviors:
- Parses the MotionLogger export header to locate the `DATE/TIME;` table.
- Resamples data into the requested epoch duration.
- Aggregates values by column:
  - `EVENT`, `PIM`, `ZCM`: sum per epoch.
  - `EXT TEMPERATURE`, `LIGHT`: mean per epoch.
  - `STATE`: mode (most frequent value) per epoch.
- Recomputes `PIMn` and `ZCMn` based on the new epoch length instead of using the source values.
- Outputs a Condor-formatted report header with collection start/end times and epoch duration.

## Requirements (Download/Install)
- **Python 3.9+**
- **pandas** (Python package)
  - Install with: `pip install pandas`

> Note: The script uses Tkinter for file dialogs, which is bundled with most standard Python
> installations. On some Linux distributions you may need to install an additional package
> (e.g., `python3-tk`).

## How to Run
1. Ensure your MotionLogger export is saved as a `.txt` file.
2. Run the script:
   ```bash
   python RoughDraft.py
   ```
3. Use the file picker to select the MotionLogger/Condor `.txt` export.
4. Enter the desired epoch duration in seconds.
5. The converted file will be saved next to the original file with a name like:
   `YourFile_Condor_60s.txt`.

## Included Sample Files
- `MotionLogger_Export.txt`: example MotionLogger export.
- `Condor_Input_Format.txt`: example Condor-format output structure.
