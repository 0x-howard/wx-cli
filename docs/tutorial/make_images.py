#!/usr/bin/env python3
"""把教程里的关键终端输出渲染成「终端截图」风格的 SVG（已脱敏）。

    python3 docs/tutorial/make_images.py   # 输出到 docs/tutorial/images/
行首标记：`$ ` 命令，`# ` 注释，`!!` 高亮行。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "images"
CHAR_W, LINE_H, PAD = 8.2, 19, 18

COLORS = {
    "cmd": "#89dceb",
    "comment": "#7f849c",
    "err": "#f38ba8",
    "ok": "#a6e3a1",
    "warn": "#f9e2af",
    "text": "#cdd6f4",
}
ERR_WORDS = ("error", "错误", "✗", "failed", "失败", "not permitted", "未成功", "kr=5")
OK_WORDS = ("✓", "成功", "Finished", "完成", "Signature=adhoc", "Got task port")
WARN_WORDS = ("警告", "warning", "仍有", "超时")


def display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def classify(line: str) -> str:
    if line.startswith("$ "):
        return "cmd"
    if line.startswith("# "):
        return "comment"
    low = line.lower()
    if any(w.lower() in low for w in ERR_WORDS):
        return "err"
    if any(w in line for w in OK_WORDS):
        return "ok"
    if any(w.lower() in low for w in WARN_WORDS):
        return "warn"
    return "text"


def render(title: str, body: str) -> str:
    lines = body.strip("\n").splitlines()
    width = max(display_width(l.lstrip("!")) for l in lines + [title]) * CHAR_W + PAD * 2
    width = max(width, 560)
    height = len(lines) * LINE_H + PAD * 2 + 34
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height}" '
        f'viewBox="0 0 {width:.0f} {height}">',
        f'<rect width="100%" height="100%" rx="10" fill="#1e1e2e"/>',
        '<rect width="100%" height="30" rx="10" fill="#313244"/>',
        '<rect y="20" width="100%" height="10" fill="#313244"/>',
        '<circle cx="18" cy="15" r="6" fill="#f38ba8"/>',
        '<circle cx="38" cy="15" r="6" fill="#f9e2af"/>',
        '<circle cx="58" cy="15" r="6" fill="#a6e3a1"/>',
        f'<text x="{width / 2:.0f}" y="20" fill="#bac2de" font-size="13" text-anchor="middle" '
        f'font-family="PingFang SC, Helvetica, sans-serif">{escape(title)}</text>',
    ]
    y0 = 30 + PAD
    for i, raw in enumerate(lines):
        hl = raw.startswith("!!")
        line = raw[2:] if hl else raw
        y = y0 + i * LINE_H
        if hl:
            out.append(
                f'<rect x="{PAD - 6}" y="{y - 1}" width="{width - 2 * PAD + 12:.0f}" '
                f'height="{LINE_H}" rx="3" fill="#f9e2af" fill-opacity="0.14"/>'
            )
        out.append(
            f'<text x="{PAD}" y="{y + 14}" fill="{COLORS[classify(line)]}" font-size="13.5" '
            f'font-family="Menlo, SF Mono, PingFang SC, monospace" xml:space="preserve">'
            f"{escape(line)}</text>"
        )
    out.append("</svg>")
    return "\n".join(out)


SHOTS: dict[str, tuple[str, str]] = {
    "01-build-link-error": ("坑 1：cargo build 链接失败（macOS 27 SDK）", """
$ cargo build --release
   Compiling serde_core v1.0.228
error: linking with `cc` failed: exit status: 1
!!  = note: ld: multiple errors: tapi error: malformed file
!!    /Library/Developer/CommandLineTools/SDKs/MacOSX27.0.sdk/usr/lib/libSystem.B.tbd:4:20: error: unknown architecture
          clang: error: linker command failed with exit code 1
error: could not compile `serde_core` (build script) due to 1 previous error
# 解决：SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk
"""),
    "02-build-openssl-space": ("坑 2：OpenSSL 构建失败（路径含空格）", """
