# Automated Movie Compression Pipeline for Jellyfin

**Version:** 1.0
**Target OS:** Ubuntu Server 24.04 LTS
**Container Platform:** Docker & Docker Compose
**Media Server:** Jellyfin
**Torrent Client:** qBittorrent
**Automation Goal:** Automatically compress downloaded movies before adding them to the Jellyfin library.

---

# 1. Objective

Build a fully automated media-processing pipeline that:

* Downloads movies
* Verifies download integrity
* Compresses movies to reduce storage
* Downloads subtitles
* Organizes movies
* Updates Jellyfin automatically

The entire process should require **zero manual intervention**.

---

# 2. High-Level Architecture

```text
                    Internet

         Telegram / Torrent / Browser
                     │
                     ▼
              qBittorrent
                     │
                     ▼
              Download Folder
                     │
             Download Completed
                     │
                     ▼
        Automation Orchestrator
                     │
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
 File Check     Subtitle Download   Metadata
     │
     ▼
 Video Compression
     │
     ▼
 Quality Verification
     │
     ▼
 Folder Organization
     │
     ▼
 Jellyfin Library
     │
     ▼
 Jellyfin Scan
```

---

# 3. Design Principles

## Never Process Incomplete Files

Downloads should never be processed while still downloading.

Always wait until:

* qBittorrent reports completed
* File size remains unchanged
* File can be opened by ffprobe

---

## Never Modify Originals

Keep the original until compression succeeds.

Workflow:

```text
Downloads
    │
    ▼
Compression
    │
    ▼
Verification
    │
    ▼
Delete Original
```

---

## Idempotent Pipeline

Every stage must be restart-safe.

If the server reboots:

* continue where it stopped
* never restart from the beginning
* never duplicate work

---

# 4. Folder Structure

```text
/media

├── downloads
│
├── processing
│
├── compressed
│
├── subtitles
│
├── failed
│
├── archive
│
└── jellyfin
    ├── Movies
    └── TV Shows
```

---

# 5. Docker Containers

## Required

| Container          | Purpose             |
| ------------------ | ------------------- |
| Jellyfin           | Media Server        |
| qBittorrent        | Downloader          |
| Compression Worker | FFmpeg encoding     |
| Subtitle Service   | Subtitle Downloader |
| Automation Service | Orchestrator        |

---

## Optional

| Container    | Purpose              |
| ------------ | -------------------- |
| Tdarr Server | Distributed Encoding |
| Tdarr Node   | Encoding Worker      |
| Prometheus   | Monitoring           |
| Grafana      | Dashboards           |
| Loki         | Logs                 |

---

# 6. Pipeline Stages

---

## Stage 1

Movie Download

Input

```text
Torrent
```

Output

```text
/media/downloads
```

Checks

* Download complete
* Hash check successful
* File accessible

---

## Stage 2

File Validation

Run

```text
ffprobe
```

Verify

* valid container
* duration
* resolution
* codec
* audio stream

Reject

* corrupted
* incomplete
* zero bytes

Move failures

```text
/media/failed
```

---

## Stage 3

Compression Decision

Determine

Already HEVC?

↓

Yes

Skip compression

↓

No

Compress

Rules

Skip when

* codec = HEVC
* bitrate already low
* AV1

Compress when

* MPEG2
* VC1
* H264
* Xvid
* DivX

---

## Stage 4

Compression

Encoder

HEVC (H265)

Settings

```text
CRF = 22

Preset = Slow

Audio = Copy

Subtitle = Copy
```

Expected Savings

1080p

40–60%

4K

30–40%

---

## Stage 5

Quality Verification

Compare

Original

Compressed

Verify

Duration

Resolution

Frame count

Audio tracks

Subtitle tracks

File playable

If failed

Delete compressed

Keep original

Move to failed

---

## Stage 6

Subtitle Download

Search

Movie Name

Year

Language

Download

English

Malayalam (if available)

Rename

```text
Movie.en.srt

Movie.ml.srt
```

---

## Stage 7

Rename

Example

```text
Avatar (2009)

Avatar (2009).mkv

Avatar (2009).en.srt
```

---

## Stage 8

Move

Destination

```text
/media/jellyfin/Movies/
```

---

## Stage 9

Jellyfin Scan

Options

Automatic

or

API trigger

---

# 7. Compression Rules

## Movies

Compress

H264

↓

H265

Skip

Already HEVC

Skip

Already AV1

---

## TV Shows

Same policy

---

## Anime

Keep original subtitles

Keep chapters

Keep attachments

---

# 8. Metadata Database

Store

```text
Movie

Codec

Resolution

Original Size

Compressed Size

Compression Ratio

Processing Time

Status

Checksum
```

Example

