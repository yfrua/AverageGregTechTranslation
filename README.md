# AverageGregTechTranslation

Cooperative subtitle translation project for GregTech-related clips.


## Quick Start (Git Newcomer)

### 1) One-time setup

Install:

- Git: https://git-scm.com/downloads

Configure your identity (run once):

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 2) Clone the repository

```bash
git clone https://github.com/yfrua/AverageGregTechTranslation.git
cd AverageGregTechTranslation
```

### 3) Pick a workflow mode

For a small two-person team, direct work on `main` is fine if both of you sync frequently.

Option A: Direct on `main` (recommended for this repo now)

```bash
git checkout main
git pull origin main
```

Option B: Branch + PR (safer, use this for larger or riskier edits)

```bash
git checkout -b translate/<your-name>/<file-or-topic>
```

Examples:

- `translate/alex/hot-ingots-pass1`
- `translate/lee/fix-typos-hot-ingots`

### 4) Edit subtitle files

Open the `.srt` file in your editor and only change text lines that need translation.

Please do **not** change:

- Subtitle index numbers (`1`, `2`, `3`, ...)
- Timecode lines (`00:00:01,000 --> 00:00:04,000`)
- Blank line separators

### 5) Commit your work

Check what changed:

```bash
git status
git diff
```

Commit:

```bash
git add clips/hot_ingots.srt
git commit -m "Translate hot_ingots.srt (section 1-80)"
```

### 6) Push your changes

If you are using direct `main` workflow:

```bash
git pull --rebase origin main
git push origin main
```

If you are using branch workflow:

```bash
git push -u origin translate/<your-name>/<file-or-topic>
```

Then open GitHub and create a PR from your branch into `main`.

## Daily Sync Workflow

Before starting each work session:

```bash
git checkout main
git pull origin main
```

If you are on a branch, bring latest `main` into your branch:

```bash
git checkout translate/<your-name>/<file-or-topic>
git merge main
```

If there is a merge conflict, ask for help immediately or resolve it carefully in the conflicted `.srt` file, then:

```bash
git add <conflicted-file>
git commit
```

## Commit Message Suggestions

Good commit messages:

- `Translate hot_ingots.srt entries 1-80`
- `Revise terminology in hot_ingots.srt`
- `Fix punctuation and consistency in hot_ingots.srt`

## Team Safety Rules for Direct main Workflow

If both of you commit directly to `main`, follow these rules:

- Always run `git pull origin main` before editing.
- Keep each commit small (one file or one subtitle range).
- Push frequently so the other person can sync.
- If both are editing the same file, split by subtitle entry ranges first.
- Use branch + PR temporarily for large rewrites.

## Common Git Commands Cheat Sheet

```bash
git status                     # See changed files
git diff                       # See exact line changes
git add <file>                 # Stage a file
git commit -m "message"        # Commit staged changes
git pull origin main           # Get latest main updates
git push                       # Push your branch
git checkout -b <branch-name>  # Create and switch branch
```

