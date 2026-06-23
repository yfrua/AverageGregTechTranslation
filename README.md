# AverageGregTechTranslation

Cooperative subtitle translation project for GregTech-related videos.

## Resources
- YouTube video downloader (put it in the same folder as `downloader.bat`): https://github.com/yt-dlp/yt-dlp
- GTNH wiki: https://gtnh.miraheze.org/wiki/Main_Page
- GTNH Chinese wiki: https://gtnh.huijiwiki.com/wiki/%E9%A6%96%E9%A1%B5
- GTNH Chinese translation: https://paratranz.cn/projects/4964/terms
- online quest book (both Eng and Chs, toggle at upper right): https://gtnhquestsbook.top/
- online NEI (Chinese, server may be down): https://nei.gtnh.work/index?dataSource=273
- online NEI (English): https://shadowtheage.github.io/gtnh/
- **Terminology database for this project**: [`terms.json`](terms.json) — consistent EN→CN term mappings for subtitle translation

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

This step determine which branch you are going to use. Check this [video](https://www.bilibili.com/video/BV19e4y1q7JJ/) out to have better understanding of feature branch workflow.

**Option A: Direct on `main`**

```bash
git checkout main
```
You may even not need to do this, because you are at main branch by default.

**Option B: Branch + PR (recommended)**

```bash
git checkout -b translate/<file-or-topic>
```
to create a new brach named `translate/<file-or-topic>` if it doesn't exist and switch to that branch.

### 4) Edit subtitle files

Open the `.srt` file in your editor and only change text lines that need translation.

Please do **not** change:

- Subtitle index numbers (`1`, `2`, `3`, ...)
- Timecode lines (`00:00:01,000 --> 00:00:04,000`)
- Blank line separators

### 5) Commit your work

Check what changed (not necessary):

```bash
git status
git diff
```

Commit:

```bash
git add <path_to_file>
git commit -m "<your_commit_message>"
```

### 6) Push your changes

Sync any change from remote repo before your commit:
```bash
git pull
```
or
```bash
git pull --rebase origin <your-branch>
```

To push your commit to the remote repo:

If this is your first time pushing this exact branch:
```bash
git push -u origin translate/<file-or-topic>
```
so that `git remote` configuration is automatically set.

Afterward, you can simple run `git push` to push any commit of that branch:

Once every steps of translation are done, you can open GitHub and create a pull request (PR) from your branch into `main`. A branch after merging into `main` is usually deleted in remote, but you also need to delete it locally:
```bash
git branch -D translate/<file-or-topic>
```

## Sync from Remote Repository

The idea of feature branch is to keep `main` branch stable while every feature branch active.

It would not make you free from doing `git pull` to keep in sync with everyone else, but make works in different projects not interference each other. The `main` branch is clean unless the whole procedure of translation on other branch is done and got merged into it.

So, before you start each work session, sync with remote repository:
```bash
git pull --all
```

If there are any updata in `main` branch, bring latest `main` into your branch:
```bash
git checkout translate/<file-or-topic>
git merge main
```

If there is a merge conflict, ask for help immediately or resolve it carefully in the conflicted files, then:

```bash
git add <conflicted-file>
git commit
```

## Common Git Commands Cheat Sheet

```bash
git status                # See changed files
git diff                  # See exact line changes
git add <file>            # Stage a file
git commit -m "message"   # Commit staged changes
git pull origin <branch>  # Get latest <branch> updates
git push                  # Push your branch
git checkout -b <branch>  # Create and switch branch
git branch -D <branch>    # Delete local branch
```

## Prompt for AI Translation
```
Update the Chinese translation at the second half of subtitles based on the first English half. Don't modify the English half unless there are some obvious errors, also don't delete words in bracket because that's something I'm not sure about when writting down what my heard.
You can find a terminology database at @terms.json , use it to translate the term you don't know. And you can make some addition to it after translating the whole subtitles.
```
