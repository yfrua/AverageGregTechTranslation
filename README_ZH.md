# AverageGregTechTranslation
GregTech 油管博主相关视频的合作字幕翻译项目。

请阅读并遵循 [指南](guidelines.md) 后开始翻译。

拉取请求中改动的字幕文件会由 CI 自动检查是否符合规范（[`scripts/subtitle_lint.py`](scripts/subtitle_lint.py)）。CI 会检查整个文件。如需在本地运行同样的检查：

```bash
python3 scripts/subtitle_lint.py <字幕文件.srt>
```

加上 `--fix` 可自动修正可修复的样式问题（首字母大写、句末标点、空格代替逗号等）再检查。

—————————————————注意—————————————————

所有操作均需命令行操作，windows 使用 powershell

请按照教程逐步操作

- 软件与视频教程 qq 群里有
- 项目网址：https://github.com/yfrua/AverageGregTechTranslation
- 播放软件：potplayer 使用这个软件同时打开字幕和视频
- 浏览器视频下载插件： Tubly - YouTube MP3/MP4/Shorts 下载器
- 梯子前端请注意版本问题
- 梯子配置链接：https://vpnyfrua.ccwu.cc/sub?token=97c57fbbe5f889b177152ebbc29a6bb0&clash
（结合前端使用）

## 1. 一次性设置

- 安装视频播放软件
- 安装 Git：https://git-scm.com/downloads  
- 配置身份（运行一次）：

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## 2. 克隆仓库
```bash
git clone https://github.com/yfrua/AverageGregTechTranslation.git
cd AverageGregTechTranslation
```

## 3. 编辑字幕文件
在文本编辑器中打开 `.srt` 文件，**仅修改需要翻译的文本行**。  

**请勿修改**：
- 字幕序号（1, 2, 3, ...）
- 时间码行（如 `00:00:01,000 --> 00:00:04,000`）
- 空行分隔符

## 4. 提交工作
- 查看改动（非必须，提交之前）：
```bash
git status
git diff
```

- 提交：
```
bash
git add <文件路径>
git commit -m "<提交信息>"
```

## 5. 同步仓库信息
在提交前同步远程仓库的任何变更：
```bash
git pull
```
或
```bash
git pull --rebase origin <你的分支名>
```

推送提交到远程仓库：  
- 如果是首次推送该分支：
```bash
git push -u origin translate/<文件名或主题>
```
  这样会自动设置远程跟踪。
- 之后只需运行 `git push` 即可推送该分支的任何提交。

---

**翻译完成后**，可以在 GitHub 上从您的分支向 `main` 发起拉取请求（PR）。分支合并到 main 后，通常会在远程删除，但您也需要在本地删除它：
```bash
git branch -D translate/<文件名或主题>
```

---

**同步远程仓库**  
特性分支工作流的思想是保持 `main` 分支稳定，同时各个特性分支活跃。  

这并不能让您免于执行 `git pull` 以与他人保持同步，但能使不同项目的工作互不干扰。`main` 分支只有在其他分支的翻译工作全部完成并合并后才会被更新。

因此，在每次工作前，请先同步远程仓库：
```bash
git pull --all
```

如果 `main` 分支有更新，请将最新的 main 合并到您的分支：
```bash
git checkout translate/<文件名或主题>
git rebase main
```

如果出现合并冲突，请立即寻求帮助，或仔细解决冲突文件中的问题，然后：
```bash
git add <冲突文件>
git commit
```

---

**常用 Git 命令速查表**
| 命令                     | 说明                   |
| ------------------------ | ---------------------- |
| `git status`             | 查看已更改的文件       |
| `git diff`               | 查看具体行变更         |
| `git add <文件>`         | 暂存文件               |
| `git commit -m "消息"`   | 提交暂存的更改         |
| `git pull origin <分支>` | 获取指定分支的最新更新 |
| `git push`               | 推送您的分支           |
| `git checkout <分支>`    | 切换分支               |
| `git checkout -b <分支>` | 创建并切换分支         |
| `git branch -D <分支>`   | 删除本地分支           |