$ cargo build --release      # 项目放在 \"/Users/you/Wechat Data/\" 下
error: failed to run custom build command for `openssl-sys v0.9.112`
!!  cp: Data/wx-cli-runtime/target/release/build/openssl-sys-.../OpenSSLConfig.cmake: Not a directory
  make: *** [install_dev] Error 1
  Error installing OpenSSL:
      'make' reported failure with exit status: 2
# 解决：CARGO_TARGET_DIR=$HOME/wx-cli-build（不含空格的路径）
"""),
    "03-build-success": ("编译成功", """
$ export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.sdk
$ export CARGO_TARGET_DIR=$HOME/wx-cli-build
$ cargo build --release
   Compiling rusqlite v0.31.0
   Compiling wx-cli v0.6.3 (/Users/you/Wechat Data/wx-cli)
!!    Finished `release` profile [optimized] target(s) in 1m 06s
$ ./wx --version
wx 0.6.3
"""),
    "04-task-for-pid": ("坑 3：官方签名微信，task_for_pid 被拒", """
$ sudo ./wx init
检测微信数据目录...
数据目录: ~/Library/Containers/com.tencent.xinWeChat/.../xwechat_files/wxid_xxxx/db_storage
扫描加密密钥…
WeChat PID: 7845
!!WeChat 签名: 官方 Hardened Runtime（内存扫描需要 sudo；hook 也建议 sudo）
找到 26 个加密数据库
!!错误: task_for_pid 失败 (kr=5)。
当前 WeChat 是官方 Hardened Runtime 签名。请从本机 GUI Terminal 重试，并在「开发者工具」中允许该 Terminal。
# 给终端开了「开发者工具」权限后重试，结果完全一样
"""),
    "05-resign-blocked": ("坑 4：重签名被 macOS「App 管理」拦截", """
$ sudo xattr -cr /Applications/WeChat.app
xattr: [Errno 1] Operation not permitted: '/Applications/WeChat.app'
$ sudo codesign --force --deep --sign - /Applications/WeChat.app
/Applications/WeChat.app: replacing existing signature
!!/Applications/WeChat.app: Operation not permitted
In subcomponent: /Applications/WeChat.app/Contents/MacOS/WeChatAppEx.app
# 解决：给终端宿主（Cursor / Terminal）开「App 管理」+「完全磁盘访问」，⌘Q 重启后再执行
"""),
    "06-resign-ok": ("重签名成功", """
$ pgrep -x WeChat && echo \"还在运行\" || echo \"已退出\"
已退出
$ sudo xattr -cr /Applications/WeChat.app
$ sudo codesign --force --deep --sign - /Applications/WeChat.app
/Applications/WeChat.app: replacing existing signature
$ codesign -dv /Applications/WeChat.app 2>&1 | grep -E \"Signature|flags\"
CodeDirectory v=20400 size=366 flags=0x2(adhoc) hashes=5+3 location=embedded
!!Signature=adhoc
"""),
    "07-init-partial": ("首次 init：只拿到 6/26", """
$ sudo ./wx init
WeChat 签名: ad-hoc（无需再次签名；用户态 LLDB 通常可附加）
!!Got task port: 3855
内存扫描完成：x'hex' 候选 0 个，salt 邻接候选 213 个（读取约 1728.1 MB）
内存阶段匹配到 0/26 个数据库密钥
仍有 26 个数据库未匹配密钥，启动 LLDB hook 45s…
LLDB hook 捕获到 6 个 32-byte key
!!最终匹配到 6/26 个数据库密钥
[wx] 警告：仍有 20 个加密 DB 没有密钥（其中 7 个影响聊天完整性）：
  - message/message_1.db (407.7MB) [关键]
  - message/message_4.db (245.2MB) [关键]
  - message/media_0.db (308.4MB) [关键]
"""),
    "08-pid-unchanged": ("坑 5：以为重启了微信，其实 PID 没变", """
$ sudo ./wx key extract --hook-seconds 180
已有 9 个仍可解密的密钥，将与新扫描结果合并
!!WeChat PID: 56356          # 和上一次一模一样 → 微信根本没重启
内存扫描完成：x'hex' 候选 0 个，salt 邻接候选 225 个
!!LLDB: lldb -p 56356 （等待 180s，到期自动 detach）
LLDB hook 捕获到 7 个 32-byte key
最终匹配到 10/26 个数据库密钥
"""),
    "09-forgot-login": ("坑 6：挂上 hook 后忘了点登录", """