```text
Movie

Interstellar

Original

22 GB

Compressed

8 GB

Ratio

63%

Status

Success
```

---

# 9. Failure Recovery

Possible failures

Download incomplete

↓

Retry later

Compression failed

↓

Retry

Subtitle failed

↓

Continue

Rename failed

↓

Retry

Jellyfin offline

↓

Queue request

---

# 10. Retry Policy

Compression

3 retries

Subtitle

5 retries

Rename

5 retries

Move

Infinite retries

---

# 11. Logging

Every stage

```text
Timestamp

Movie

Stage

Duration

Status

Error
```

Example

```text
2026-07-26

Movie

Dune

Compression

Completed

Original

18 GB

Compressed

7 GB

Saved

11 GB
```

---

# 12. Monitoring

Track

Downloads

Compression Queue

Failures

Storage Saved

Average Compression Time

Average Movie Size

Daily Throughput

---

# 13. Performance Optimizations

## Hardware Encoding

Use Intel Quick Sync

Docker

```yaml
devices:
  - /dev/dri:/dev/dri
```

---

## CPU Limits

Limit encoder

```text
75%

CPU
```

Prevent Jellyfin lag.

---

## Disk IO

Processing folder

SSD preferred

Archive

HDD acceptable

---

# 14. Storage Strategy

Never compress

Already HEVC

Never compress

AV1

Delete original

Only after

Verification complete

---

# 15. Automation Flow

```text
Download Complete

↓

Validate

↓

Already HEVC?

├── Yes

│     ↓

│ Move to Jellyfin

│

└── No

      ↓

Compress

      ↓

Verify

      ↓

Download Subtitles

      ↓

Rename

      ↓

Move

      ↓

Jellyfin Scan

      ↓

Done
```

---

# 16. Recommended Technology Stack

| Layer                   | Technology                  |
| ----------------------- | --------------------------- |
| Downloader              | qBittorrent                 |
| Orchestrator            | Python + LangGraph (future) |
| Compression             | FFmpeg                      |
| Alternative Compression | Tdarr                       |
| Subtitle Downloader     | Bazarr or custom service    |
| Metadata                | TMDb                        |
| Media Server            | Jellyfin                    |
| Monitoring              | Grafana + Prometheus + Loki |
| Container Runtime       | Docker Compose              |

---

# 17. Future Enhancements

## Phase 2

* AI-based compression decision
* Detect animation vs live action
* Dynamic CRF selection
* GPU hardware encoding
* Multi-worker compression

---

## Phase 3

* Automatically detect duplicate movies
* Quality scoring
* AI scene analysis
* Automatic trailer generation
* Automatic intro/outro detection

---

## Phase 4

* Multi-server distributed encoding
* Remote encoding workers
* Cloud backup
* AI recommendations
* Storage prediction dashboard

---

# 18. Estimated Resource Requirements

| Component          | CPU    | RAM    | Disk       |
| ------------------ | ------ | ------ | ---------- |
| Jellyfin           | Medium | 2–4 GB | Low        |
| qBittorrent        | Low    | 512 MB | Low        |
| FFmpeg Compression | High   | 2–6 GB | High I/O   |
| Subtitle Service   | Low    | 256 MB | Negligible |
| Automation Service | Low    | 512 MB | Negligible |
| Monitoring Stack   | Medium | 1–2 GB | Low        |

---

# 19. Implementation Phases

## Phase 1 – Core Infrastructure

* Install Docker and Docker Compose.
* Deploy Jellyfin.
* Deploy qBittorrent.
* Create media directory structure.
* Configure shared Docker volumes.

**Deliverable:** Downloads can reach the media server.

---

## Phase 2 – Processing Pipeline

* Create the automation service.
* Detect completed downloads.
* Validate media files with `ffprobe`.
* Compress H.264 videos to H.265.
* Verify output quality.
* Move successful files to a staging folder.

**Deliverable:** Automated, reliable compression.

---

## Phase 3 – Media Enhancement

* Download subtitles.
* Rename files consistently.
* Organize into Jellyfin library structure.
* Trigger or wait for Jellyfin library scans.

**Deliverable:** Fully organized media library.

---

## Phase 4 – Observability

* Deploy Prometheus, Grafana, and Loki.
* Add dashboards for queue length, storage savings, failures, and processing times.
* Configure alerts for repeated failures or low disk space.

**Deliverable:** Production-grade monitoring.

---

## Phase 5 – AI-Orchestrated Automation

* Introduce LangGraph as the workflow orchestrator.
* Add intelligent retry and recovery logic.
* Skip unnecessary compression based on codec and bitrate.
* Enable future AI-driven quality optimization and workflow decisions.

**Deliverable:** A scalable, intelligent media automation platform ready for future expansion.
