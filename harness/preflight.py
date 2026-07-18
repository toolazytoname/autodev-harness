"""Pre-flight brief interrogation (T41).

The biggest pain point across harness runs: the pipeline goes dark for
hours, then produces something close-but-wrong. The user has no chance
to correct course until the very end. This module fixes that by grilling
the user with a fixed set of questions *before* any model call happens.

The questions are deliberately a mix of:
  - things the brief said (confirm we parsed them right)
  - things the brief didn't say (force the user to pick a default)
  - things the harness is *guessing* (surface the guess so the user
    can overrule it before it becomes code)

In TTY mode the user types answers inline. In non-TTY (CI, scripted)
mode the answers must come from ``AUTODEV_PREFLIGHT_ANSWERS`` (path
to a JSON file) — otherwise the harness exits 1 with a clear "fill
this in first" message, so a silent run with no decisions is
impossible.

The answers are persisted to ``artifacts/preflight-answers.json`` so
the develop phase can read them and inject relevant ones (device,
visual direction, scope) into the generator's prompt.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PreflightAnswers:
    """One decision per question. ``None`` = "use harness default"."""

    product_form: Optional[str] = None      # web | uni-app | miniprogram | native-ios | native-android | desktop
    device: Optional[str] = None            # phone | phone-tablet | responsive | desktop
    visual: Optional[str] = None            # minimalist-ui | gpt-taste | industrial-brutalist-ui | stitch-design-taste
    scope_in: list[str] = field(default_factory=list)  # which features are v1 must-have
    auth: Optional[str] = None              # none | simple-password | accounts | wechat-openid
    notes: str = ""                         # free-form additions


QUESTIONS: list[tuple[str, str, list[str]]] = [
    (
        "product_form",
        "产品形态是什么？Harness 默认 web（React/Vite）。uni-app 一套代码同时输出微信小程序 + H5 + iOS/Android；纯 miniprogram 是单端原生小程序。",
        ["web", "uni-app (Vue 3 + 微信云开发)", "wechat-miniprogram (Taro)", "native-ios", "native-android", "desktop-electron"],
    ),
    (
        "device",
        "目标设备？这决定 layout 方向（mobile-first vs 桌面宽屏）。",
        ["phone", "phone-tablet", "responsive", "desktop"],
    ),
    (
        "visual",
        "视觉方向用哪个 taste skill？",
        ["minimalist-ui", "gpt-taste", "industrial-brutalist-ui", "stitch-design-taste", "let-harness-pick"],
    ),
    (
        "scope_in",
        "v1 必须做的 feature 列表（逗号分隔）。harness 会只 work on these。",
        [],  # free-form list
    ),
    (
        "auth",
        "登录 / 权限？uni-app + 微信云开发推荐 wechat-openid（云函数拿 OPENID，无需自建登录页）。",
        ["none", "simple-password", "accounts", "wechat-openid"],
    ),
]


def _autofill_from_brief(brief_text: str) -> PreflightAnswers:
    """Best-effort guess at product form / device / auth from the brief text.

    Keeps the user from having to answer things the brief already
    declared. Never raises — a regex miss just leaves the answer None
    and the user will be asked.

    Priority order for product_form (highest first):
      1. uni-app / uniapp / vue 3 / vite / 跨端 / 微信云开发 / wx.cloud
      2. 微信小程序 / miniprogram / wechat
      3. native iOS / Android
    """
    answers = PreflightAnswers()
    text = brief_text.lower()
    # uni-app 一类关键词(优先级最高,涵盖 miniprogram 编译产物)
    uniapp_signals = ("uni-app", "uniapp", "vue 3", "vue3", "wx.cloud", "cloudfunctions", "云开发", "跨端", "跨平台")
    if any(sig.lower() in text for sig in uniapp_signals):
        answers.product_form = "uni-app (Vue 3 + 微信云开发)"
        answers.auth = "wechat-openid"
    elif "小程序" in brief_text or "miniprogram" in text or "wechat" in text:
        answers.product_form = "wechat-miniprogram (Taro)"
        answers.auth = "wechat-openid"
    if "ios" in text and "android" not in text:
        answers.product_form = answers.product_form or "native-ios"
    if "桌面" in brief_text or "desktop" in text:
        answers.device = "desktop"
    elif "手机" in brief_text or "phone" in text or "移动" in brief_text:
        answers.device = "phone"
    return answers


def _print_header(project_dir: Path) -> None:
    sep = "━" * 60
    print(sep)
    print("Pre-flight: 我想跟你对齐几个事再动手")
    print(f"项目目录: {project_dir}")
    print(sep)


def _ask_one(key: str, prompt: str, options: list[str]) -> object:
    """Ask one question, return either a string (single) or list (multi)."""
    print()
    print(f"▸ {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    print(f"  (回车 = harness default)")
    if not options:  # free-form list
        print("  (逗号分隔)")
    while True:
        try:
            raw = input("  > ").strip()
        except EOFError:
            raw = ""
        if not raw:
            return None
        if not options:
            return [s.strip() for s in raw.split(",") if s.strip()]
        # Numeric choice
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        # Direct match
        for opt in options:
            if raw.lower() == opt.lower():
                return opt
        print(f"  (请输入 1-{len(options)} 的数字，或回车跳过)")


def run_preflight(project_dir: Path, brief_text: str) -> PreflightAnswers:
    """Run the pre-flight interrogation; return the answers.

    TTY mode: interactive prompts.
    Non-TTY mode: read from ``AUTODEV_PREFLIGHT_ANSWERS`` env var
    (path to JSON). If unset, print the questions + a clear exit
    message so a silent run can't sneak through.
    """
    answers_file = project_dir / "artifacts" / "preflight-answers.json"
    answers_file.parent.mkdir(parents=True, exist_ok=True)

    autofill = _autofill_from_brief(brief_text)
    if not sys.stdin.isatty():
        env_path = os.environ.get("AUTODEV_PREFLIGHT_ANSWERS")
        if not env_path:
            _print_header(project_dir)
            print()
            print("⚠️  非交互模式，需要先填 preflight 答案：")
            print("   1) 看下面这些问题")
            print("   2) 把答案写到 JSON")
            print("   3) AUTODEV_PREFLIGHT_ANSWERS=path.json python -m harness ...")
            print()
            for key, prompt, options in QUESTIONS:
                print(f"  • {prompt}")
            print()
            print("或在交互终端里直接跑（去掉 CI 标志）")
            sys.exit(1)
        with open(env_path) as fh:
            data = json.load(fh)
        answers = PreflightAnswers(**{**asdict(autofill), **data})
        answers_file.write_text(json.dumps(asdict(answers), indent=2, ensure_ascii=False))
        print(f"✓ preflight answers loaded from {env_path}")
        return answers

    _print_header(project_dir)
    print()
    print("我先从 brief 抓了几个明确点：")
    for field_name, value in asdict(autofill).items():
        if value and value not in ([], ""):
            print(f"  • {field_name}: {value}")
    print()
    print("下面这些要你确认 / 补全：")

    answers = autofill
    for key, prompt, options in QUESTIONS:
        result = _ask_one(key, prompt, options)
        if result is not None:
            setattr(answers, key, result)
    print()
    extra = input("▸ 还有什么要交代的（自由输入，回车跳过）:\n  > ").strip()
    if extra:
        answers.notes = extra
    answers_file.write_text(json.dumps(asdict(answers), indent=2, ensure_ascii=False))
    print()
    print(f"✓ 答案存到 {answers_file}")
    print("━" * 60)
    return answers