$ sudo ./wx key extract --hook-seconds 180
WeChat PID: 58154            # PID 变了，微信确实重启了
!!内存扫描完成：x'hex' 候选 0 个，salt 邻接候选 0 个（读取约 1208.1 MB）
LLDB: lldb -p 58154 （等待 180s，到期自动 detach）
!!LLDB hook 捕获到 0 个 32-byte key   # 没登录 → 微信没打开任何数据库
最终匹配到 10/26 个数据库密钥
"""),
    "10-login-too-early": ("坑 7：在内存扫描阶段就登录了（太早）", """
$ sudo ./wx key extract --hook-seconds 180
WeChat PID: 58154
扫描进程内存寻找密钥（x'hex' + salt 邻接）...
!!内存扫描完成：x'hex' 候选 0 个，salt 邻接候选 214 个   # ≠0 → 扫描时已经登录了
LLDB: lldb -p 58154 （等待 180s，到期自动 detach）
LLDB hook 捕获到 8 个 32-byte key
最终匹配到 10/26 个数据库密钥
# 旧消息库的 -shm 修改时间都是 12:16 = 登录那一刻，早于 hook 挂上的时间
"""),
    "11-success": ("正确时序：hook 挂好后再登录 → 25/26", """
$ sudo ./wx key extract --hook-seconds 240
WeChat PID: 61090
!!内存扫描完成：x'hex' 候选 0 个，salt 邻接候选 0 个   # =0 → 扫描时确实还没登录
仍有 16 个数据库未匹配密钥，启动 LLDB hook 240s…
LLDB: lldb -p 61090 （等待 240s，到期自动 detach）
# ←—— 此时才点「登录」
LLDB 超时，尝试终止…
!!LLDB hook 捕获到 33 个 32-byte key
!!最终匹配到 25/26 个数据库密钥
[wx] 警告：仍有 1 个加密 DB 没有密钥（其中 0 个影响聊天完整性）：
  - migrate/unspportmsg.db (76.0KB)
"""),
    "12-doctor": ("wx doctor：全部关键项通过", """
$ ./wx doctor
✓  WeChat 进程                    PID 61090
✓  SIP                          enabled — 取钥看 task_for_pid/TCC，不依赖关 SIP
✓  WeChat 签名                    ad-hoc
✓  lldb                         可用
✓  数据库密钥                        25 个密钥
!!✓  关键分片密钥                       聊天 / session / contact 齐全
✓  旁路库密钥                        1 个可选缺失（如 migrate/*）
✓  SQLCipher 在线打开               session.db OK
✓  message_fts 密钥               已配置（search 可走 FTS）
"""),
    "13-export-before": ("原生 wx export：大量 XML 噪音", """
### 2025-12-16 11:30
**示例群**: [系统] 12345678901@chatroom:
!!> <sysmsg type=\"sysmsgtemplate
**某群友**: <?xml version=\"1.0\"?>
!!> <msg bigheadimgurl=\"http://wx.qlogo.cn/mmhead/...\" username=\"v3_xxxx...@stranger\" ...
**某群友**: 有点搞笑[破涕为笑]
>   ↳ 群友A: <?xml version=\"1.0\"?> <msg> <img aeskey=\"xxxxxxxx...\" ...
"""),
    "14-export-after": ("精简导出：一条消息一行", """
## 2026-10-16
- 12:37 **群友A**：有耐心愿意每天花时间选岗投岗可以进…（回复 群友B: 机构说进ie要一个月 有必要等嘛）
!!- 12:38 **群友C**：有点搞笑[破涕为笑]（回复 群友A: [图片]）
- 12:43 **群友A**：每个基金会选岗方式都不太相同，ie类似于国内boss直聘…
- 12:45 **群友A**：这个是基金会（回复 群友D: ie是啥意思）
!!- 12:50 **群友A**：你得在Goolemap上看看周围地理位置怎么样，好不好找二工（回复 群友B: [图片]）
"""),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (title, body) in SHOTS.items():
        (OUT / f"{name}.svg").write_text(render(title, body))
    print(f"{len(SHOTS)} 张图 → {OUT}")


if __name__ == "__main__":
    main()
