# Byte-Converter
> A Python terminal tool that downloads a YouTube video, gzip-compresses it, and converts the resulting bytes into a single astronomically large integer.

---

## 📋 Overview

Byte-Converter is a small Python command-line application that implements a three-stage pipeline: download a video from YouTube, losslessly compress it, and then interpret the compressed binary data as one giant base-10 integer. The project appears to be an exploratory or educational experiment to illustrate just how large the numbers encoded inside everyday digital media files truly are.

The README includes a detailed table showing that, for example, a one-minute 720p YouTube video (~18.7 MB compressed) yields a decimal integer with roughly 45 million digits. The tool leverages Python's built-in arbitrary-precision integers and explicitly raises the `sys.set_int_max_str_digits` limit (introduced in Python 3.11) to allow conversion of these massive numbers to strings without raising an error.

A second, standalone utility module (`convert_to_bytes.py`) provides a simpler inspection helper: it reads any local MP4 file, prints byte statistics (size, first 50 bytes in hex and decimal), and optionally saves a full hex dump to a text file.

## 🗓️ Timeline

| Field | Value |
|-------|-------|
| **Started** | August 2026 |
| **Last Active** | August 2026 |
| **Duration** | ~3 days |

## 🔗 Repository

| Field | Value |
|-------|-------|
| **GitHub** | https://github.com/Dibij/Byte-Converter |
| **Created on GitHub** | August 15, 2026 |
| **Last pushed** | August 17, 2026 |

## 🛠️ Tech Stack

- **Language:** Python 3.x
- **Third-party library:** `yt-dlp` — video downloading from YouTube and other platforms
- **Standard library:** `gzip` (compression), `shutil` (stream copy), `os` (file system), `sys` (integer digit limit override)
- **External system dependency:** `ffmpeg` — required by yt-dlp for muxing video/audio streams

## 📁 Project Structure

```
Byte-Converter/
├── main.py               # Entry point: download → compress → convert to big integer
├── convert_to_bytes.py   # Standalone utility: inspect a local MP4 as raw bytes / hex
├── requirements.txt      # Single dependency: yt-dlp
├── Details.docx          # Supporting document (binary, not analyzed)
├── README.md             # Project description, pipeline explanation, and size tables
└── .gitignore            # Standard Python gitignore
```

## 🚀 Key Features / What It Does

1. **YouTube video download** — Prompts the user for a YouTube URL and downloads the best available MP4 stream using `yt-dlp` with the iOS player client extractor to work around bot-detection.
2. **Gzip compression (level 9)** — Reads the raw MP4 and compresses it at maximum compression with Python's built-in `gzip` module, writing a `.gz` file.
3. **Byte-to-integer conversion** — Reads the compressed binary blob and converts it to a single Python big integer using `int.from_bytes(data, 'big')`.
4. **Display of first 100 digits** — Converts the enormous integer to a string and prints only the first 100 decimal digits, with a warning that this step can be slow and memory-intensive for large files.
5. **Python 3.11+ integer string limit bypass** — Calls `sys.set_int_max_str_digits(0)` at startup to remove the security cap on integer-to-string conversion length.
6. **Standalone hex inspector** (`convert_to_bytes.py`) — Reads a local MP4 (or any file), reports file size in bytes and MB, prints the first 50 bytes in both hex and decimal form, and saves the complete hex dump to a `.txt` file.
7. **Error-path cleanup** — On failure, automatically removes any partial `video.mp4` and `video.gz` artefacts; on success, cleanup is intentionally skipped (commented out) so the files can be inspected afterwards.

## 📦 Dependencies & Setup

```bash
# Clone
git clone https://github.com/Dibij/Byte-Converter.git
cd Byte-Converter

# Install Python dependency
pip install -r requirements.txt   # installs yt-dlp

# Also required on the system PATH:
# ffmpeg (https://ffmpeg.org/download.html)

# Run
python main.py
# → Enter YouTube URL when prompted
```

## 📝 Notes

- This appears to be a personal curiosity/learning project exploring Python's arbitrary-precision integers and the mathematical scale of real-world binary data.
- The cleanup block in `main.py` is commented out (`os.remove` calls), meaning video and compressed files are left on disk after a successful run — a likely leftover from debugging.
- `Details.docx` is present in the repository but its contents are binary and were not analyzed.
- The project has no tests, no CI configuration, and no packaging setup — consistent with a quick experimental script.
- Only 6 commits were made over 3 days, indicating a short, focused development sprint.
