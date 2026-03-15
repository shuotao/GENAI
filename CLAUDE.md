# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**"The Physics of Insight"** is a dual-purpose project combining:

1. **Interactive Web Platform** (`/web`): Static HTML/CSS/JS website inspired by Jack Butcher's design philosophy, presenting LLM learning concepts with visual clarity and interactive technical detail drawers.
2. **SRT Audio-to-Text Workflow** (`/SRT`): Python-based pipeline for converting audio recordings to SRT subtitles and transcripts, with built-in QA/QC and professional knowledge supplementation.

The project emphasizes "compression vs. expansion" and bridging knowledge silos through visual design and automated content processing.

---

## Architecture

### Web Component (`/web`)

**Purpose**: Deliver core learning content with minimal cognitive friction

- **`index.html`**: Main single-page scrolling interface with 13 core sections
  - Uses Intersection Observer for scroll detection
  - Dynamically loads technical detail pages into right-side drawer via iframe
  - Responsive design with glassmorphism effects

- **`script.js`**: Handles UI interactivity
  - Scroll-based navigation state (navbar visibility)
  - Drawer open/close logic with dynamic iframe src loading
  - Responsive breakpoints

- **`style.css`**: Unified visual system
  - Minimalist black/white/gray palette
  - Glassmorphism backdrop effects
  - Smooth drawer animations
  - System font stack (no external font dependencies for offline viewing)

- **`tech-01.html` through `tech-10.html`**: Detail pages loaded as drawer content
  - Each contains concrete technical implementation details
  - Includes Prompt engineering techniques ("HOW" section)

- **`easter-egg.html`**: Hidden page revealing the development workflow automation

### SRT Component (`/SRT`)

**Purpose**: Standardize audio transcription and transcript generation workflow

- **`transcribe.py`**: Audio-to-SRT converter
  - Chunks audio into 10-minute segments (prevents Whisper hallucination on long recordings)
  - Calls Groq Whisper API with custom context from `context.txt` for vocabulary accuracy
  - Outputs SRT files with proper timecodes (HH:MM:SS,mmm format)
  - Auto-invokes `qaqc_srt.py` for immediate QA/QC

- **`qaqc_srt.py`**: Quality assurance and cleanup
  - Removes empty subtitle blocks
  - Filters "Whisper hallucinations" (e.g., prompts injected as content: "內容包含：...")
  - Applies typo fixes (common sound-alike errors like 剪報→簡報)
  - Renumbers SRT sequences (handles removed blocks gracefully)
  - Can be called standalone for batch processing

- **`context.txt`**: Vocabulary context for Whisper
  - Comma-separated list of domain terms (technical, meeting-specific, brand names)
  - Injected into Whisper prompt to improve accuracy on specialized vocabulary
  - Currently tuned for: Claude Code, technical terminology, Chinese traditional terms

- **`Agent.md`**: Definitive workflow specification (v2.1)
  - **Zero Omission Principle**: Transcripts must preserve complete original content, no summarization
  - **Knowledge Supplements**: Professional term explanations must be embedded at first-mention point in text (not appended)
  - **Merging SRT files**: Strict rules for combining multiple SRT files + cleanup
  - **QA/QC Standards**: What constitutes proper formatting and filtering

### Assets (`/assets`)

- `physics_of_insight/`: Visualization diagrams for core concepts
- Portrait photos and UI icons (jack_diamond_icon.png for easter egg)

---

## Development & Build

### Web Development

**Offline Testing:**
```bash
# Simply open in browser (no server needed)
open web/index.html
# Or drag/drop into browser window
```

**Requirements**: Modern browser (Chrome, Edge, Safari) with CSS Grid and Intersection Observer support. Works completely offline once loaded (uses system fonts).

**Deployment**: Repository configured for GitHub Pages with root `index.html` that auto-redirects to `web/index.html`.

### SRT Audio Processing

**Setup:**
```bash
cd SRT
python3 -m venv .venv
source .venv/bin/activate
pip install requests
# Requires: ffmpeg (system-level), Groq API key
```

**Transcribe Audio File:**
```bash
cd SRT
python3 transcribe.py
# Prompts for: Groq API Key, then processes all audio files in current directory
# Outputs: filename.srt (then auto-runs QAQC)
```

**Manual QA/QC (if needed):**
```bash
python3 qaqc_srt.py <filename.srt>
# Updates the file in-place with cleaned/renumbered content
```

**Customize vocabulary context:**
```bash
# Edit context.txt with comma-separated domain terms
# These will be injected into Whisper's prompt for accuracy boost
```

---

## SRT Workflow Standards

**Critical Rules** (from Agent.md v2.1):

1. **Zero Omission Principle**
   - Never summarize, condense, or paraphrase transcripts
   - Preserve all original speaker content (except pure filler: 呃, 嗯, 那個 when non-semantic)
   - Keep first-person voice; never rewrite as third-person narrative

2. **Merging Multiple SRT Files**
   - Concatenate by filename order
   - Remove timecodes and sequence numbers
   - Remove redundant filler words only where non-semantic
   - Add Markdown headers (`##`, `###`) at section boundaries (not replacing content)

3. **Professional Knowledge Supplements**
   - Extract technical terms and provide explanations
   - Insert explanations **at first mention point in text**, not in appendix
   - Use Markdown blockquotes with empty lines before/after:
     ```markdown
     [text mentioning Transformer...]

     > **專業知識補充：Transformer**
     >
     > [Explanation of concept]

     [continued text...]
     ```

4. **Final QA/QC Checklist**
   - All content preserved? ✓
   - Timecodes + sequence numbers removed? ✓
   - Filler words removed appropriately? ✓
   - Section headers added? ✓
   - Knowledge supplements embedded at mention points? ✓
   - No third-person rewrites? ✓

---

## Key Files & Paths

| Purpose | Path | Notes |
|---------|------|-------|
| Main website | `/web/index.html` | Static, offline-ready |
| Web styling | `/web/style.css` | Single unified stylesheet |
| Web interactivity | `/web/script.js` | Drawer + scroll detection |
| Tech detail pages | `/web/tech-0X.html` | Loaded as iframes in drawer |
| Audio transcription | `/SRT/transcribe.py` | Groq Whisper integration |
| QA/QC pipeline | `/SRT/qaqc_srt.py` | Cleanup + renumbering |
| Workflow rules | `/SRT/Agent.md` | Master specification (v2.1) |
| Vocabulary context | `/SRT/context.txt` | Comma-separated Whisper hints |
| Learning notes | `/SRT/好學生筆記.md` | AI role definition for note generation |
| Project philosophy | `/README.md` | Design rationale + setup |

---

## Important Notes

### Security Alert 🔐

**`SRT/Groq.md` contains what appears to be an API key and should NOT be in version control.**

- [ ] TODO: Remove Groq.md from repository (or rotate the key immediately if exposed)
- [ ] TODO: Use environment variables instead: `export GROQ_API_KEY=<key>` and read via `os.environ.get()`
- [ ] TODO: Add `.env` to `.gitignore`

### Project Structure Decisions

- **Relative paths throughout**: All web assets use relative paths (`../assets/`, `./style.css`) for flexibility (works on any domain, locally, or offline)
- **No server required**: Pure static site; no Node build step, no package manager, no database
- **Single CSS file**: Unifies visual system; avoid separate component stylesheets
- **iframe drawers**: Technical content loads into right-side drawer without page reload; preserves scroll position on main page

### Git History

Recent work (commit 77c1fe5+) unified development/deployment structure and introduced the SRT workflow. See `git log` for full history.

