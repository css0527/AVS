#!/usr/bin/env python3
"""Read-only audit of the AVS motion/concise defense deck.

Prints one JSON report to stdout. Optional --output writes only the report.
Run after rebuilding the deck; no deliverable is modified by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import posixpath
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, "/tmp/avs_ppt_deps")
from PIL import Image, ImageSequence

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EXPECTED_MOTION_PAGES = [1, 2, *range(4, 14)]
FORBIDDEN = ["下一步", "还需补录", "补齐", "仍需消融"]
VIDEO_NUMBER_PATTERNS = [
    r"0[.]996", r"99[.]6", r"7[.]52", r"13[.]94", r"4[.]26",
    r"7[.]5\s*(?:到|至|[-–—~～])\s*13[.]9", r"4[.]3\s*厘米",
    r"九十九点六", r"七点五到十三点九", r"四点三厘米",
    r"(?:五|5)类(?:走廊)?(?:危害|灾害|危险|安全)?标识", r"(?:四|4)个核心标记",
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def norm(value: str) -> str:
    return re.sub(r"\s+", "", value)


def cjk_count(value: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", value))


def leaves(value, prefix=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, f"{prefix}[{i}]")
    elif isinstance(value, str):
        yield prefix, value


def rels(zf, part):
    dirname, basename = posixpath.split(part)
    relfile = posixpath.join(dirname, "_rels", basename + ".rels")
    if relfile not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(relfile))
    result = {}
    for el in root.findall(f"{{{REL_NS}}}Relationship"):
        target = el.attrib["Target"]
        if el.attrib.get("TargetMode") == "External":
            resolved = target
        else:
            resolved = posixpath.normpath(posixpath.join(dirname, target))
            if resolved.startswith("/"):
                resolved = resolved.lstrip("/")
        result[el.attrib["Id"]] = {
            "target": resolved,
            "type": el.attrib.get("Type", "").rsplit("/", 1)[-1],
            "external": el.attrib.get("TargetMode") == "External",
        }
    return result


def notes_text(zf, slide_part):
    for r in rels(zf, slide_part).values():
        if r["type"] == "notesSlide":
            root = ET.fromstring(zf.read(r["target"]))
            for shape in root.findall(".//p:sp", NS):
                ph = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
                if ph is not None and ph.attrib.get("type") == "body":
                    return "\n".join(
                        "".join(t.text or "" for t in p.findall(".//a:t", NS))
                        for p in shape.findall("p:txBody/a:p", NS)
                    )
    return ""


def gif_info(data):
    with Image.open(io.BytesIO(data)) as im:
        frame_count = getattr(im, "n_frames", 1)
        loop = im.info.get("loop")
        durations = []
        pixels = set()
        for f in ImageSequence.Iterator(im):
            durations.append(int(f.info.get("duration", 0)))
            pixels.add(digest(f.convert("RGB").tobytes()))
        return {
            "format": im.format,
            "frames": frame_count,
            "loop": loop,
            "duration_ms": sum(durations),
            "min_frame_duration_ms": min(durations) if durations else 0,
            "distinct_rendered_frames": len(pixels),
            "size": list(im.size),
        }


def audit(root):
    here = root / "国赛答辩"
    report = {
        "audit": "AVS 动图与精简版 PPT 只读核验",
        "count_note": "可见文字字数统计 PPT 文本对象中的汉字；GIF 画面内文字另需目视检查。",
        "checks": {},
        "slides": [],
        "potential_issues": [],
    }
    checks = report["checks"]

    def check(key, passed, **detail):
        checks[key] = {"pass": bool(passed), **detail}

    required = {
        "deck": here / "AVS_国赛答辩.pptx",
        "content": here / "roadshow_content.json",
        "manifest": here / "PPT配图与版式核对.json",
        "old_counts": here / "历史版本/动态精简前_20261017/页面字数.json",
        "audio_audit": here / "配音制作/音画核对.json",
        "script": here / "AVS_国赛答辩逐页讲稿.md",
    }
    missing = [str(p) for p in required.values() if not p.is_file()]
    check("required_files", not missing, missing=missing)
    if missing:
        report["all_checks_pass"] = False
        return report
    content = json.loads(required["content"].read_text())
    manifest = json.loads(required["manifest"].read_text())
    old_counts = json.loads(required["old_counts"].read_text())
    audio_audit = json.loads(required["audio_audit"].read_text())
    md = required["script"].read_text()
    pages = content["slides"]
    page_map = {int(s["page"]): s for s in pages}
    manifest_map = {int(s["page"]): s for s in manifest["slides"]}
    old_map = {int(s["page"]): int(s["cjk_text"]) for s in old_counts}
    headings = list(re.finditer(r"(?m)^## 第(\d+)页[^\n]*", md))
    md_pages = {
        int(match.group(1)): md[match.start():headings[i + 1].start() if i + 1 < len(headings) else len(md)]
        for i, match in enumerate(headings)
    }
    json_bad = [
        {"path": path, "token": token, "text": value}
        for path, value in leaves(content) for token in FORBIDDEN if token in value
    ]
    md_bad = [token for token in FORBIDDEN if token in md]
    check("no_unfinished_phrases_in_content_and_script", not json_bad and not md_bad,
          json_matches=json_bad, markdown_matches=md_bad)
    main_pages = [int(s["page"]) for s in pages if not s.get("backup", s.get("hidden", False))]
    hidden_pages = [int(s["page"]) for s in pages if s.get("backup", s.get("hidden", False))]
    check("source_page_structure", len(pages) == 18 and main_pages == list(range(1, 15)) and hidden_pages == list(range(15, 19)),
          total=len(pages), main_pages=main_pages, hidden_pages=hidden_pages)
    main_budget = sum(float(s.get("seconds", 0)) for s in pages if not s.get("backup", s.get("hidden", False)))
    budget_matches = abs(main_budget - float(content["meta"]["planned_total_seconds"])) < .01 and abs(main_budget - float(manifest["total_target_seconds"])) < .01
    check("time_budget_under_480_seconds", main_budget < 480 and budget_matches,
          actual_seconds=main_budget, content_meta_seconds=content["meta"]["planned_total_seconds"],
          manifest_seconds=manifest["total_target_seconds"], margin_seconds=480 - main_budget)

    with zipfile.ZipFile(required["deck"]) as zf:
        pres = ET.fromstring(zf.read("ppt/presentation.xml"))
        pres_rels = rels(zf, "ppt/presentation.xml")
        slide_parts = [pres_rels[el.attrib[f"{{{NS['r']}}}id"]]["target"] for el in pres.findall("p:sldIdLst/p:sldId", NS)]
        actual_hidden = []
        actual_motion = []
        bad_phrases = []
        bad_numbers = []
        gif_errors = []
        mismatch_notes = []
        mismatch_manifest_text = []
        embedded_movies = []
        all_visible = []
        content_motion_mismatches = []
        for page_no, slide_part in enumerate(slide_parts, 1):
            xml = ET.fromstring(zf.read(slide_part))
            is_hidden = xml.attrib.get("show") in ("0", "false")
            if is_hidden:
                actual_hidden.append(page_no)
            texts = [t.text or "" for t in xml.findall(".//a:t", NS)]
            text = "\n".join(texts)
            all_visible.append(text)
            notes = notes_text(zf, slide_part)
            if norm(notes) != norm(md_pages.get(page_no, "")):
                mismatch_notes.append({"page": page_no, "has_notes": bool(notes), "has_markdown_section": page_no in md_pages})
            source = page_map.get(page_no, {})
            speech = source.get("speech", "")
            if speech and (norm(speech) not in norm(notes) or norm(speech) not in norm(md_pages.get(page_no, ""))):
                mismatch_notes.append({"page": page_no, "speech_missing_or_changed": True})
            for label, value in [("visible", text), ("notes", notes)]:
                for token in FORBIDDEN:
                    if token in value:
                        bad_phrases.append({"page": page_no, "where": label, "token": token})
            if page_no <= 14:
                for label, value in [("visible", text), ("speech", speech)]:
                    for pattern in VIDEO_NUMBER_PATTERNS:
                        match = re.search(pattern, value)
                        if match:
                            bad_numbers.append({"page": page_no, "where": label, "match": match.group()})
            declared = manifest_map.get(page_no, {})
            declared_text = "\n".join(str(t.get("text", "")) for t in declared.get("texts", []))
            if norm(declared_text) != norm(text):
                mismatch_manifest_text.append(page_no)
            slide_rels = rels(zf, slide_part)
            image_targets = []
            for blip in xml.findall(".//a:blip", NS):
                rid = blip.attrib.get(f"{{{NS['r']}}}embed")
                if rid and rid in slide_rels:
                    target = slide_rels[rid]["target"]
                    if target not in image_targets:
                        image_targets.append(target)
            images = []
            for target in image_targets:
                raw = zf.read(target)
                info = {"package_part": target, "sha256": digest(raw)}
                if target.lower().endswith(".gif"):
                    info.update(gif_info(raw))
                    if page_no not in actual_motion:
                        actual_motion.append(page_no)
                    if not (info["frames"] > 1 and info["loop"] == 0 and info["duration_ms"] > 0 and info["distinct_rendered_frames"] > 1 and info["min_frame_duration_ms"] > 0):
                        gif_errors.append({"page": page_no, "error": "GIF 不是有效无限循环多帧动画", **info})
                    expected = [im for im in declared.get("images", []) if im.get("animated")]
                    matches = [im for im in expected if im.get("sha256") == info["sha256"]]
                    if not matches:
                        gif_errors.append({"page": page_no, "error": "包内 GIF 与核对清单 SHA 不匹配", "part": target})
                    else:
                        for im in matches:
                            sourcefile = root / im["file"]
                            source_ok = sourcefile.is_file() and file_sha(sourcefile) == info["sha256"]
                            info["original_file"] = im["file"]
                            info["source_sha_matches"] = source_ok
                            if not source_ok:
                                gif_errors.append({"page": page_no, "error": "GIF 源文件缺失或与包内文件不同", "file": im["file"]})
                            if im.get("frames") != info["frames"]:
                                gif_errors.append({"page": page_no, "error": "GIF 帧数与核对清单不同"})
                            if im.get("duration_ms") != info["duration_ms"]:
                                gif_errors.append({"page": page_no, "error": "GIF 时长与核对清单不同"})
                    content_asset = source.get("motion_asset")
                    if not content_asset or not (root / content_asset).is_file() or file_sha(root / content_asset) != info["sha256"]:
                        content_motion_mismatches.append({"page": page_no, "source_motion_asset": content_asset, "package_part": target})
                images.append(info)
            for r in slide_rels.values():
                if r["type"] in ("video", "media") and not r["external"] and r["target"].lower().endswith(".mp4"):
                    item = {"page": page_no, "package_part": r["target"], "sha256": digest(zf.read(r["target"]))}
                    if item not in embedded_movies:
                        embedded_movies.append(item)
            previous = old_map.get(page_no)
            current = cjk_count(text)
            report["slides"].append({
                "page": page_no, "title": source.get("title"), "hidden": is_hidden,
                "cjk_visible_text_before": previous, "cjk_visible_text_now": current,
                "cjk_reduction": None if previous is None else previous - current,
                "reduction_percent": None if not previous else round(100 * (previous - current) / previous, 1),
                "notes_match_markdown": norm(notes) == norm(md_pages.get(page_no, "")),
                "images": images,
            })
        check("package_page_structure", len(slide_parts) == 18 and actual_hidden == list(range(15, 19)),
              total=len(slide_parts), main=len(slide_parts)-len(actual_hidden), hidden_pages=actual_hidden)
        check("motion_coverage", actual_motion == EXPECTED_MOTION_PAGES and manifest.get("animated_pages") == EXPECTED_MOTION_PAGES,
              expected_pages=EXPECTED_MOTION_PAGES, actual_pages=actual_motion,
              manifest_animated_pages=manifest.get("animated_pages"))
        check("gif_frames_loops_hashes", not gif_errors, errors=gif_errors)
        check("source_content_motion_links_match_package", not content_motion_mismatches, mismatches=content_motion_mismatches)
        check("package_text_matches_manifest", not mismatch_manifest_text, mismatch_pages=mismatch_manifest_text)
        check("markdown_and_notes_match", not mismatch_notes and len(md_pages) == 18, mismatches=mismatch_notes)
        check("no_unfinished_phrases_in_package", not bad_phrases, matches=bad_phrases)
        check("no_video_result_numbers_repeated_on_main_slides", not bad_numbers, matches=bad_numbers)

    current_main = sum(s["cjk_visible_text_now"] for s in report["slides"] if s["page"] <= 14)
    previous_main = sum(old_map.get(p, 0) for p in range(1, 15))
    grown = [s["page"] for s in report["slides"] if s["page"] <= 14 and (s["cjk_reduction"] is None or s["cjk_reduction"] < 0)]
    check("main_visible_text_reduced", current_main < previous_main and not grown,
          before=previous_main, now=current_main, reduction_percent=round(100*(previous_main-current_main)/previous_main, 1),
          pages_with_more_text=grown)
    for s in report["slides"]:
        if s["page"] <= 14 and s["cjk_visible_text_now"] > 100:
            report["potential_issues"].append(f"第 {s['page']} 页仍有 {s['cjk_visible_text_now']} 个可见汉字，建议目视确认重点层次。")
        if s["page"] <= 14 and s["cjk_reduction"] == 0:
            report["potential_issues"].append(f"第 {s['page']} 页文字数量与旧版相同，请确认是否已通过布局突出重点。")
    for page, source in page_map.items():
        main_text = source.get("speech", "") + "\n" + source.get("title", "")
        matches = re.findall(r"未来|有待|尚未|计划|待完成|待验证|将进一步|准备继续", main_text)
        if page <= 14 and matches:
            report["potential_issues"].append(f"第 {page} 页主讲或标题含需人工确认的未来/未完成表述：{','.join(matches)}。")

    expected_video_sha = audio_audit.get("video_sha256")
    video = here / "B09018834.mp4"
    submission = root / "avs_ws/submission/B09018834.mp4"
    external_videos = {str(video.relative_to(root)): file_sha(video) if video.exists() else None,
                       str(submission.relative_to(root)): file_sha(submission) if submission.exists() else None}
    movie_ok = bool(embedded_movies) and all(m["page"] == 3 and m["sha256"] == expected_video_sha for m in embedded_movies)
    movie_ok = movie_ok and all(v == expected_video_sha for v in external_videos.values())
    video_manifest = manifest_map.get(3, {}).get("video", {})
    movie_ok = movie_ok and video_manifest.get("sha256") == expected_video_sha
    check("video_matches_completed_voiceover", movie_ok, expected_sha256=expected_video_sha,
          embedded_movies=embedded_movies, external_videos=external_videos, manifest_sha256=video_manifest.get("sha256"))
    if video.exists():
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)]))
        duration = float(probe["format"]["duration"])
        stream_types = [s["codec_type"] for s in probe["streams"]]
        check("video_audio_subtitle_duration", stream_types.count("video") == 1 and stream_types.count("audio") == 1 and "subtitle" not in stream_types and abs(duration - float(audio_audit["duration_seconds"])) < .1,
              duration_seconds=duration, stream_types=stream_types, audio_audit_duration_seconds=audio_audit["duration_seconds"])
    report["all_checks_pass"] = all(item["pass"] for item in checks.values())
    report["failed_checks"] = [key for key, item in checks.items() if not item["pass"]]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/home/c/AVS"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = audit(args.root.resolve())
    except Exception as e:
        report = {"all_checks_pass": False, "fatal_error": f"{type(e).__name__}: {e}"}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    return 0 if report.get("all_checks_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
