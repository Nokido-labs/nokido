# cmux Study — manaflow-ai/cmux


## README.md (full)
```
<h1 align="center">cmux</h1>
<p align="center">A Ghostty-based macOS terminal with vertical tabs and notifications for AI coding agents</p>

<p align="center">
  <a href="https://github.com/manaflow-ai/cmux/releases/latest/download/cmux-macos.dmg">
    <img src="./docs/assets/macos-badge.png" alt="Download cmux for macOS" width="180" />
  </a>
</p>

<p align="center">
  English | <a href="README.ja.md">日本語</a> | <a href="README.vi.md">Tiếng Việt</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.de.md">Deutsch</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.it.md">Italiano</a> | <a href="README.da.md">Dansk</a> | <a href="README.pl.md">Polski</a> | <a href="README.ru.md">Русский</a> | <a href="README.bs.md">Bosanski</a> | <a href="README.ar.md">العربية</a> | <a href="README.no.md">Norsk</a> | <a href="README.pt-BR.md">Português (Brasil)</a> | <a href="README.th.md">ไทย</a> | <a href="README.tr.md">Türkçe</a> | <a href="README.km.md">ភាសាខ្មែរ</a> | <a href="README.uk.md">Українська</a>
</p>

<p align="center">
  <a href="https://x.com/manaflowai"><img src="https://img.shields.io/badge/@manaflow-555?logo=x" alt="X / Twitter" /></a>
  <a href="https://discord.gg/xsgFEVrWCZ"><img src="https://img.shields.io/badge/Discord-555?logo=discord" alt="Discord" /></a>
  <a href="https://github.com/manaflow-ai/cmux"><img src="https://img.shields.io/github/stars/manaflow-ai/cmux?style=flat&logo=github&label=stars&color=4c71f2" alt="GitHub stars" /></a>
</p>

<p align="center">
  <img src="./docs/assets/main-first-image.png" alt="cmux screenshot" width="900" />
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=i-WxO5YUTOs">▶ Demo video</a> · <a href="https://cmux.com/blog/zen-of-cmux">The Zen of cmux</a>
</p>

## Features

<table>
<tr>
<td width="40%" valign="middle">
<h3>Notification rings</h3>
Panes get a blue ring and tabs light up when coding agents need your attention
</td>
<td width="60%">
<img src="./docs/assets/notification-rings.png" alt="Notification rings" width="100%" />
</td>
</tr>
<tr>
<td width="40%" valign="middle">
<h3>Notification panel</h3>
See all pending notifications in one place, jump to the most recent unread
</td>
<td width="60%">
<img src="./docs/assets/sidebar-notification-badge.png" alt="Sidebar notification badge" width="100%" />
</td>
</tr>
<tr>
<td width="40%" valign="middle">
<h3>In-app browser</h3>
Split a browser alongside your terminal with a scriptable API ported from <a href="https://github.com/vercel-labs/agent-browser">agent-browser</a>
</td>
<td width="60%">
<img src="./docs/assets/built-in-browser.png" alt="Built-in browser" width="100%" />
</td>
</tr>
<tr>
<td width="40%" valign="middle">
<h3>Vertical + horizontal tabs</h3>
Sidebar shows git branch, linked PR status/number, working directory, listening ports, and latest notification text. Split horizontally and vertically.
</td>
<td width="60%">
<img src="./docs/assets/vertical-horizontal-tabs-and-splits.png" alt="Vertical tabs and split panes" width="100%" />
</td>
</tr>
<tr>
<td width="40%" valign="middle">
<h3>SSH</h3>
<code>cmux ssh user@remote</code> creates a workspace for a remote machine. Browser panes route through the remote network so localhost just works. Drag an image into a remote session to upload via scp.
</td>
<td width="60%">
<img src="./docs/assets/ssh.png" alt="cmux SSH" width="100%" />
</td>
</tr>
<tr>
<td width="40%" valign="middle">
<h3>Claude Code Teams</h3>
<code>cmux claude-teams</code> runs Claude Code's teammate mode with one command. Teammates spawn as native splits with sidebar metadata and notifications. No tmux required.
</td>
<td width="60%">
<img src="./docs/assets/claude-code-teams.png" alt="Claude Code Teams" width="100%" />
</td>
</tr>
</table>

- **Browser import** — Import cookies, history, and sessions from Chrome, Firefox, Arc, and 20+ browsers so browser panes start authenticated
- **Custom commands** — Define project-specific actions in [`cmux.json`](https://cmux.com/docs/custom-commands) that launch from the command palette
- **Scriptable** — CLI and socket API to create workspaces, split panes, send keystrokes, and automate the browser
- **Native macOS app** — Built with Swift and AppKit, not Electron. Fast startup, low memory.
- **Ghostty compatible** — Reads your existing `~/.config/ghostty/config` for themes, fonts, and colors
- **GPU-accelerated** — Powered by libghostty for smooth rendering

## Install

### DMG (recommended)

<a href="https://github.com/manaflow-ai/cmux/releases/latest/download/cmux-macos.dmg">
  <img src="./docs/assets/macos-badge.png" alt="Download cmux for macOS" width="180" />
</a>

Open the `.dmg` and drag cmux to your Applications folder. cmux auto-updates via Sparkle, so you only need to download once.

### Homebrew

```bash
brew tap manaflow-ai/cmux
brew install --cask cmux
```

To update later:

```bash
brew upgrade --cask cmux
```

On first launch, macOS may ask you to confirm opening an app from an identified developer. Click **Open** to proceed.

## Why cmux?

I run a lot of Claude Code and Codex sessions in parallel. I was using Ghostty with a bunch of split panes, and relying on native macOS notifications to know when an agent needed me. But Claude Code's notification body is always just "Claude is waiting for your input" with no context, and with enough tabs open I couldn't even read the titles anymore.

I tried a few coding orchestrators but most of them were Electron/Tauri apps and the performance bugged me. I also just prefer the terminal since GUI orchestrators lock you into their workflow. So I built cmux as a native macOS app in Swift/AppKit. It uses libghostty for terminal rendering and reads your existing Ghostty config for themes, fonts, and colors.

The main additions are the sidebar and notification system. The sidebar has vertical tabs that show git branch, linked PR status/number, working directory, listening ports, and the latest notification text for each workspace. The notification system picks up terminal sequences (OSC 9/99/777) and has a CLI (`cmux notify`) you can wire into agent hooks for Claude Code, OpenCode, etc. When an agent is waiting, its pane gets a blue ring and the tab lights up in the sidebar, so I can tell which one needs me across splits and tabs. Cmd+Shift+U jumps to the most recent unread.

The in-app browser has a scriptable API ported from [agent-browser](https://github.com/vercel-labs/agent-browser). Agents can snapshot the accessibility tree, get element refs, click, fill forms, and evaluate JS. You can split a browser pane next to your terminal and have Claude Code interact with your dev server directly.

Everything is scriptable through the CLI and socket API — create workspaces/tabs, split panes, send keystrokes, open URLs in the browser.

## The Zen of cmux

cmux is not prescriptive about how developers hold their tools. It's a terminal and browser with a CLI, and the rest is up to you.

cmux is a primitive, not a solution. It gives you a terminal, a browser, notifications, workspaces, splits, tabs, and a CLI to control all of it. cmux doesn't force you into an opinionated way to use coding agents. What you build with the primitives is yours.

The best developers have always built their own tools. Nobody has figured out the best way to work with agents yet, and the teams building closed products definitely haven't either. The developers closest to their own codebases will figure it out first.

Give a million developers composable primitives and they'll collectively find the most efficient workflows faster than any product team could design top-down.

## Documentation

For more info on how to configure cmux, [head over to our docs](https://cmux.com/docs/getting-started?utm_source=readme).

## Keyboard Shortcuts

### Workspaces

| Shortcut | Action |
|----------|--------|
| ⌘ N | New workspace |
| ⌘ 1–8 | Ju
```

## package.json
```json
{
  "scripts": {
    "feed-tui": "bun Resources/feed-tui/index.ts"
  },
  "dependencies": {
    "@opentui/core": "^0.1.106",
    "vercel": "^50.9.5"
  },
  "license": "GPL-3.0-or-later"
}

```

## Repository structure
- [dir] .circleci
- [dir] .claude
- [dir] .github
- [file] .gitignore
- [file] .gitkeep
- [file] .gitmodules
- [file] .vercelignore
- [file] AGENTS.md
- [dir] AppIcon.icon
- [dir] Assets.xcassets
- [file] CHANGELOG.md
- [file] CLAUDE.md
- [dir] CLI
- [file] CONTRIBUTING.md
- [dir] GhosttyTabs.xcodeproj
- [file] LICENSE
- [file] PROJECTS.md
- [file] Package.resolved
- [file] Package.swift
- [dir] Packages
- [dir] Prototypes
- [file] README.ar.md
- [file] README.bs.md
- [file] README.da.md
- [file] README.de.md
- [file] README.es.md
- [file] README.fr.md
- [file] README.it.md
- [file] README.ja.md
- [file] README.km.md

## SearxNG: cmux manaflow tmux multi terminal AI
- **cmux — The terminal built for multitasking**
  https://cmux.com/
  tmux is a terminal multiplexer that runs inside any terminal. cmux is a native macOS app with a GUI: vertical tabs, split panes, an embedded browser, and a ...
- **GitHub - manaflow-ai/cmux: Ghostty-based macOS terminal with vertical ...**
  https://github.com/manaflow-ai/cmux
  Teammates spawn as native splits with sidebar metadata and notifications. No tmux required. Claude Code Teams. Browser import — Import cookies, ...
- **cmux: The Terminal Built for AI Coding Agents - DEV Community**
  https://dev.to/neuraldownload/cmux-the-terminal-built-for-ai-coding-agents-3l7h
  If you need cross-platform support — keep tmux. cmux isn't trying to replace tmux everywhere. It's solving a specific problem that tmux was never designed for: multi-agent awareness, in a world where 
- **tmux control panel integration #560 - manaflow-ai/cmux - GitHub**
  https://github.com/manaflow-ai/cmux/issues/560
  26 févr. 2026 · 1. The current fallback is reading the wrong layer under tmux. We tried multiple approaches on the cmux side: ghostty_surface_read_text ...
- **cmux vs tmux — Agent Terminal vs Terminal Multiplexer (2026) - Solo**
  https://soloterm.com/cmux-vs-tmux
  Compare cmux and tmux: new open source agent terminal vs the standard multiplexer. Notification rings vs remote persistence, agent-first vs battle-tested. Solo matters if neither covers local process 

## SearxNG: cmux open source coding agents parallel browser
- **cmux — The terminal built for multitasking**
  https://cmux.com/
  cmux is a terminal, so any agent that runs in a terminal works out of the box: Claude Code, Codex, OpenCode, Gemini CLI, Kiro, Aider, Goose, Amp, Cline, Cursor ...
- **manaflow-ai/cmux: Ghostty-based macOS terminal with vertical tabs ...**
  https://github.com/manaflow-ai/cmux
  Agents can snapshot the accessibility tree, get element refs, click, fill forms, and evaluate JS. You can split a browser pane next to your terminal and have ...
- **cmux: Native macOS Terminal for AI Coding Agents - Better Stack**
  https://betterstack.com/community/guides/ai/cmux-terminal/
  Discover cmux: Swift-based terminal built for AI agent orchestration. Learn CLI commands, browser automation with DOM snapshots, multi-pane agent parallelism, libghostty integration, and creating rich
- **I Run 10 Claude Code Agents Easily Using This App - Medium**
  https://medium.com/vibe-coding/i-run-10-claude-code-agents-easily-using-this-app-b1926d7bd83c
  7 avr. 2026 · cmux is a free Mac terminal app built on Ghostty that lets you run multiple Claude Code agents with smart notifications and a built-in ...
- **Mux: Introduction**
  https://mux.coder.com/
  Mux makes it easy to run parallel coding agents, each with its own isolated workspace, right from your browser or desktop. Mux is open source and LLM ...

## SearxNG: cmux electron multiplexer terminal panes
- **cmux — The terminal built for multitasking**
  https://cmux.com/
  How does it compare to tmux? tmux is a terminal multiplexer that runs inside any terminal. cmux is a native macOS app with a GUI: vertical tabs, split panes, an embedded browser, and a socket API are 
- **cmux: Native macOS Terminal for AI Coding Agents - Better Stack**
  https://betterstack.com/community/guides/ai/cmux-terminal/
  Discover cmux: Swift-based terminal built for AI agent orchestration. Learn CLI commands, browser automation with DOM snapshots, multi-pane agent parallelism, libghostty integration, and creating rich
- **GitHub - amirlehmam/wmux: Windows terminal multiplexer for AI agents ...**
  https://github.com/amirlehmam/wmux
  il y a 2 jours · Based on cmux. wmux is a Windows reimplementation of cmux, the macOS terminal for multitasking. Same design, same socket protocol, same ...
- **GitHub - manaflow-ai/cmux: Ghostty-based macOS terminal with vertical ...**
  https://github.com/manaflow-ai/cmux
  The notification system picks up terminal sequences (OSC 9/99/777) and has a CLI (cmux notify) you can wire into agent hooks for Claude Code, OpenCode, etc. When an agent is waiting, its pane gets a b
- **I built a Linux terminal workspace for managing multiple Claude Code ...**
  https://www.reddit.com/r/ClaudeAI/comments/1sgrjto/i_built_a_linux_terminal_workspace_for_managing/
  9 avr. 2026 · I built PrettyMux as a native Linux terminal workspace for multitask workflows and keeping track of my agents. It's a GTK4 app built on ...